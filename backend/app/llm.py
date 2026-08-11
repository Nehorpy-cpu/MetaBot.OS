"""Capa de abstracción LLM con fallback entre proveedores OpenAI-compatibles.

Se usa el primer proveedor con API key configurada; si falla (error de red,
rate limit, 5xx), se intenta el siguiente. Así el sistema no queda atado a
NVIDIA NIM: sirve Groq u OpenRouter con el mismo código.
"""
import httpx

from .config import LLM_PROVIDERS


class LLMError(Exception):
    pass


# --- Model Router: se elige modelo por TAREA, no por marca ---
#
# Regla explícita del proyecto: quien audita no debe ser el mismo modelo que
# produjo la salida. Un proveedor entra o sale según resultados, cambiando
# solo esta tabla.
TASK_MODELS: dict[str, str] = {
    # Conversación con cliente: baja latencia + buen tool-calling
    "cx": "nvidia/llama-3.3-nemotron-super-49b-v1.5",
    # Razonamiento/planificación
    "reasoning": "nvidia/llama-3.3-nemotron-super-49b-v1.5",
    # Auditoría: modelo DISTINTO al que produce, para no auto-aprobarse
    "audit": "meta/llama-3.3-70b-instruct",
    # Supervisión de turnos: también distinto al del CX, pero además rápido.
    # Medido en el VPS con el mismo prompt y 900 tokens: llama-3.1-70b tarda
    # ~25s contra ~100s del modelo de auditoría. Corre fuera de la espera del
    # cliente, pero comparte el worker de trabajos con los recordatorios.
    "supervision": "meta/llama-3.1-70b-instruct",
    # Redacción creativa
    "creative": "mistralai/mistral-large-2-instruct",
    # Extracción estructurada de datos (catálogo, perfiles)
    "extraction": "meta/llama-3.3-70b-instruct",
}


def model_for(task: str, override: str | None = None) -> str | None:
    """Modelo a usar para una tarea. `override` (config del agente) gana."""
    return override or TASK_MODELS.get(task)


def available_providers() -> list[dict]:
    return [p for p in LLM_PROVIDERS if p["api_key"]]


async def chat_raw(
    messages: list[dict],
    *,
    tools: list[dict] | None = None,
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 1024,
    # 120s: los modelos serverless de NIM pueden tardar ~1 min en arrancar
    # en frío; mejor esperar que caer en fallback innecesario.
    timeout: float = 120.0,
    json_mode: bool = False,
) -> dict:
    """Devuelve el mensaje completo del asistente (puede incluir tool_calls)
    del primer proveedor que funcione."""
    providers = available_providers()
    if not providers:
        raise LLMError(
            "Ningún proveedor LLM configurado. Definí NVIDIA_API_KEY, "
            "GROQ_API_KEY u OPENROUTER_API_KEY en .env"
        )
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        for p in providers:
            payload: dict = {
                "model": model or p["default_model"],
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if tools:
                payload["tools"] = tools
            if json_mode:
                # Salida JSON forzada (OpenAI-compatible). Si el proveedor no
                # lo soporta, se reintenta sin el parámetro más abajo.
                payload["response_format"] = {"type": "json_object"}
            try:
                resp = await client.post(
                    f"{p['base_url']}/chat/completions",
                    headers={"Authorization": f"Bearer {p['api_key']}"},
                    json=payload,
                )
                if json_mode and resp.status_code in (400, 422):
                    payload.pop("response_format", None)
                    resp = await client.post(
                        f"{p['base_url']}/chat/completions",
                        headers={"Authorization": f"Bearer {p['api_key']}"},
                        json=payload,
                    )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]
            except (httpx.HTTPError, KeyError, IndexError) as exc:
                # type(exc) SIEMPRE visible: str(ReadTimeout) es vacío y
                # ocultaba la causa real en producción.
                errors.append(f"{p['name']}: {type(exc).__name__}: {exc}")
                # Si el modelo pedido no existe en este proveedor, probar con
                # su modelo por defecto antes de pasar al siguiente.
                if model and model != p["default_model"]:
                    try:
                        payload["model"] = p["default_model"]
                        resp = await client.post(
                            f"{p['base_url']}/chat/completions",
                            headers={"Authorization": f"Bearer {p['api_key']}"},
                            json=payload,
                        )
                        resp.raise_for_status()
                        return resp.json()["choices"][0]["message"]
                    except (httpx.HTTPError, KeyError, IndexError) as exc2:
                        errors.append(f"{p['name']} (default): {type(exc2).__name__}: {exc2}")
    raise LLMError("Todos los proveedores fallaron: " + "; ".join(errors))


async def complete(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 1024,
    timeout: float = 60.0,
    json_mode: bool = False,
) -> str:
    """Devuelve solo el texto de respuesta."""
    message = await chat_raw(
        messages, model=model, temperature=temperature, max_tokens=max_tokens,
        timeout=timeout, json_mode=json_mode,
    )
    return message.get("content") or ""
