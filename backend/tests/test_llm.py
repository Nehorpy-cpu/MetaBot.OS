import pytest

from app import llm
from app.llm import LLMError, complete


@pytest.mark.anyio
async def test_no_providers_raises(monkeypatch):
    monkeypatch.setattr(llm, "available_providers", lambda: [])
    with pytest.raises(LLMError, match="Ningún proveedor"):
        await complete([{"role": "user", "content": "hola"}])


def test_provider_order_is_fallback_chain():
    from app.config import LLM_PROVIDERS

    names = [p["name"] for p in LLM_PROVIDERS]
    assert names == ["nvidia", "groq", "openrouter"]
