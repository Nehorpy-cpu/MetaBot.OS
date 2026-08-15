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
