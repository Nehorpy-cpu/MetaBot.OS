"""Qué modelos puede tocar el sistema, y cuáles no.

La clave de OpenAI habilita 124 modelos: `sora-2`, `gpt-image-2`, los `-pro`,
`gpt-5.6-sol`, `gpt-5.6-luna`. Todos se cobran y ninguno hace falta para
contestar por WhatsApp. El sistema tiene autorizados tres —texto, voz a
texto, texto a voz— y esto prueba que los demás no salgan por ningún camino.

Que un modelo esté disponible no es motivo para permitirlo: la cuenta la paga
el dueño del negocio.
"""
import pytest

from app import config, llm


def test_solo_hay_tres_modelos_permitidos():
    assert config.OPENAI_MODELOS_PERMITIDOS == frozenset({
        "gpt-4o-mini", "gpt-4o-mini-transcribe", "gpt-4o-mini-tts",
    })


def test_no_hay_modelos_de_imagen_ni_video_permitidos():
    """Ni por accidente ni por un renombre futuro."""
    prohibidos = ("sora", "image", "dall-e", "video")
    for permitido in config.OPENAI_MODELOS_PERMITIDOS:
        assert not any(p in permitido for p in prohibidos), permitido


def test_ni_sol_ni_luna_ni_terra_ni_pro():
    """Los tres que la especificación original traía por defecto, más los
    grandes. El CFO narra un número que ya calculó el servidor: no necesita
    un modelo de frontera para eso."""
    for caro in ("gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.6-terra",
                 "gpt-5.5-pro", "gpt-5.4-pro", "o1-pro"):
        assert caro not in config.OPENAI_MODELOS_PERMITIDOS


def test_los_modelos_configurados_estan_todos_permitidos():
    for modelo in (config.OPENAI_TEXT_MODEL, config.OPENAI_TRANSCRIPTION_MODEL,
                   config.OPENAI_TTS_MODEL):
        assert modelo in config.OPENAI_MODELOS_PERMITIDOS


def test_el_entorno_no_puede_habilitar_un_modelo_de_afuera(monkeypatch):
    """Una variable de entorno la cambia alguien a las once de la noche y
    nadie se entera. La lista blanca vive en código por eso."""
    monkeypatch.setenv("OPENAI_TEXT_MODEL", "gpt-5.6-sol")
    assert config._modelo("OPENAI_TEXT_MODEL", "gpt-4o-mini") == "gpt-4o-mini"

    monkeypatch.setenv("OPENAI_TTS_MODEL", "sora-2")
    assert config._modelo("OPENAI_TTS_MODEL", "gpt-4o-mini-tts") == "gpt-4o-mini-tts"


def test_el_entorno_si_puede_elegir_adentro_de_la_lista(monkeypatch):
    monkeypatch.setenv("OPENAI_TEXT_MODEL", "gpt-4o-mini")
    assert config._modelo("OPENAI_TEXT_MODEL", "gpt-4o-mini") == "gpt-4o-mini"


@pytest.mark.anyio
async def test_pedirle_a_openai_un_modelo_prohibido_no_sale(monkeypatch, anyio_backend):
    """El cerrojo va en `chat_raw`, que es por donde pasa TODA llamada. Si
    estuviera repartido por el código, un camino nuevo se olvidaría."""
    monkeypatch.setattr(llm, "available_providers", lambda: [
        {"name": "openai", "base_url": "https://api.openai.com/v1",
         "api_key": "no-se-usa", "default_model": "gpt-4o-mini"},
    ])
    monkeypatch.setitem(llm.PROVEEDOR_DE_MODELO, "sora-2", "openai")

    with pytest.raises(llm.LLMError) as exc:
        await llm.chat_raw([{"role": "user", "content": "hola"}], model="sora-2")
    assert "no están autorizados" in str(exc.value)


@pytest.mark.anyio
async def test_el_bloqueo_no_alcanza_a_los_otros_proveedores(monkeypatch, anyio_backend):
    """La lista blanca es de OpenAI. Los modelos de Groq y NVIDIA se eligen
    por otro criterio (cupo, latencia) y no tienen por qué pasar por acá."""
    llamadas = []

    class _RespuestaFalsa:
        status_code = 200

        @staticmethod
        def json():
            return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

        @staticmethod
        def raise_for_status():
            return None

    class _ClienteFalso:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kwargs):
            llamadas.append(kwargs.get("json", {}).get("model"))
            return _RespuestaFalsa()

    monkeypatch.setattr(llm, "available_providers", lambda: [
        {"name": "groq", "base_url": "https://api.groq.com/openai/v1",
         "api_key": "no-se-usa", "default_model": "llama-3.3-70b-versatile"},
    ])
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kw: _ClienteFalso())

    await llm.chat_raw([{"role": "user", "content": "hola"}],
                       model="llama-3.3-70b-versatile")
    assert llamadas == ["llama-3.3-70b-versatile"]


def test_finanzas_arranca_con_el_modelo_pago_y_tiene_respaldo_gratis():
    """Es la única tarea que arranca pagando, y por un motivo medido: sin la
    llamada a la herramienta no corre la verificación de permiso."""
    cadena = llm.cadena_para("finanzas")
    assert cadena[0] == config.OPENAI_TEXT_MODEL
    assert len(cadena) > 1, "sin respaldo, una clave vencida deja al CFO mudo"
    assert all(m not in config.OPENAI_MODELOS_PERMITIDOS for m in cadena[1:])


def test_la_conversacion_comun_sigue_siendo_gratis():
    """Poner OpenAI en 'cx' le pondría un costo por mensaje a todos los
    clientes del sistema, no solo a los del CFO."""
    for modelo in llm.cadena_para("cx"):
        assert modelo not in config.OPENAI_MODELOS_PERMITIDOS
