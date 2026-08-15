"""El bot no pide un PIN porque se le ocurra.

Visto en producción probando la Fase 6: el dueño preguntó "cuánto vendí este
mes", la métrica es de riesgo bajo, la herramienta devolvió el número sin
pedir nada — y el modelo igual contestó "necesito el PIN de acceso, ¿me lo
pasás?".

No es una respuesta de más: es entrenar al dueño a tipear su PIN cuando
alguien se lo pide por WhatsApp. Ese es el hábito que necesita un estafador.
"""
from tests.test_api import _create_company, client  # noqa: I001

from app import cfo
from app.chat import _sanear_pin_inventado
from app.db import SessionLocal
from app.models import Company, Conversation

FINANZAS = ["finance"]
TELEFONO = "595981777222"


def _escenario(nombre: str):
    cid = _create_company(name=nombre, packs=FINANZAS)["id"]
    client.post(f"/api/companies/{cid}/cfo/identidades",
                json={"phone": TELEFONO, "nombre": "Dueño",
                      "sensibilidad_max": "alta"})
    db = SessionLocal()
    conv = Conversation(company_id=cid, contact_phone=TELEFONO, channel="whatsapp")
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return cid, conv, db


def test_un_pedido_de_pin_que_nadie_exigio_no_sale():
    cid, conv, db = _escenario("PIN Inventado")
    try:
        company = db.get(Company, cid)
        salida, reemplazada = _sanear_pin_inventado(
            db, company, conv,
            "¡Hola! Para consultarte las ventas necesito el PIN de acceso. "
            "¿Me lo podés pasar?",
        )
        assert reemplazada is True
        assert "pin" not in salida.lower()
    finally:
        db.close()


def test_el_pedido_legitimo_sigue_saliendo():
    """Cuando la autorización SÍ lo exigió, queda una consulta pendiente y el
    pedido es real."""
    cid, conv, db = _escenario("PIN Legítimo")
    try:
        company = db.get(Company, cid)
        cfo.pedir_pin(db, cid, TELEFONO, "flujo_de_caja", None, None)
        texto = "Para eso necesito tu PIN. ¿Me lo pasás?"
        salida, reemplazada = _sanear_pin_inventado(db, company, conv, texto)
        assert reemplazada is False
        assert salida == texto
    finally:
        db.close()


def test_una_respuesta_normal_no_se_toca():
    cid, conv, db = _escenario("PIN Sin Ruido")
    try:
        company = db.get(Company, cid)
        texto = "Vendiste ₲ 8.550.000 entre el 1 y el 15 de agosto."
        salida, reemplazada = _sanear_pin_inventado(db, company, conv, texto)
        assert reemplazada is False
        assert salida == texto
    finally:
        db.close()


def test_tambien_atrapa_clave_de_acceso():
    """Decirlo con otras palabras es el mismo pedido."""
    cid, conv, db = _escenario("PIN Otro Nombre")
    try:
        company = db.get(Company, cid)
        salida, reemplazada = _sanear_pin_inventado(
            db, company, conv,
            "Necesito tu clave de acceso para darte ese dato.",
        )
        assert reemplazada is True
        assert "clave de acceso" not in salida.lower()
    finally:
        db.close()


def test_la_palabra_pin_adentro_de_otra_no_dispara():
    """'Pintura' no es un pedido de PIN. Un guardia que salta de más deja de
    ser confiable y se termina apagando."""
    cid, conv, db = _escenario("PIN Falso Positivo")
    try:
        company = db.get(Company, cid)
        texto = "El gasto más grande del mes fue pintura del local."
        salida, reemplazada = _sanear_pin_inventado(db, company, conv, texto)
        assert reemplazada is False
        assert salida == texto
    finally:
        db.close()


# ─── Sin herramienta no hay número ───────────────────────────────────────


def test_una_pregunta_de_plata_sin_llamar_a_la_herramienta_no_se_contesta():
    """Sin llamada tampoco corre la verificación de permiso: no se sabe si
    esa persona podía preguntar."""
    from app.chat import _sin_herramienta_no_hay_numero

    cid, _, db = _escenario("Sin Herramienta")
    try:
        company = db.get(Company, cid)
        salida, reemplazada = _sin_herramienta_no_hay_numero(
            company, "cuanto vendi este mes?", [],
            "Este mes vendiste alrededor de 12 millones.",
        )
        assert reemplazada is True
        assert "12 millones" not in salida
    finally:
        db.close()


def test_si_la_herramienta_se_llamo_la_respuesta_pasa():
    from app.chat import _sin_herramienta_no_hay_numero

    cid, _, db = _escenario("Con Herramienta")
    try:
        company = db.get(Company, cid)
        texto = "Vendiste ₲ 8.550.000 entre el 1 y el 15 de agosto."
        salida, reemplazada = _sin_herramienta_no_hay_numero(
            company, "cuanto vendi este mes?", ["consultar_finanzas"], texto)
        assert reemplazada is False
        assert salida == texto
    finally:
        db.close()


def test_una_pregunta_que_no_es_de_plata_pasa():
    """Un guardia que salta de más se termina apagando, y entonces no protege
    nada."""
    from app.chat import _sin_herramienta_no_hay_numero

    cid, _, db = _escenario("Pregunta Común")
    try:
        company = db.get(Company, cid)
        for pregunta in ("hola, están abiertos?", "cuánto sale una consulta?",
                         "qué precio tiene el producto?"):
            texto = "Sí, claro."
            salida, reemplazada = _sin_herramienta_no_hay_numero(
                company, pregunta, [], texto)
            assert reemplazada is False, f"saltó de más con: {pregunta}"
            assert salida == texto
    finally:
        db.close()


def test_sin_el_bloque_de_finanzas_el_guardia_no_se_mete():
    """Una empresa que no compró finanzas no tiene de qué protegerse acá, y
    el guardia no puede romperle una conversación normal."""
    from app.chat import _sin_herramienta_no_hay_numero

    c = _create_company(name="Comercio Sin Finanzas")
    db = SessionLocal()
    try:
        company = db.get(Company, c["id"])
        texto = "Las ventas de la promo terminan el viernes."
        salida, reemplazada = _sin_herramienta_no_hay_numero(
            company, "hasta cuándo dura la promo de ventas?", [], texto)
        assert reemplazada is False
        assert salida == texto
    finally:
        db.close()
