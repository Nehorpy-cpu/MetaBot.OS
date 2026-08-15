import json

import httpx
import pytest

from app import llm
from app.llm import LLMError, cadena_para, chat_raw, complete, model_for


@pytest.mark.anyio
async def test_no_providers_raises(monkeypatch):
    monkeypatch.setattr(llm, "available_providers", lambda: [])
    with pytest.raises(LLMError, match="Ningún proveedor"):
        await complete([{"role": "user", "content": "hola"}])


def test_provider_order_is_fallback_chain():
    from app.config import LLM_PROVIDERS

    names = [p["name"] for p in LLM_PROVIDERS]
    # OpenAI va ULTIMO a proposito: es el unico que cobra. Que este registrado
    # no significa que se use — solo la cadena de la tarea `finanzas` lo pide
    # primero, y ahi la razon esta medida y escrita en TASK_MODELS.
    assert names == ["nvidia", "groq", "openrouter", "gemini", "openai"]
    assert names[-1] == "openai", "el proveedor pago no puede quedar primero"


# --- El modelo tiene que ir al proveedor donde vive ---
#
# El fallo que estas pruebas cierran: chat_raw recorría los proveedores en
# orden fijo y, si el primero no conocía el modelo pedido, reintentaba con el
# modelo POR DEFECTO de ese mismo proveedor antes de pasar al siguiente.
# Medido en el VPS el 11-ago-2026: pedir "openai/gpt-oss-120b" (que solo
# existe en Groq, donde responde en 0,8s) tardaba 58,9s porque terminaba
# corriendo el modelo de NVIDIA, y en agent_runs quedaba anotado el modelo
# pedido. O sea: el Model Router era decorativo y las métricas mentían.

PROVEEDORES = [
    {"name": "nvidia", "base_url": "https://nvidia.test/v1", "api_key": "k1",
     "default_model": "meta/llama-3.3-70b-instruct"},
    {"name": "groq", "base_url": "https://groq.test/v1", "api_key": "k2",
     "default_model": "llama-3.3-70b-versatile"},
]


class _RespuestaFalsa:
    def __init__(self, status_code=200, contenido="ok"):
        self.status_code = status_code
        self._contenido = contenido

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error", request=None, response=None  # type: ignore[arg-type]
            )

    def json(self):
        return {"choices": [{"message": {"role": "assistant", "content": self._contenido}}]}


def _cliente_falso(monkeypatch, conocidos: dict[str, set[str]], registro: list):
    """Simula proveedores que solo aceptan los modelos que realmente tienen."""

    class ClienteFalso:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            host = url.split("//")[1].split(".")[0]
            modelo = json["model"]
            registro.append((host, modelo))
            if modelo not in conocidos.get(host, set()):
                return _RespuestaFalsa(404)
            return _RespuestaFalsa(200, f"soy {modelo}")

    monkeypatch.setattr(llm.httpx, "AsyncClient", ClienteFalso)


@pytest.mark.anyio
async def test_el_modelo_va_al_proveedor_donde_vive(monkeypatch):
    """Pedir un modelo de Groq no puede terminar corriendo el de NVIDIA."""
    monkeypatch.setattr(llm, "available_providers", lambda: PROVEEDORES)
    registro: list = []
    _cliente_falso(monkeypatch, {
        "nvidia": {"meta/llama-3.3-70b-instruct"},
        "groq": {"openai/gpt-oss-120b", "llama-3.3-70b-versatile"},
    }, registro)

    msg = await chat_raw([{"role": "user", "content": "hola"}], model="openai/gpt-oss-120b")

    assert msg["_proveedor_usado"] == "groq"
    assert msg["_modelo_usado"] == "openai/gpt-oss-120b"
    # Y ni siquiera se molestó a NVIDIA con un modelo que no tiene.
    assert registro == [("groq", "openai/gpt-oss-120b")]


@pytest.mark.anyio
async def test_nunca_sustituye_en_silencio_por_el_modelo_de_otro(monkeypatch):
    """Antes, si el modelo pedido fallaba, se usaba el default del proveedor
    equivocado y nadie se enteraba. Ahora se pasa al siguiente CANDIDATO."""
    monkeypatch.setattr(llm, "available_providers", lambda: PROVEEDORES)
    registro: list = []
    # Groq está caído para gpt-oss-120b (simula el 429 del free tier).
    _cliente_falso(monkeypatch, {
        "nvidia": {"meta/llama-3.3-70b-instruct"},
        "groq": {"llama-3.3-70b-versatile"},
    }, registro)

    msg = await chat_raw(
        [{"role": "user", "content": "hola"}],
        models=["openai/gpt-oss-120b", "meta/llama-3.3-70b-instruct"],
    )
    assert msg["_modelo_usado"] == "meta/llama-3.3-70b-instruct"
    assert msg["_proveedor_usado"] == "nvidia"
    # Jamás se pidió un modelo que nadie eligió.
    pedidos = {m for _, m in registro}
    assert pedidos <= {"openai/gpt-oss-120b", "meta/llama-3.3-70b-instruct"}


@pytest.mark.anyio
async def test_dice_quien_contesto_de_verdad(monkeypatch):
    """Sin esto, agent_runs anota el modelo PEDIDO: si hubo fallback, las
    mediciones de latencia describen un modelo que nunca corrió."""
    monkeypatch.setattr(llm, "available_providers", lambda: PROVEEDORES)
    _cliente_falso(monkeypatch, {"nvidia": set(), "groq": {"llama-3.3-70b-versatile"}}, [])
    msg = await chat_raw(
        [{"role": "user", "content": "hola"}],
        models=["openai/gpt-oss-120b", "llama-3.3-70b-versatile"],
    )
    assert msg["_modelo_usado"] == "llama-3.3-70b-versatile"


@pytest.mark.anyio
async def test_si_el_proveedor_no_tiene_key_ni_se_intenta(monkeypatch):
    """Un modelo de Groq con Groq sin configurar no debe caer en NVIDIA."""
    solo_nvidia = [PROVEEDORES[0]]
    monkeypatch.setattr(llm, "available_providers", lambda: solo_nvidia)
    registro: list = []
    _cliente_falso(monkeypatch, {"nvidia": {"meta/llama-3.3-70b-instruct"}}, registro)

    with pytest.raises(LLMError):
        await chat_raw([{"role": "user", "content": "hola"}], model="openai/gpt-oss-120b")
    assert registro == [], "se pidió a NVIDIA un modelo que es de Groq"


# --- La cadena por tarea ---


def test_el_cx_arranca_por_el_modelo_rapido():
    """Medido en producción con el prompt real y las 7 herramientas, turno
    completo: groq/gpt-oss-120b 0,8-2,2s contra 17,3-71,4s del nemotron."""
    assert model_for("cx") == "openai/gpt-oss-120b"
    assert llm.PROVEEDOR_DE_MODELO["openai/gpt-oss-120b"] == "groq"


def test_la_cadena_del_cx_tiene_respaldo_en_otro_proveedor():
    """El free tier de Groq da 429. Si no hay a dónde caer, el bot se queda
    mudo, que es peor que lento."""
    cadena = cadena_para("cx")
    proveedores = {llm.PROVEEDOR_DE_MODELO.get(m) for m in cadena}
    assert len(proveedores) >= 2, f"toda la cadena depende de un proveedor: {cadena}"


def test_el_modelo_del_tenant_manda_pero_no_deja_sin_respaldo():
    """Si una empresa fijó su modelo, va primero; pero si falla, se sigue con
    los de la tarea en vez de quedarse sin nada."""
    cadena = cadena_para("cx", "meta/llama-3.1-70b-instruct")
    assert cadena[0] == "meta/llama-3.1-70b-instruct"
    assert len(cadena) > 1


def test_quien_audita_no_es_quien_produce():
    """Regla del proyecto: el auditor no puede auto-aprobarse."""
    assert model_for("audit") != model_for("cx")
    assert model_for("supervision") != model_for("cx")


@pytest.mark.anyio
async def test_una_respuesta_vacia_pasa_al_siguiente_modelo(monkeypatch):
    """Un modelo de razonamiento puede gastar todo max_tokens pensando y
    devolver contenido vacío. Al llamador le llega como "no supo qué
    contestar" y el paciente recibe "¿me repetís eso último?"."""
    monkeypatch.setattr(llm, "available_providers", lambda: PROVEEDORES)

    class ClienteVacio:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            if json["model"] == "openai/gpt-oss-120b":
                return _RespuestaFalsa(200, "")  # razonó y no le quedó nada
            return _RespuestaFalsa(200, "acá está la respuesta")

    monkeypatch.setattr(llm.httpx, "AsyncClient", ClienteVacio)
    msg = await chat_raw(
        [{"role": "user", "content": "hola"}],
        models=["openai/gpt-oss-120b", "llama-3.3-70b-versatile"],
    )
    assert msg["content"] == "acá está la respuesta"
    assert msg["_modelo_usado"] == "llama-3.3-70b-versatile"


@pytest.mark.anyio
async def test_si_el_ultimo_tambien_viene_vacio_se_devuelve_igual(monkeypatch):
    """Sin candidatos que queden, devolver lo que hay es mejor que un error:
    el llamador ya tiene su propio texto de respaldo."""
    monkeypatch.setattr(llm, "available_providers", lambda: PROVEEDORES)

    class TodoVacio:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            return _RespuestaFalsa(200, "")

    monkeypatch.setattr(llm.httpx, "AsyncClient", TodoVacio)
    msg = await chat_raw([{"role": "user", "content": "hola"}],
                         models=["openai/gpt-oss-120b", "llama-3.3-70b-versatile"])
    assert msg["content"] == ""
