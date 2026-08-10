"""Clasificación de intención: determinística, auditable y sin latencia."""
import pytest

from app.intents import Intent, clasificar_por_señales


@pytest.mark.parametrize("texto,esperado", [
    # Urgencias: ganan sobre cualquier otra intención del mismo mensaje
    ("Me duele mucho el pecho, ¿tienen turno?", Intent.URGENCIA),
    ("No puedo respirar bien", Intent.URGENCIA),
    ("es una emergencia", Intent.URGENCIA),
    # Pedido explícito de humano
    ("quiero hablar con una persona", Intent.HUMANO),
    ("pasame con un asesor por favor", Intent.HUMANO),
    # Reclamos
    ("Me llegó roto el perfume, quiero mi plata", Intent.RECLAMO),
    ("pésima atención, nunca llegó mi pedido", Intent.RECLAMO),
    # Agenda
    ("Quiero sacar un turno para el lunes", Intent.AGENDAR),
    ("¿tienen disponibilidad esta semana?", Intent.AGENDAR),
    # Compra
    ("Lo quiero, ¿cómo pago?", Intent.COMPRAR),
    ("me lo llevo, hago transferencia", Intent.COMPRAR),
    # Consulta de producto
    ("¿Cuánto sale el Good Girl?", Intent.CONSULTA_PRODUCTO),
    ("busco algo dulce para mi señora", Intent.CONSULTA_PRODUCTO),
    ("¿qué me recomendás?", Intent.CONSULTA_PRODUCTO),
    # Información del negocio
    ("¿cuál es el horario de atención?", Intent.CONSULTA_INFO),
    ("¿hacen envíos a Encarnación?", Intent.CONSULTA_INFO),
    ("¿dónde están ubicados?", Intent.CONSULTA_INFO),
    # Saludo suelto
    ("Hola!", Intent.SALUDO),
    ("buenas tardes", Intent.SALUDO),
])
def test_clasifica_intenciones_tipicas(texto, esperado):
    resultado = clasificar_por_señales(texto)
    assert resultado.intent == esperado, f"'{texto}' → {resultado.intent} (esperaba {esperado})"


def test_urgencia_gana_sobre_agendar():
    """Un mensaje con síntoma grave no se trata como pedido de turno."""
    r = clasificar_por_señales("Tengo dolor de pecho, quiero un turno para mañana")
    assert r.intent == Intent.URGENCIA
    assert r.confianza >= 0.9  # ante la duda, escalar


def test_funciona_sin_tildes_y_en_mayusculas():
    assert clasificar_por_señales("CUANTO SALE?").intent == Intent.CONSULTA_PRODUCTO
    assert clasificar_por_señales("¿Cuánto Sale?").intent == Intent.CONSULTA_PRODUCTO


def test_mensaje_ambiguo_baja_la_confianza():
    """Si el mensaje dispara varias intenciones, el CEO no debe confiarse."""
    claro = clasificar_por_señales("quiero sacar un turno")
    ambiguo = clasificar_por_señales("hola, ¿cuánto sale y tienen turno?")
    assert ambiguo.confianza < claro.confianza


def test_sin_señales_no_inventa():
    r = clasificar_por_señales("mmm")
    assert r.intent == Intent.OTRO
    assert r.confianza == 0.0
    assert r.metodo == "por_defecto"


def test_la_decision_es_auditable():
    """Queda registrado QUÉ disparó la clasificación."""
    r = clasificar_por_señales("me llegó roto")
    assert r.señales, "debe registrar la señal que la disparó"
    assert r.metodo == "señales"


def test_clasificacion_es_instantanea():
    """Sin latencia: el cliente espera en WhatsApp."""
    import time

    t0 = time.perf_counter()
    for _ in range(1000):
        clasificar_por_señales("¿cuánto sale el perfume dulce para mujer?")
    transcurrido = time.perf_counter() - t0
    assert transcurrido < 0.5, f"1000 clasificaciones tardaron {transcurrido:.2f}s"


@pytest.mark.parametrize("texto", [
    "me duele mucho el pecho",
    "tengo un dolor en el pecho desde ayer",
    "me cuesta respirar",
    "me falta el aire",
    "creo que es un infarto",
    "perdí el conocimiento un rato",
])
def test_variantes_de_urgencia_medica(texto):
    """Regresión: 'me duele mucho el pecho' se clasificaba como pedido de
    turno. En urgencias, errar por defecto es grave."""
    assert clasificar_por_señales(texto).intent == Intent.URGENCIA
