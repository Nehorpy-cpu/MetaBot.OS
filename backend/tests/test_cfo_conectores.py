"""CFO — Fase 6: de dónde salen los datos y de cuándo son.

Dos cosas se prueban acá, y ninguna es "el CSV se parsea":

1. Que **conectado no sea disponible**. Un conector vacío que habilitara el
   cálculo haría que el CFO conteste ₲ 0 con cara de certeza.
2. Que las planillas REALES entren. Las que exporta un sistema paraguayo
   traen `;`, `1.234.567` y `dd/mm/aaaa`. Un parser que solo acepta el CSV
   ideal no sirve para nadie.
"""
from datetime import date, datetime, timedelta

from tests.test_api import _create_company, client  # noqa: I001
from tests.test_tenancy import _login, _make_user

from app import cfo_conectores, cfo_csv
from app.cfo_metricas import Fuente
from app.db import SessionLocal
from app.models import FinanceConnector, FinanceRecord

FINANZAS = ["finance"]

PLANILLA = (
    "fecha,monto,categoria,referencia\n"
    "01/07/2026,1.500.000,Mostrador,F-001\n"
    "15/07/2026,2.300.000,Mayorista,F-002\n"
)


def _empresa(nombre: str) -> int:
    return _create_company(name=nombre, packs=FINANZAS)["id"]


def _conector(cid: int, fuente="ventas", nombre="Sistema de facturación") -> int:
    r = client.post(f"/api/companies/{cid}/cfo/conectores",
                    json={"fuente": fuente, "tipo": "csv", "nombre": nombre})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _subir(cid: int, con: int, contenido: str | bytes, nombre="ventas.csv"):
    datos = contenido.encode("utf-8") if isinstance(contenido, str) else contenido
    return client.post(
        f"/api/companies/{cid}/cfo/conectores/{con}/cargar",
        files={"archivo": (nombre, datos, "text/csv")},
    )


# ─── Conectado no es disponible ──────────────────────────────────────────


def test_un_conector_recien_creado_no_habilita_la_fuente():
    """Si habilitara, el motor calcularía sobre cero filas y contestaría ₲ 0
    con cara de certeza. Ese es el cero mentiroso que todo el módulo existe
    para evitar."""
    cid = _empresa("Conector Vacío")
    _conector(cid)
    db = SessionLocal()
    try:
        assert Fuente.VENTAS not in cfo_conectores.fuentes_disponibles(db, cid)
    finally:
        db.close()
    fuentes = {f["fuente"]: f for f in client.get(f"/api/companies/{cid}/cfo/fuentes").json()}
    assert fuentes["ventas"]["disponible"] is False
    assert fuentes["ventas"]["corte"] is None


def test_recien_con_filas_la_fuente_queda_disponible():
    cid = _empresa("Conector Con Filas")
    con = _conector(cid)
    assert _subir(cid, con, PLANILLA).status_code == 200
    db = SessionLocal()
    try:
        assert Fuente.VENTAS in cfo_conectores.fuentes_disponibles(db, cid)
    finally:
        db.close()


def test_apagar_el_conector_saca_la_fuente():
    """Y no hay que borrar los datos para eso: se apaga y el CFO deja de
    contestar con ellos."""
    cid = _empresa("Conector Apagado")
    con = _conector(cid)
    _subir(cid, con, PLANILLA)
    client.patch(f"/api/companies/{cid}/cfo/conectores/{con}", json={"activo": False})
    db = SessionLocal()
    try:
        assert Fuente.VENTAS not in cfo_conectores.fuentes_disponibles(db, cid)
    finally:
        db.close()


def test_lo_interno_siempre_esta():
    """Los turnos y los servicios con precio ya están adentro: no se conectan."""
    cid = _empresa("Fuente Interna")
    db = SessionLocal()
    try:
        assert Fuente.INTERNA in cfo_conectores.fuentes_disponibles(db, cid)
    finally:
        db.close()


# ─── Planillas de verdad ─────────────────────────────────────────────────


def test_entra_una_planilla_exportada_por_excel_en_castellano():
    """Separador `;`, montos con punto de miles, fechas dd/mm/aaaa. Es lo que
    sale del sistema de facturación de un comercio de acá."""
    cid = _empresa("Planilla Excel")
    con = _conector(cid)
    contenido = (
        "fecha;monto;categoria;referencia\n"
        "03/07/2026;1.234.567;Mostrador;A-1\n"
        "04/07/2026;890.000,00;Mostrador;A-2\n"
    )
    r = _subir(cid, con, contenido)
    assert r.status_code == 200, r.text
    assert r.json()["nuevas"] == 2

    db = SessionLocal()
    try:
        filas = db.query(FinanceRecord).filter(
            FinanceRecord.company_id == cid).order_by(FinanceRecord.referencia).all()
        assert [f.monto_gs for f in filas] == [1_234_567, 890_000]
        # El 3 de julio, no el 7 de marzo.
        assert filas[0].fecha == date(2026, 7, 3)
    finally:
        db.close()


def test_un_monto_con_punto_de_miles_no_se_lee_como_decimal():
    """`1.234.567` es un millón doscientos, no uno con veintitrés."""
    assert cfo_csv.leer_monto("1.234.567") == 1_234_567
    assert cfo_csv.leer_monto("1.234.567,00") == 1_234_567
    assert cfo_csv.leer_monto("1,234,567.00") == 1_234_567
    assert cfo_csv.leer_monto("890000") == 890_000
    assert cfo_csv.leer_monto("-450.000") == -450_000
    assert cfo_csv.leer_monto("₲ 1.500.000") == 1_500_000


def test_una_fecha_paraguaya_no_se_lee_al_reves():
    """03/07/2026 es julio. Leerlo al modo estadounidense no da error: da
    marzo, y nadie se entera."""
    assert cfo_csv.leer_fecha("03/07/2026") == date(2026, 7, 3)
    assert cfo_csv.leer_fecha("2026-07-03") == date(2026, 7, 3)


def test_un_archivo_en_cp1252_no_rompe():
    """Excel en Windows exporta así, y el acento llega roto o no llega."""
    cid = _empresa("Planilla Latin1")
    con = _conector(cid, fuente="gastos", nombre="Gastos")
    contenido = "fecha,monto,categoria,referencia\n01/07/2026,100.000,Días,G-1\n"
    assert _subir(cid, con, contenido.encode("cp1252")).status_code == 200
    db = SessionLocal()
    try:
        assert db.query(FinanceRecord).filter(
            FinanceRecord.company_id == cid).first().categoria == "Días"
    finally:
        db.close()


def test_si_una_fila_no_se_entiende_no_se_carga_ninguna():
    """Cargar 2 de 3 da un total que se ve bien, cierra mal, y nadie sabe por
    qué."""
    cid = _empresa("Planilla Rota")
    con = _conector(cid)
    contenido = (
        "fecha,monto,categoria,referencia\n"
        "01/07/2026,1.500.000,Mostrador,F-1\n"
        "no es fecha,2.000.000,Mostrador,F-2\n"
        "03/07/2026,1.000.000,Mostrador,F-3\n"
    )
    r = _subir(cid, con, contenido)
    assert r.status_code == 422
    detalle = r.json()["detail"]
    assert detalle["codigo"] == "planilla_invalida"
    # Y dice CUÁL fila, no "formato incorrecto".
    assert any("Fila 3" in x for x in detalle["renglones"])

    db = SessionLocal()
    try:
        assert db.query(FinanceRecord).filter(
            FinanceRecord.company_id == cid).count() == 0
    finally:
        db.close()


def test_subir_dos_veces_el_mismo_archivo_no_duplica():
    """Un dueño que sube dos veces vería sus ventas al doble y no tendría
    forma de saber por qué."""
    cid = _empresa("Planilla Repetida")
    con = _conector(cid)
    _subir(cid, con, PLANILLA)
    r = _subir(cid, con, PLANILLA)
    assert r.json()["nuevas"] == 0
    assert r.json()["actualizadas"] == 2

    db = SessionLocal()
    try:
        total = sum(f.monto_gs for f in db.query(FinanceRecord).filter(
            FinanceRecord.company_id == cid).all())
        assert total == 3_800_000
    finally:
        db.close()


def test_sin_referencia_tampoco_duplica():
    """Muchas exportaciones no traen un id. La referencia se deriva del
    contenido para que la recarga siga sin duplicar."""
    cid = _empresa("Planilla Sin Referencia")
    con = _conector(cid)
    contenido = "fecha,monto,categoria\n01/07/2026,500.000,Mostrador\n"
    _subir(cid, con, contenido)
    _subir(cid, con, contenido)
    db = SessionLocal()
    try:
        assert db.query(FinanceRecord).filter(
            FinanceRecord.company_id == cid).count() == 1
    finally:
        db.close()


def test_un_archivo_sin_las_columnas_dice_cuales_faltan():
    cid = _empresa("Planilla Sin Columnas")
    con = _conector(cid)
    r = _subir(cid, con, "algo,otra_cosa\n1,2\n")
    assert r.status_code == 422
    assert "fecha" in r.json()["detail"]["motivo"]


def test_un_archivo_vacio_no_deja_el_conector_como_exitoso():
    cid = _empresa("Planilla Vacía")
    con = _conector(cid)
    assert _subir(cid, con, "").status_code == 422
    estado = client.get(f"/api/companies/{cid}/cfo/conectores").json()[0]
    assert estado["ultima_sync_ok"] is False
    assert estado["ultimo_error"]
    assert estado["habilita_la_fuente"] is False


# ─── Frescura ────────────────────────────────────────────────────────────


def test_el_corte_es_la_sincronizacion_mas_vieja():
    """Con tres conectores y uno atrasado, los datos completos son los de
    ese. Quedarse con el más reciente sería contar la mejor mitad."""
    cid = _empresa("Frescura Mínima")
    a = _conector(cid, nombre="Sucursal centro")
    b = _conector(cid, nombre="Sucursal barrio")
    _subir(cid, a, PLANILLA)
    _subir(cid, b, PLANILLA.replace("F-00", "G-00"))

    viejo = datetime.utcnow() - timedelta(days=9)
    db = SessionLocal()
    try:
        db.get(FinanceConnector, a).ultima_sync_at = viejo
        db.commit()
        corte = cfo_conectores.corte_de(db, cid, Fuente.VENTAS)
        assert corte is not None
        assert abs((corte - viejo).total_seconds()) < 2
    finally:
        db.close()


def test_los_datos_viejos_se_avisan_pegados_al_numero():
    """Un número con datos de hace nueve días, sin decirlo, es peor que no
    contestar: el dueño decide igual."""
    cid = _empresa("Frescura Avisada")
    con = _conector(cid)
    _subir(cid, con, PLANILLA)
    db = SessionLocal()
    try:
        db.get(FinanceConnector, con).ultima_sync_at = (
            datetime.utcnow() - timedelta(days=9))
        db.commit()
        f = cfo_conectores.frescura(db, cid, [Fuente.VENTAS])
        assert f["advertencias"], "no avisó que los datos están viejos"
        assert "9 días" in f["advertencias"][0]
    finally:
        db.close()


def test_datos_recientes_no_generan_ruido():
    cid = _empresa("Frescura Fresca")
    con = _conector(cid)
    _subir(cid, con, PLANILLA)
    db = SessionLocal()
    try:
        assert cfo_conectores.frescura(db, cid, [Fuente.VENTAS])["advertencias"] == []
    finally:
        db.close()


def test_una_fuente_sin_datos_lo_dice_en_vez_de_dar_un_corte():
    cid = _empresa("Frescura Sin Datos")
    db = SessionLocal()
    try:
        f = cfo_conectores.frescura(db, cid, [Fuente.GASTOS])
        assert f["corte"] is None
        assert "No hay datos cargados" in f["advertencias"][0]
    finally:
        db.close()


def test_sumar_distingue_cero_sin_filas_de_cero_con_filas():
    """`₲ 0` con 0 filas es "no hay datos"; con 40 filas es "vendiste y
    gastaste lo mismo". El motor necesita distinguirlos."""
    cid = _empresa("Suma Honesta")
    con = _conector(cid, fuente="gastos", nombre="Gastos")
    contenido = ("fecha,monto,categoria,referencia\n"
                 "01/07/2026,500.000,Alquiler,G-1\n"
                 "02/07/2026,-500.000,Ajuste,G-2\n")
    _subir(cid, con, contenido)
    db = SessionLocal()
    try:
        total, filas = cfo_conectores.sumar(
            db, cid, Fuente.GASTOS, date(2026, 7, 1), date(2026, 7, 31))
        assert (total, filas) == (0, 2)
        total, filas = cfo_conectores.sumar(
            db, cid, Fuente.GASTOS, date(2025, 1, 1), date(2025, 1, 31))
        assert (total, filas) == (0, 0)
    finally:
        db.close()


# ─── Aislamiento y permisos ──────────────────────────────────────────────


def test_los_datos_de_una_empresa_no_entran_en_la_suma_de_otra():
    a = _empresa("Conector Cruce A")
    b = _empresa("Conector Cruce B")
    _subir(a, _conector(a), PLANILLA)
    db = SessionLocal()
    try:
        total_b, filas_b = cfo_conectores.sumar(
            db, b, Fuente.VENTAS, date(2026, 7, 1), date(2026, 7, 31))
        assert (total_b, filas_b) == (0, 0)
        assert Fuente.VENTAS not in cfo_conectores.fuentes_disponibles(db, b)
    finally:
        db.close()


def test_no_se_sube_una_planilla_al_conector_de_otra_empresa():
    a = _empresa("Conector Ajeno A")
    b = _empresa("Conector Ajeno B")
    con = _conector(a)
    assert _subir(b, con, PLANILLA).status_code == 404


def test_no_se_borra_el_conector_de_otra_empresa():
    a = _empresa("Conector Borrado A")
    b = _empresa("Conector Borrado B")
    con = _conector(a)
    assert client.delete(
        f"/api/companies/{b}/cfo/conectores/{con}").status_code == 404


def test_un_operador_no_toca_conectores():
    """Conectar una fuente decide qué números va a dar el sistema. Es
    administración."""
    cid = _empresa("Conector Permisos")
    _make_user("operador-conectores@test.py", cid, role="operator")
    op = _login("operador-conectores@test.py")
    assert op.get(f"/api/companies/{cid}/cfo/conectores").status_code == 403
    assert op.post(f"/api/companies/{cid}/cfo/conectores",
                   json={"fuente": "ventas", "tipo": "csv", "nombre": "X"}
                   ).status_code == 403


def test_sin_el_bloque_no_hay_conectores():
    c = _create_company(name="Comercio Sin Conectores")
    assert client.get(
        f"/api/companies/{c['id']}/cfo/conectores").status_code == 402


def test_borrar_el_conector_borra_sus_datos():
    cid = _empresa("Conector Borrado Cascada")
    con = _conector(cid)
    _subir(cid, con, PLANILLA)
    assert client.delete(
        f"/api/companies/{cid}/cfo/conectores/{con}").status_code == 204
    db = SessionLocal()
    try:
        assert db.query(FinanceRecord).filter(
            FinanceRecord.company_id == cid).count() == 0
        assert Fuente.VENTAS not in cfo_conectores.fuentes_disponibles(db, cid)
    finally:
        db.close()


def test_no_se_crea_un_conector_de_una_fuente_inventada():
    cid = _empresa("Conector Fuente Inventada")
    r = client.post(f"/api/companies/{cid}/cfo/conectores",
                    json={"fuente": "criptomonedas", "tipo": "csv", "nombre": "X"})
    assert r.status_code == 422
    assert r.json()["detail"]["codigo"] == "fuente_desconocida"


def test_no_se_crea_un_conector_de_la_fuente_interna():
    """Lo interno no se sube: ya está adentro. Permitirlo sería tener dos
    verdades sobre la misma cosa."""
    cid = _empresa("Conector Interna")
    r = client.post(f"/api/companies/{cid}/cfo/conectores",
                    json={"fuente": "interna", "tipo": "csv", "nombre": "X"})
    assert r.status_code == 422


def test_rest_y_postgres_todavia_no_estan_y_lo_dicen():
    """Devolver 501 con el motivo es mejor que aceptar y no sincronizar
    nunca."""
    cid = _empresa("Conector No Implementado")
    r = client.post(f"/api/companies/{cid}/cfo/conectores",
                    json={"fuente": "ventas", "tipo": "rest", "nombre": "API"})
    assert r.status_code == 501
    assert r.json()["detail"]["codigo"] == "tipo_no_implementado"


def test_dos_conectores_no_comparten_nombre_en_la_misma_empresa():
    """Con dos "Sucursal centro" no se sabe cuál quedó atrasado."""
    cid = _empresa("Conector Nombre Repetido")
    _conector(cid, nombre="Sucursal centro")
    r = client.post(f"/api/companies/{cid}/cfo/conectores",
                    json={"fuente": "ventas", "tipo": "csv",
                          "nombre": "Sucursal centro"})
    assert r.status_code == 409
    assert r.json()["detail"]["codigo"] == "nombre_repetido"


def test_un_archivo_gigante_se_rechaza_por_tamano():
    cid = _empresa("Planilla Gigante")
    con = _conector(cid)
    grande = b"fecha,monto\n" + b"01/07/2026,1000\n" * 400_000
    assert len(grande) > cfo_csv.MAXIMO_BYTES
    assert _subir(cid, con, grande).status_code == 422


# ─── De qué fuente salió el número ───────────────────────────────────────


def _aprobar(cid: int):
    r = client.post(f"/api/companies/{cid}/cfo/metricas/ventas_netas/aprobar",
                    json={"version": 1})
    assert r.status_code == 200, r.text


def _calcular(cid: int) -> dict:
    r = client.post(f"/api/companies/{cid}/cfo/metricas/ventas_netas/calcular",
                    json={"desde": "2026-07-01", "hasta": "2026-07-31"})
    assert r.status_code == 200, r.text
    return r.json()


def test_sin_conector_las_ventas_salen_de_las_atenciones_y_lo_dicen():
    """Un sanatorio factura por atención. Es una venta de verdad, pero no es
    facturación contable, y el número tiene que decirlo."""
    cid = _empresa("Fuente Atenciones")
    _aprobar(cid)
    r = _calcular(cid)
    assert r["calculable"] is True
    assert "atenciones" in " ".join(r["fuentes"]).lower()
    assert any("no es facturación contable" in a.lower() for a in r["advertencias"])


def test_con_conector_las_ventas_salen_del_sistema_de_facturacion():
    cid = _empresa("Fuente Facturación")
    con = _conector(cid)
    _subir(cid, con, PLANILLA)
    _aprobar(cid)
    r = _calcular(cid)
    assert r["valor"] == 3_800_000
    assert "facturación" in " ".join(r["fuentes"]).lower()
    assert r["detalle"]["registros"] == 2


def test_el_numero_no_mezcla_las_dos_fuentes():
    """Mitad del sistema de facturación y mitad de los turnos da un total que
    nadie puede explicar cuando el contador pregunte."""
    from datetime import datetime as _dt

    from app.models import Appointment, Doctor, Service

    cid = _empresa("Fuente Sin Mezcla")
    db = SessionLocal()
    try:
        s = Service(company_id=cid, name="Consulta", price_gs=999_000, active=True)
        d = Doctor(company_id=cid, name="Dr. Y")
        db.add_all([s, d])
        db.commit()
        db.add(Appointment(
            company_id=cid, doctor_id=d.id, patient_name="P",
            patient_phone="595981000000",
            scheduled_at=_dt(2026, 7, 10, 10, 0),
            service_id=s.id, status="attended",
        ))
        db.commit()
    finally:
        db.close()

    con = _conector(cid)
    _subir(cid, con, PLANILLA)
    _aprobar(cid)
    r = _calcular(cid)
    # Solo lo conectado: 3.800.000. Ni 4.799.000, ni 999.000.
    assert r["valor"] == 3_800_000, "sumó las dos fuentes"


def test_el_corte_del_numero_es_el_de_los_datos_no_la_hora_de_preguntar():
    """Un informe que dice "ahora" sobre datos de anteayer es peor que uno sin
    fecha."""
    cid = _empresa("Fuente Corte")
    con = _conector(cid)
    _subir(cid, con, PLANILLA)
    viejo = datetime.utcnow() - timedelta(days=9)
    db = SessionLocal()
    try:
        db.get(FinanceConnector, con).ultima_sync_at = viejo
        db.commit()
    finally:
        db.close()
    _aprobar(cid)
    r = _calcular(cid)
    assert r["corte"].startswith(viejo.strftime("%Y-%m-%d"))
    assert any("9 días" in a for a in r["advertencias"])


def test_una_metrica_sin_plan_b_sigue_pidiendo_su_fuente():
    """El plan B es de ventas, no de todo. Flujo de caja necesita bancos y sin
    eso no se calcula, se explique como se explique."""
    cid = _empresa("Fuente Sin Plan B")
    client.post(f"/api/companies/{cid}/cfo/metricas/flujo_de_caja/aprobar",
                json={"version": 1})
    r = client.post(f"/api/companies/{cid}/cfo/metricas/flujo_de_caja/calcular",
                    json={"desde": "2026-07-01", "hasta": "2026-07-31"})
    cuerpo = r.json()
    assert cuerpo["calculable"] is False
    # El motivo, se llame como se llame el campo: lo que no puede pasar es que
    # devuelva cero y se quede callado.
    assert "caja_y_bancos" in str(cuerpo), cuerpo
    assert "valor" not in cuerpo or cuerpo["valor"] is None
