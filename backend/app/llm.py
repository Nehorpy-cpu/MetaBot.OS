"""Capa de abstracción LLM con fallback entre proveedores OpenAI-compatibles.

Se usa el primer proveedor con API key configurada; si falla (error de red,
rate limit, 5xx), se intenta el siguiente. Así el sistema no queda atado a
NVIDIA NIM: sirve Groq u OpenRouter con el mismo código.
"""
import httpx

from .config import LLM_PROVIDERS


class LLMError(Exception):
    pass


def available_providers() -> list[dict]:
    return [p for p in LLM_PROVIDERS if p["api_key"]]


async def complete(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 1024,
    timeout: float = 60.0,
) -> str:
    """Devuelve el texto de respuesta del primer proveedor que funcione."""
    providers = available_providers()
    if not providers:
        raise LLMError(
            "Ningún proveedor LLM configurado. Definí NVIDIA_API_KEY, "
            "GROQ_API_KEY u OPENROUTER_API_KEY en .env"
        )
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        for p in providers:
            try:
                resp = await client.post(
                    f"{p['base_url']}/chat/completions",
                    headers={"Authorization": f"Bearer {p['api_key']}"},
                    json={
                        "model": model or p["default_model"],
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            except (httpx.HTTPError, KeyError, IndexError) as exc:
                errors.append(f"{p['name']}: {exc}")
    raise LLMError("Todos los proveedores fallaron: " + "; ".join(errors))
