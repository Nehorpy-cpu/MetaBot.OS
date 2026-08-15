"""CFO — Fase 9: lo que el sistema atrapa, alguien lo tiene que leer.

Los guardias determinísticos ya existían y funcionaban: atajaban el PIN
inventado y la respuesta sin herramienta. Pero lo único que hacían con eso era
escribir un `logger.warning`. Un control que atrapa algo y no lo cuenta sirve
una sola vez: la vez que alguien mira los logs.

Estos hallazgos son de otra clase que los del Auditor. Los del Auditor los
produce un modelo mirando conversaciones —son sospechas—; estos los produce un
guardia que SABE que algo salió mal.

La segunda mitad del archivo prueba la otra cara de la fase: que el sistema
NO pueda aplicarse mejoras solo.
"""
import inspect
from datetime import datetime, timedelta

from tests.test_api import _create_company, client  # noqa: I001

from app import chat, config
from app.db import SessionLocal
from app.models import AuditFinding, Company, Conversation

FINANZAS = ["finance"]


def _escenario(nombre: str):
    cid = _create_company(name=nombre, packs=FINANZAS)["id"]
    db = SessionLocal()
    conv = Conversation(company_id=cid, contact_phone="595981777222",
                        channel="whatsapp")
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return cid, conv, db


def _hallazgos(db, cid: int) -> list[AuditFinding]:
    return (
        db.query(AuditFinding)
        .filter(AuditFinding.company_id == cid)
        .order_by(AuditFinding.id)
        .all()
    )


# ─── Lo que el guardia atrapa queda escrito ──────────────────────────────


def test_un_pin_inventado_deja_un_hallazgo_critico():
    """Pedir un PIN sin motivo le enseña al dueño a tipearlo cuando se lo
    piden por WhatsApp. Eso no es una advertencia: es entrenarlo para que
    caiga en una estafa."""
    cid, conv, db = _escenario("Hallazgo PIN")
    try:
        company = db.get(Company, cid)
        chat._anotar_hallazgo(db, company, conv, "critical", "pin_inventado",
                              "El modelo pidió un PIN que nadie exigió.")
        filas = _hallazgos(db, cid)
        assert len(filas) == 1
        assert filas[0].severity == "critical"
        assert filas[0].note.startswith("[pin_inventado]")
    finally:
        db.close()


def test_la_clave_va_al_principio_para_poder_agrupar():
    """Sin un identificador estable, agrupar hallazgos obliga a parsear
    castellano, y el castellano cambia."""
    cid, conv, db = _escenario("Hallazgo Clave")
    try:
        company = db.get(Company, cid)
        chat._anotar_hallazgo(db, company, conv, "warning", "sin_herramienta",
                              "Contestó sin llamar a la herramienta.")
        assert _hallazgos(db, cid)[0].note.startswith("[sin_herramienta] ")
    finally:
        db.close()


def test_el_mismo_problema_no_se_anota_cincuenta_veces():
    """Un guardia que llena la bandeja la vuelve ilegible, que es la forma más
    común de apagar un control sin apagarlo."""
    cid, conv, db = _escenario("Hallazgo Repetido")
    try:
        company = db.get(Company, cid)
        for _ in range(5):
            chat._anotar_hallazgo(db, company, conv, "critical", "pin_inventado",
                                  "El modelo pidió un PIN que nadie exigió.")
        assert len(_hallazgos(db, cid)) == 1
    finally:
        db.close()


def test_pero_dos_problemas_DISTINTOS_se_anotan_los_dos():
    cid, conv, db = _escenario("Hallazgo Dos Tipos")
    try:
        company = db.get(Company, cid)
        chat._anotar_hallazgo(db, company, conv, "critical", "pin_inventado", "a")
        chat._anotar_hallazgo(db, company, conv, "critical", "sin_herramienta", "b")
        assert len(_hallazgos(db, cid)) == 2
    finally:
        db.close()


def test_pasado_el_silencio_se_vuelve_a_anotar():
    """Que no se repita hoy no significa que se olvide para siempre: si sigue
    pasando la semana que viene, hay que volver a enterarse."""
    cid, conv, db = _escenario("Hallazgo Silencio")
    try:
        company = db.get(Company, cid)
        chat._anotar_hallazgo(db, company, conv, "critical", "pin_inventado", "a")
        viejo = _hallazgos(db, cid)[0]
        viejo.created_at = datetime.utcnow() - timedelta(
            hours=chat._HORAS_ENTRE_HALLAZGOS_IGUALES + 1)
        db.commit()
        chat._anotar_hallazgo(db, company, conv, "critical", "pin_inventado", "a")
        assert len(_hallazgos(db, cid)) == 2
    finally:
        db.close()


def test_sin_conversacion_no_explota():
    """El hallazgo cuelga de una conversación. Sin ella no hay dónde
    anotarlo, y eso no puede tumbar la respuesta al cliente."""
    cid, _, db = _escenario("Hallazgo Sin Conversación")
    try:
        company = db.get(Company, cid)
        chat._anotar_hallazgo(db, company, None, "critical", "pin_inventado", "a")
        assert _hallazgos(db, cid) == []
    finally:
        db.close()


def test_el_hallazgo_de_una_empresa_no_aparece_en_otra():
    a_cid, a_conv, db = _escenario("Hallazgo Cruce A")
    b_cid, _, _ = _escenario("Hallazgo Cruce B")
    try:
        chat._anotar_hallazgo(db, db.get(Company, a_cid), a_conv,
                              "critical", "pin_inventado", "a")
        assert len(_hallazgos(db, a_cid)) == 1
        assert _hallazgos(db, b_cid) == []
    finally:
        db.close()


def test_los_hallazgos_salen_por_la_api_que_el_panel_ya_usa():
    """No se inventó una bandeja nueva: van a la que el panel ya muestra."""
    cid, conv, db = _escenario("Hallazgo API")
    try:
        chat._anotar_hallazgo(db, db.get(Company, cid), conv, "critical",
                              "sin_herramienta", "Contestó sin la herramienta.")
    finally:
        db.close()
    filas = client.get(f"/api/companies/{cid}/audits").json()
    assert any(f["note"].startswith("[sin_herramienta]") for f in filas)
    assert any(f["severity"] == "critical" for f in filas)


# ─── La automejora no se aplica sola ─────────────────────────────────────


def test_las_tres_llaves_de_la_automejora_estan_en_false():
    assert config.CFO_ALLOW_AUTOMATIC_INSTALL is False
    assert config.CFO_ALLOW_AUTOMATIC_MERGE is False
    assert config.CFO_ALLOW_AUTOMATIC_DEPLOY is False
    assert config.CFO_ALLOW_AUTOMATIC_METRIC_CHANGE is False


def test_esas_llaves_no_se_pueden_encender_desde_el_entorno(monkeypatch):
    """Están asignadas a `False` literal, no leídas de `os.environ`. Un
    despliegue no puede ser la vía por la que el sistema empieza a
    desplegarse solo."""
    fuente = inspect.getsource(config)
    for llave in ("CFO_ALLOW_AUTOMATIC_INSTALL", "CFO_ALLOW_AUTOMATIC_MERGE",
                  "CFO_ALLOW_AUTOMATIC_DEPLOY",
                  "CFO_ALLOW_AUTOMATIC_METRIC_CHANGE"):
        linea = next(l for l in fuente.splitlines() if l.startswith(llave))
        assert linea.strip().endswith("= False"), linea
        assert "environ" not in linea, f"{llave} se lee del entorno"


def test_no_existe_ningun_camino_de_codigo_que_las_use_para_actuar():
    """Una llave en False que nadie mira es una llave decorativa; y una que SÍ
    se mira para decidir si desplegar es un camino que alguien puede activar.
    No hay ninguno de los dos: el código para instalar, fusionar o desplegar
    solo, sencillamente no está escrito."""
    import pathlib

    raiz = pathlib.Path(chat.__file__).parent
    peligrosas = ("subprocess", "os.system", "git push", "docker compose up")
    for archivo in raiz.glob("cfo*.py"):
        texto = archivo.read_text(encoding="utf-8")
        for p in peligrosas:
            assert p not in texto, f"{archivo.name} podría ejecutar: {p}"


# ─── El tope de mensajes por número ──────────────────────────────────────
#
# Existe por plata: desde que la tarea `finanzas` arranca con un modelo pago,
# cada mensaje entrante cuesta. Un número en bucle gasta la cuenta del dueño
# sin que nadie se entere hasta la factura.


def _mandar(cid: int, texto: str, telefono="595981777222"):
    import asyncio

    from app.chat import handle_incoming

    db = SessionLocal()
    try:
        return asyncio.run(handle_incoming(
            db, db.get(Company, cid), telefono, texto, channel="whatsapp"))
    finally:
        db.close()


def test_un_numero_en_bucle_deja_de_gastar_turnos(monkeypatch):
    llamadas = []

    async def _modelo(*a, **kw):
        llamadas.append(1)
        return {"role": "assistant", "content": "Listo.",
                "_modelo_usado": "prueba", "_proveedor_usado": "prueba"}

    monkeypatch.setattr("app.chat.chat_raw", _modelo)
    cid, _, db = _escenario("Tope Bucle")
    db.close()

    for i in range(chat.MENSAJES_POR_HORA + 3):
        r = _mandar(cid, f"hola {i}")
    assert r["status"] == "tope_de_mensajes"
    # El modelo dejó de correr: eso es lo que se estaba pagando.
    assert len(llamadas) <= chat.MENSAJES_POR_HORA + 1


def test_el_tope_esta_alto_para_no_dispararse_con_una_persona():
    """Un tope que se le dispara a un cliente legítimo cuesta más que la plata
    que ahorra."""
    assert chat.MENSAJES_POR_HORA >= 30


def test_el_mensaje_del_cliente_igual_queda_registrado(monkeypatch):
    """Que no se le conteste con un modelo no significa que no haya escrito:
    si el dueño después revisa la conversación, tiene que estar."""
    from app.models import Message

    async def _modelo(*a, **kw):
        return {"role": "assistant", "content": "Listo.",
                "_modelo_usado": "prueba", "_proveedor_usado": "prueba"}

    monkeypatch.setattr("app.chat.chat_raw", _modelo)
    cid, _, db = _escenario("Tope Registro")
    db.close()

    for i in range(chat.MENSAJES_POR_HORA + 2):
        _mandar(cid, f"mensaje {i}")

    db = SessionLocal()
    try:
        entrantes = (
            db.query(Message)
            .filter(Message.company_id == cid, Message.direction == "in")
            .count()
        )
        assert entrantes == chat.MENSAJES_POR_HORA + 2
    finally:
        db.close()


def test_el_tope_es_por_numero_y_no_por_empresa(monkeypatch):
    """Si fuera por empresa, un cliente pesado dejaría sin bot a todos los
    demás."""
    async def _modelo(*a, **kw):
        return {"role": "assistant", "content": "Listo.",
                "_modelo_usado": "prueba", "_proveedor_usado": "prueba"}

    monkeypatch.setattr("app.chat.chat_raw", _modelo)
    cid, _, db = _escenario("Tope Por Número")
    db.close()

    for i in range(chat.MENSAJES_POR_HORA + 2):
        _mandar(cid, f"m{i}", telefono="595981000001")
    otro = _mandar(cid, "hola", telefono="595981000002")
    assert otro["status"] != "tope_de_mensajes"
