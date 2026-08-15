"""CFO — Fase 2: qué significa cada número, y quién lo decidió.

Lo que se prueba acá es una frontera: la IA no calcula, no define y no
habilita. Y un número que no se puede calcular sale como "no se puede", con
el motivo, nunca como cero — porque alguien decide con ese cero.
"""
from datetime import date, datetime

from tests.test_api import _create_company, client  # noqa: I001
from tests.test_tenancy import _login, _make_user

from app import cfo_metricas, cfo_motor
from app.cfo_metricas import CATALOGO, Fuente
from app.db import SessionLocal
from app.models import Appointment, Company, FinanceMetricState, Service

FINANZAS = ["finance", "booking"]
DESDE, HASTA = date(2026, 7, 1), date(2026, 7, 31)


def _empresa(nombre: str):
    return _create_company(name=nombre, packs=FINANZAS)


def _servicio(cid: int, nombre: str, precio: int) -> int:
    db = SessionLocal()
    try:
        s = Service(company_id=cid, name=nombre, price_gs=precio, active=True)
        db.add(s)
        db.commit()
        return s.id
    finally:
        db.close()


def _doctor(cid: int) -> int:
    r = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dr. CFO"})
    return r.json()["id"]


def _atencion(cid: int, doctor_id: int, dia: int, service_id=None, estado="attended"):
    db = SessionLocal()
    try:
        a = Appointment(
            company_id=cid, doctor_id=doctor_id, patient_name="Paciente",
            patient_phone="595981000000", scheduled_at=datetime(2026, 7, dia, 10, 0),
            service_id=service_id, status=estado,
        )
        db.add(a)
        db.commit()
        return a.id
    finally:
        db.close()


def _aprobar(cid: int, clave: str, version=1, vigente_desde=None):
    cuerpo = {"version": version}
    if vigente_desde:
        cuerpo["vigente_desde"] = vigente_desde
    return client.post(f"/api/companies/{cid}/cfo/metricas/{clave}/aprobar", json=cuerpo)


def _calcular(cid: int, clave: str, desde=DESDE, hasta=HASTA):
    return client.post(f"/api/companies/{cid}/cfo/metricas/{clave}/calcular",
                       json={"desde": desde.isoformat(), "hasta": hasta.isoformat()})


# ─── El catálogo dice la verdad sobre lo que se puede ─────────────────────


def test_el_catalogo_dice_que_le_falta_a_cada_metrica():
    """Lo que hace honesto al producto: se ve de un vistazo qué puede
    contestar el CFO y qué no, en vez de descubrirlo cuando el dueño
    pregunta."""
    c = _empresa("Empresa Catálogo Métricas")
    filas = client.get(f"/api/companies/{c['id']}/cfo/metricas").json()
    por_clave = {f["clave"]: f for f in filas}

    # Ventas se puede: sale de datos propios del sistema.
    assert por_clave["ventas_netas"]["se_puede_aprobar"]
    assert por_clave["ventas_netas"]["fuentes_faltantes"] == []

    # Caja no: no hay tabla de caja ni banco en el sistema.
    assert not por_clave["flujo_de_caja"]["se_puede_aprobar"]
    assert "caja_y_bancos" in por_clave["flujo_de_caja"]["fuentes_faltantes"]

    # Y todas arrancan sin definir para una empresa nueva.
    assert por_clave["ventas_netas"]["estado"] == "sin_definir"


def test_la_utilidad_neta_no_se_puede_habilitar():
    """El número con el que se reparten dividendos. Calculado sin impuestos ni
    nómina no está incompleto: está mal."""
    c = _empresa("Empresa Utilidad")
    r = _aprobar(c["id"], "utilidad_neta")
    assert r.status_code == 409
    detalle = r.json()["detail"]
    assert detalle["codigo"] == "fuente_no_conectada"
    assert {"impuestos", "gastos", "nomina"} <= set(detalle["faltantes"])
    assert "todavía no puedo calcular" in detalle["motivo"]


def test_el_mensaje_dice_QUE_falta_conectar():
    """Decir 'no puedo' sin decir qué falta deja a alguien esperando un número
    que nunca va a llegar."""
    texto = cfo_metricas.explicar_faltante("flujo_de_caja", cfo_motor.FUENTES_DISPONIBLES)
    assert "caja_y_bancos" in texto
    assert "flujo de caja" in texto.lower()


# ─── Aprobar es un acto, no un efecto secundario ──────────────────────────


def test_sin_aprobar_no_se_calcula_aunque_haya_datos():
    """Deny by default. Una métrica que nadie aprobó no contesta un número,
    tenga o no los datos."""
    c = _empresa("Empresa Sin Aprobar")
    cid = c["id"]
    doc = _doctor(cid)
    svc = _servicio(cid, "Consulta", 150_000)
    _atencion(cid, doc, 5, svc)

    r = _calcular(cid, "ventas_netas").json()
    assert r["calculable"] is False
    assert r["valor"] is None, "devolvió un número sin definición aprobada"
    assert "no está aprobada" in r["advertencias"][0]


def test_aprobar_una_version_que_no_es_la_del_catalogo_falla():
    """Aprobar tiene que ser un acto sobre una definición concreta, no sobre
    'lo que diga el código hoy'."""
    c = _empresa("Empresa Versión")
    r = _aprobar(c["id"], "ventas_netas", version=99)
    assert r.status_code == 409
    assert r.json()["detail"]["codigo"] == "version_desactualizada"


def test_aprobada_y_activa_calcula():
    c = _empresa("Empresa Aprobada")
    cid = c["id"]
    doc = _doctor(cid)
    svc = _servicio(cid, "Consulta", 150_000)
    _atencion(cid, doc, 5, svc)
    _atencion(cid, doc, 6, svc)

    assert _aprobar(cid, "ventas_netas").status_code == 200
    r = _calcular(cid, "ventas_netas").json()
    assert r["calculable"] is True
    assert r["valor"] == 300_000
    assert r["detalle"]["atenciones"] == 2


def test_una_metrica_deprecada_deja_de_contestar():
    c = _empresa("Empresa Deprecada")
    cid = c["id"]
    _aprobar(cid, "ventas_netas")
    assert client.post(
        f"/api/companies/{cid}/cfo/metricas/ventas_netas/deprecar").status_code == 200
    assert _calcular(cid, "ventas_netas").json()["calculable"] is False


def test_la_vigencia_corta_hacia_atras():
    """Un cambio de criterio arranca una fecha. Contestar un período anterior
    con la definición nueva es responder otra pregunta."""
    c = _empresa("Empresa Vigencia")
    cid = c["id"]
    _aprobar(cid, "ventas_netas", vigente_desde="2026-08-01")
    r = _calcular(cid, "ventas_netas", DESDE, HASTA).json()
    assert r["calculable"] is False
    assert "rige desde" in r["advertencias"][0]


# ─── Los números ─────────────────────────────────────────────────────────


def test_solo_se_cuenta_lo_atendido():
    """Un turno confirmado al que el paciente no vino no es plata."""
    c = _empresa("Empresa Solo Atendido")
    cid = c["id"]
    doc = _doctor(cid)
    svc = _servicio(cid, "Consulta", 100_000)
    _atencion(cid, doc, 5, svc, estado="attended")
    _atencion(cid, doc, 6, svc, estado="no_show")
    _atencion(cid, doc, 7, svc, estado="confirmed")
    _aprobar(cid, "ventas_netas")

    assert _calcular(cid, "ventas_netas").json()["valor"] == 100_000


def test_una_atencion_sin_precio_baja_la_completitud_y_avisa():
    """Un total que sale de la mitad de las atenciones no puede presentarse
    como si fuera el total."""
    c = _empresa("Empresa Completitud")
    cid = c["id"]
    doc = _doctor(cid)
    svc = _servicio(cid, "Consulta", 100_000)
    _atencion(cid, doc, 5, svc)
    _atencion(cid, doc, 6, None)
    _aprobar(cid, "ventas_netas")

    r = _calcular(cid, "ventas_netas").json()
    assert r["valor"] == 100_000
    assert r["completitud"] == 0.5
    assert any("sin prestación" in a for a in r["advertencias"])


def test_el_neto_avisa_que_hoy_es_igual_al_bruto():
    """Sin fuente de descuentos ni devoluciones, el neto coincide con el
    bruto. Presentarlo como neto definitivo es una mentira prolija."""
    c = _empresa("Empresa Neto Igual Bruto")
    cid = c["id"]
    doc = _doctor(cid)
    svc = _servicio(cid, "Consulta", 200_000)
    _atencion(cid, doc, 5, svc)
    _aprobar(cid, "ventas_netas")
    _aprobar(cid, "ventas_brutas")

    neto = _calcular(cid, "ventas_netas").json()
    bruto = _calcular(cid, "ventas_brutas").json()
    assert neto["valor"] == bruto["valor"] == 200_000
    assert any("coincide con el bruto" in a for a in neto["advertencias"])
    # Y el bruto NO lleva ese aviso: es lo que dice ser.
    assert not any("coincide con el bruto" in a for a in bruto["advertencias"])


def test_el_resultado_viaja_con_su_procedencia():
    """Un número sin fuente ni fecha no sirve para decidir."""
    c = _empresa("Empresa Procedencia")
    cid = c["id"]
    _aprobar(cid, "ventas_netas")
    r = _calcular(cid, "ventas_netas").json()
    assert r["fuentes"] and r["corte"] and r["version"] == 1
    assert any("no es facturación contable" in a.lower() for a in r["advertencias"])


def test_el_ultimo_dia_del_periodo_entra_entero():
    c = _empresa("Empresa Último Día CFO")
    cid = c["id"]
    doc = _doctor(cid)
    svc = _servicio(cid, "Consulta", 50_000)
    _atencion(cid, doc, 31, svc)
    _aprobar(cid, "ventas_netas")
    assert _calcular(cid, "ventas_netas").json()["valor"] == 50_000


def test_los_montos_son_enteros_y_aguantan_cifras_grandes():
    """Guaraníes enteros, nunca float: 0.1 + 0.2 no es 0.3 y acá cada
    redondeo es plata de alguien."""
    c = _empresa("Empresa Montos Grandes")
    cid = c["id"]
    doc = _doctor(cid)
    svc = _servicio(cid, "Cirugía", 987_654_321)
    for dia in (5, 6, 7):
        _atencion(cid, doc, dia, svc)
    _aprobar(cid, "ventas_netas")
    r = _calcular(cid, "ventas_netas").json()
    assert r["valor"] == 987_654_321 * 3
    assert isinstance(r["valor"], int)


# ─── Aislamiento ─────────────────────────────────────────────────────────


def test_aprobar_en_una_empresa_no_aprueba_en_la_otra():
    a = _empresa("Empresa Métrica A")
    b = _empresa("Empresa Métrica B")
    _aprobar(a["id"], "ventas_netas")
    assert _calcular(a["id"], "ventas_netas").json()["calculable"] is True
    assert _calcular(b["id"], "ventas_netas").json()["calculable"] is False


def test_los_datos_de_otra_empresa_no_entran_en_el_calculo():
    a = _empresa("Empresa Datos A")
    b = _empresa("Empresa Datos B")
    doc_b = _doctor(b["id"])
    svc_b = _servicio(b["id"], "Consulta", 999_000)
    _atencion(b["id"], doc_b, 5, svc_b)
    _aprobar(a["id"], "ventas_netas")
    assert _calcular(a["id"], "ventas_netas").json()["valor"] == 0


def test_un_operador_no_aprueba_metricas():
    """Definir qué es una venta es administración, no operación."""
    c = _empresa("Empresa Permisos Métricas")
    cid = c["id"]
    _make_user("operador-metricas@test.py", cid, role="operator")
    op = _login("operador-metricas@test.py")
    assert op.get(f"/api/companies/{cid}/cfo/metricas").status_code == 403
    assert op.post(f"/api/companies/{cid}/cfo/metricas/ventas_netas/aprobar",
                   json={"version": 1}).status_code == 403


def test_sin_el_bloque_no_hay_metricas():
    c = _create_company(name="Comercio Sin Bloque Métricas")
    assert client.get(f"/api/companies/{c['id']}/cfo/metricas").status_code == 402


# ─── El contrato del catálogo ────────────────────────────────────────────


def test_toda_metrica_declara_formula_y_fuentes():
    """Una métrica sin fórmula escrita no se puede aprobar: quien firma no
    tiene qué leer."""
    for clave, m in CATALOGO.items():
        assert m.formula.strip(), f"{clave} no tiene fórmula"
        assert m.fuentes, f"{clave} no declara fuentes"
        assert m.version >= 1


def test_las_metricas_que_se_calculan_estan_en_el_catalogo():
    """Un calculador sin definición sería un número sin contrato."""
    for clave in cfo_motor._CALCULADORES:
        assert clave in CATALOGO, f"{clave} calcula pero no está definida"


def test_cero_sin_registros_se_distingue_de_cero_con_registros():
    """No es lo mismo "no vendiste nada" que "no cargaste nada".

    Visto en producción: con cero atenciones el bot escribió
    "₲ [valor pendiente]" —un marcador con forma de monto— en vez de decir
    que no había nada registrado. Prefirió disimular antes que contestar
    cero, y un marcador parece un dato.
    """
    c = _empresa("Empresa Sin Movimientos")
    cid = c["id"]
    _aprobar(cid, "ventas_netas")
    r = _calcular(cid, "ventas_netas").json()
    assert r["calculable"] is True
    assert r["valor"] == 0
    assert any("no se cargó nada" in a for a in r["advertencias"])

    # Con una atención de precio 0 el cero SÍ es un dato, y no lleva ese aviso.
    doc = _doctor(cid)
    gratis = _servicio(cid, "Control sin cargo", 0)
    _atencion(cid, doc, 5, gratis)
    r2 = _calcular(cid, "ventas_netas").json()
    assert r2["valor"] == 0
    assert not any("no se cargó nada" in a for a in r2["advertencias"])
