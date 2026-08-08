"""Tests del Estudio Visual (LLM e imagen mockeados)."""
from tests.test_api import _create_company, client

from app.routers import creatives as creatives_router


def test_creative_flow_copy_prompt_image(monkeypatch, tmp_path):
    company = _create_company(name="Clínica Visual")
    cid = company["id"]

    calls = []

    async def fake_complete(messages, **kwargs):
        calls.append(messages[-1]["content"])
        if "copy publicitario" in messages[-1]["content"]:
            return "¡Sonreí sin miedo! Turnos de blanqueamiento esta semana. Escribinos 😁"
        return "professional dental clinic advertisement photo, bright smile"

    async def fake_generate(prompt, width, height):
        assert "dental" in prompt
        return b"\x89PNG-fake-bytes", "pollinations"

    monkeypatch.setattr(creatives_router, "complete", fake_complete)
    monkeypatch.setattr(creatives_router, "generate_image", fake_generate)
    monkeypatch.setattr(creatives_router, "MEDIA_DIR", tmp_path)

    resp = client.post(
        f"/api/companies/{cid}/creatives",
        json={"brief": "Promo de blanqueamiento dental esta semana"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "Sonreí" in data["copy_text"]
    assert data["provider"] == "pollinations"
    assert data["image_path"].startswith(f"/media/{cid}/")
    # El archivo físico existe
    saved = tmp_path / data["image_path"].removeprefix("/media/")
    assert saved.read_bytes() == b"\x89PNG-fake-bytes"
    # El brief llegó a ambos agentes (copy + prompt de imagen)
    assert len(calls) == 2
    assert all("blanqueamiento" in c for c in calls)

    listed = client.get(f"/api/companies/{cid}/creatives").json()
    assert len(listed) == 1

    # Borrar elimina registro y archivo
    del_resp = client.delete(f"/api/companies/{cid}/creatives/{data['id']}")
    assert del_resp.status_code == 204
    assert not saved.exists()
    assert client.get(f"/api/companies/{cid}/creatives").json() == []


def test_creative_brief_too_short():
    company = _create_company(name="Clínica Brief")
    resp = client.post(f"/api/companies/{company['id']}/creatives", json={"brief": "hola"})
    assert resp.status_code == 422


def test_creative_image_failure_returns_503(monkeypatch):
    company = _create_company(name="Clínica SinImagen")

    async def fake_complete(messages, **kwargs):
        return "texto"

    async def fake_generate(prompt, width, height):
        from app.imagegen import ImageGenError

        raise ImageGenError("todos caídos")

    monkeypatch.setattr(creatives_router, "complete", fake_complete)
    monkeypatch.setattr(creatives_router, "generate_image", fake_generate)
    resp = client.post(
        f"/api/companies/{company['id']}/creatives", json={"brief": "promo de prueba larga"}
    )
    assert resp.status_code == 503
