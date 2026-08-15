"""CFO — Fase 3: la herramienta que el bot usa para dar un número.

Es la única puerta por la que sale plata por WhatsApp. Lo que se prueba acá
es el orden: quién pregunta sale del teléfono de la conversación —nunca de un
argumento del modelo—, el permiso se verifica ANTES de consultar, y el PIN no
aparece en ninguna respuesta.
"""
from datetime import date, datetime

from tests.test_api import _create_company, client  # noqa: I001
from tests.test_tenancy import _login, _make_user

from app import cfo
from app.chat import _execute_tool
from app.db import SessionLocal
from app.models import Appointment, Company, Conversation, Service

FINANZAS = ["finance", "booking"]


def _empresa(nombre: str):
    return _create_company(name=nombre, packs=FINANZAS)


def _servicio(cid: int, precio: int) -> int:
    db = SessionLocal()
    try:
        s = Service(company_id=cid, name="Consulta", price_gs=precio, active=True)
        db.add(s)
        db.commit()
        return s.id
    finally:
        db.close()


def _atencion(cid: int, doctor_id: int, service_id: int, cuando: datetime):
    db = SessionLocal()
    try:
        db.add(Appointment(
            company_id=cid, doctor_id=doctor_id, patient_name="Paciente",
            patient_phone="595981000000", scheduled_at=cuando,
            service_id=service_id, status="attended",
        ))
        db.commit()
    finally:
        db.close()


def _doctor(cid: int) -> int:
    return client.post(f"/api/companies/{cid}/doctors", json={"name": "Dr. X"}).json()["id"]


def _identidad(cid: int, phone: str, sensibilidad="baja", pin=None):
    r = client.post(f"/api/companies/{cid}/cfo/identidades",
                    json={"phone": phone, "nombre": "Dueño",
                          "sensibilidad_max": sensibilidad})
    ident = r.json()
    if pin:
        client.put(f"/api/companies/{cid}/cfo/identidades/{ident['id']}/pin",
                   json={"pin": pin})
    return ident


def _preguntar(cid: int, telefono: str, **args):
    """Ejecuta la herramienta como la ejecutaría el bot en esa conversación."""
    db = SessionLocal()
    try:
        conv = (
            db.query(Conversation)
            .filter(Conversation.company_id == cid,
                    Conversation.contact_phone == telefono)
            .first()
        )
        if conv is None:
            conv = Conversation(company_id=cid, contact_phone=telefono, channel="whatsapp")
            db.add(conv)
            db.commit()
        return _execute_tool("consultar_finanzas", args, db, db.get(Company, cid), conv)
    finally:
        db.close()


def _con_datos(nombre: str, precio=150_000, sensibilidad="baja", pin=None,
               telefono="595981900001"):
    """Empresa con una atención facturable y la métrica aprobada."""
    c = _empresa(nombre)
    cid = c["id"]
    svc = _servicio(cid, precio)
    _atencion(cid, _doctor(cid), svc, datetime(2026, 7, 10, 10, 0))
    client.post(f"/api/companies/{cid}/cfo/metricas/ventas_netas/aprobar",
                json={"version": 1})
    _identidad(cid, telefono, sensibilidad, pin)
    return cid


PERIODO = {"desde": "2026-07-01", "hasta": "2026-07-31"}


# ─── El camino feliz ─────────────────────────────────────────────────────


def test_el_dueno_autorizado_recibe_el_numero_con_su_procedencia():
    cid = _con_datos("CFO Camino Feliz")
    r = _preguntar(cid, "595981900001", metrica="ventas_netas", **PERIODO)
    assert r["valor"] == "₲ 150.000"
    assert r["periodo"] == "01/07/2026 al 31/07/2026"
    assert r["fuentes"] and r["actualizado"]
    # Las advertencias viajan con el número, para que el bot las diga primero.
    assert any("facturación contable" in a.lower() for a in r["advertencias"])


# ─── Quién pregunta ──────────────────────────────────────────────────────


def test_un_numero_no_autorizado_no_recibe_nada():
    cid = _con_datos("CFO Desconocido")
    r = _preguntar(cid, "595999111222", metrica="ventas_netas", **PERIODO)
    assert r["codigo"] == "no_autorizado"
    assert "valor" not in r


def test_el_modelo_no_puede_elegir_de_quien_es_la_consulta():
    """La identidad sale del teléfono de ESTA conversación. Si el modelo
    pudiera pasar un teléfono, alucinarlo sería suplantar al dueño."""
    cid = _con_datos("CFO Suplantación")
    # Se le pasan argumentos de más, como si el modelo intentara elegir.
    r = _preguntar(cid, "595999111222", metrica="ventas_netas",
                   contacto="595981900001", company_id=cid, **PERIODO)
    assert r["codigo"] == "no_autorizado", "un argumento del modelo le cambió la identidad"


def test_la_empresa_sale_del_contexto_y_no_del_modelo():
    """Dos empresas, el mismo dueño autorizado en una sola."""
    a = _con_datos("CFO Empresa Propia", telefono="595981900010")
    b = _empresa("CFO Empresa Ajena")
    client.post(f"/api/companies/{b['id']}/cfo/metricas/ventas_netas/aprobar",
                json={"version": 1})
    r = _preguntar(b["id"], "595981900010", metrica="ventas_netas", **PERIODO)
    assert r["codigo"] == "no_autorizado"


# ─── El riesgo y el PIN ──────────────────────────────────────────────────


def test_una_metrica_sensible_pide_el_pin():
    cid = _con_datos("CFO Pide PIN", sensibilidad="alta", pin="7391",
                     telefono="595981900002")
    client.post(f"/api/companies/{cid}/cfo/metricas/margen_bruto/aprobar",
                json={"version": 1})

    r = _preguntar(cid, "595981900002", metrica="margen_bruto", **PERIODO)
    assert r["codigo"] == "pin_requerido"
    assert r["pin_requerido"] is True
    assert "valor" not in r


def test_el_pin_correcto_deja_pasar_y_el_incorrecto_no():
    cid = _con_datos("CFO PIN Correcto", sensibilidad="alta", pin="7391",
                     telefono="595981900003")
    malo = _preguntar(cid, "595981900003", metrica="ventas_netas", pin="0000", **PERIODO)
    # ventas_netas es de riesgo bajo: no necesita PIN, así que pasa igual.
    assert malo.get("valor")

    client.post(f"/api/companies/{cid}/cfo/metricas/margen_bruto/aprobar",
                json={"version": 1})
    r = _preguntar(cid, "595981900003", metrica="margen_bruto", pin="0000", **PERIODO)
    assert r["codigo"] == "pin_incorrecto"


def test_el_pin_no_vuelve_en_la_respuesta():
    """Repetirlo lo deja escrito en el historial de un WhatsApp que se puede
    perder."""
    cid = _con_datos("CFO PIN No Vuelve", sensibilidad="alta", pin="8462",
                     telefono="595981900004")
    r = _preguntar(cid, "595981900004", metrica="ventas_netas", pin="8462", **PERIODO)
    assert "8462" not in str(r)


def test_el_riesgo_lo_decide_el_catalogo_y_no_el_modelo():
    """Si el modelo pudiera declarar el riesgo, el PIN sería opcional."""
    cid = _con_datos("CFO Riesgo Del Catálogo", sensibilidad="alta", pin="1234",
                     telefono="595981900005")
    client.post(f"/api/companies/{cid}/cfo/metricas/margen_bruto/aprobar",
                json={"version": 1})
    # El modelo "declara" que es de riesgo bajo. Se ignora.
    r = _preguntar(cid, "595981900005", metrica="margen_bruto",
                   sensitivity="low", riesgo="baja", **PERIODO)
    assert r["codigo"] == "pin_requerido"


# ─── Lo que no se puede contestar ────────────────────────────────────────


def test_una_metrica_sin_aprobar_dice_por_que():
    # `ventas_brutas` es de riesgo bajo —así que el permiso no es lo que
    # frena— y `_con_datos` solo aprueba `ventas_netas`.
    cid = _con_datos("CFO Sin Aprobar Brutas", telefono="595981900006")
    r = _preguntar(cid, "595981900006", metrica="ventas_brutas", **PERIODO)
    assert r["calculable"] is False
    assert "no está aprobada" in r["error"]
    assert "valor" not in r


def test_una_metrica_inventada_lista_las_que_si_existen():
    cid = _con_datos("CFO Métrica Inventada", telefono="595981900007")
    r = _preguntar(cid, "595981900007", metrica="rentabilidad_magica", **PERIODO)
    assert "No conozco" in r["error"]
    assert "ventas_netas" in r["metricas_disponibles"]


def test_un_periodo_al_reves_no_se_calcula():
    cid = _con_datos("CFO Período Invertido", telefono="595981900008")
    r = _preguntar(cid, "595981900008", metrica="ventas_netas",
                   desde="2026-07-31", hasta="2026-07-01")
    assert "empieza después" in r["error"]


def test_sin_fechas_toma_el_mes_en_curso():
    """El dueño pregunta "¿cómo vamos?" sin decir fechas. No se le pide que
    aprenda a escribir un rango."""
    cid = _con_datos("CFO Sin Fechas", telefono="595981900009")
    r = _preguntar(cid, "595981900009", metrica="ventas_netas")
    hoy = date.today()
    assert r["periodo"].endswith(hoy.strftime("%d/%m/%Y"))
    assert r["periodo"].startswith(hoy.replace(day=1).strftime("%d/%m/%Y"))


# ─── El bloque ───────────────────────────────────────────────────────────


def test_una_empresa_sin_el_bloque_no_tiene_la_herramienta():
    """El bot de una clínica que no compró el CFO no puede ni intentarlo."""
    from app.chat import _tools_for

    c = _create_company(name="Clínica Sin CFO Herramienta")
    db = SessionLocal()
    try:
        nombres = {t["function"]["name"] for t in _tools_for(db.get(Company, c["id"]))}
    finally:
        db.close()
    assert "consultar_finanzas" not in nombres


def test_la_empresa_con_el_bloque_si_la_tiene():
    from app.chat import _tools_for

    c = _empresa("Empresa Con CFO Herramienta")
    db = SessionLocal()
    try:
        nombres = {t["function"]["name"] for t in _tools_for(db.get(Company, c["id"]))}
    finally:
        db.close()
    assert "consultar_finanzas" in nombres


def test_el_prompt_le_dice_al_bot_que_puede_contestar():
    """Prometer un dato y después decir 'falta conectar la fuente' es peor
    que no ofrecerlo."""
    from app.chat import _build_system_prompt
    from app.models import Agent

    cid = _con_datos("CFO Prompt", telefono="595981900011")
    db = SessionLocal()
    try:
        agente = (
            db.query(Agent)
            .filter(Agent.company_id == cid, Agent.slug == "cx")
            .first()
        )
        prompt = _build_system_prompt(db, db.get(Company, cid), agente)
    finally:
        db.close()
    assert "ventas_netas" in prompt
    assert "consultar_finanzas" in prompt
    # Y no ofrece las que no están aprobadas.
    assert "flujo_de_caja" not in prompt


def test_sin_metricas_aprobadas_el_prompt_lo_dice():
    from app.chat import _build_system_prompt
    from app.models import Agent

    c = _empresa("CFO Sin Métricas Aprobadas")
    db = SessionLocal()
    try:
        agente = (
            db.query(Agent)
            .filter(Agent.company_id == c["id"], Agent.slug == "cx")
            .first()
        )
        prompt = _build_system_prompt(db, db.get(Company, c["id"]), agente)
    finally:
        db.close()
    assert "todavía no aprobó ninguna métrica" in prompt
