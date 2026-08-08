"""Tests del generador de campañas (LLM e imágenes mockeados)."""
import json

from tests.test_api import _create_company, client

from app import campaigns as campaign_engine


def _mock_pipeline(monkeypatch, tmp_path, audit='{"severity": "ok", "note": "Cumple políticas."}'):
    calls = []

    async def fake_complete(messages, **kwargs):
        content = messages[-1]["content"]
        calls.append(content)
        if '"title"' in content:
            return '{"title": "Sonrisa Total", "angle": "confianza", "audience": "jóvenes de Asunción"}'
        if "tarjeta(s) de anuncio" in content:
            return json.dumps([
                {"headline": "Tu sonrisa primero", "copy": "Vení y brillá con nosotros."},
                {"headline": "20% off esta semana", "copy": "Agendá ya tu blanqueamiento."},
            ], ensure_ascii=False)
        if "guion de video" in content:
            return json.dumps([
                {"headline": "ESCENA 1 — 3s", "copy": "¿Escondés tu sonrisa?", "visual": "primer plano"},
                {"headline": "ESCENA 2 — 5s", "copy": "Blanqueamiento seguro", "visual": "consultorio"},
                {"headline": "ESCENA 3 — 3s", "copy": "Agendá hoy", "visual": "logo y CTA"},
            ], ensure_ascii=False)
        if "prompt de imagen EN INGLÉS" in content:
            return '["bright smile professional photo", "dental clinic modern interior"]'
        return audit

    async def fake_generate(prompt, width, height):
        return b"fake-image", "pollinations"

    monkeypatch.setattr(campaign_engine, "complete", fake_complete)
    monkeypatch.setattr(campaign_engine, "generate_image", fake_generate)
    monkeypatch.setattr(campaign_engine, "MEDIA_DIR", tmp_path)
    return calls


def test_carousel_full_pipeline(monkeypatch, tmp_path):
    company = _create_company(name="Clínica Campaña")
    cid = company["id"]
    calls = _mock_pipeline(monkeypatch, tmp_path)

    resp = client.post(
        f"/api/companies/{cid}/campaigns",
        json={"brief": "Promo blanqueamiento 20% esta semana", "format": "carousel", "n_cards": 2},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Sonrisa Total"
    assert data["strategy"]["angle"] == "confianza"
    assert len(data["cards"]) == 2
    assert data["cards"][0]["headline"] == "Tu sonrisa primero"
    assert data["cards"][0]["image_path"].startswith(f"/media/{cid}/")
    assert data["audit_severity"] == "ok"
    # Los 4 agentes participaron: CEO, Creativo, Visual, Auditor
    assert len(calls) == 4

    listed = client.get(f"/api/companies/{cid}/campaigns").json()
    assert len(listed) == 1


def test_video_script_has_no_images(monkeypatch, tmp_path):
    company = _create_company(name="Clínica Video")
    cid = company["id"]
    _mock_pipeline(monkeypatch, tmp_path)

    resp = client.post(
        f"/api/companies/{cid}/campaigns",
        json={"brief": "Reel de blanqueamiento dental", "format": "video_script", "n_cards": 3},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["cards"]) == 3
    assert data["cards"][0]["visual"] == "primer plano"
    assert all(not c["image_path"] for c in data["cards"])


def test_campaign_critical_audit_is_reported(monkeypatch, tmp_path):
    company = _create_company(name="Clínica Riesgo")
    cid = company["id"]
    _mock_pipeline(
        monkeypatch, tmp_path,
        audit='{"severity": "critical", "note": "Promete resultados médicos garantizados."}',
    )
    resp = client.post(
        f"/api/companies/{cid}/campaigns",
        json={"brief": "Cura garantizada de caries en un día", "format": "carousel", "n_cards": 2},
    )
    data = resp.json()
    assert data["audit_severity"] == "critical"
    assert "garantizados" in data["audit_note"]


def test_campaign_invalid_format_rejected():
    company = _create_company(name="Clínica Formato")
    resp = client.post(
        f"/api/companies/{company['id']}/campaigns",
        json={"brief": "brief válido de campaña", "format": "billboard"},
    )
    assert resp.status_code == 422


def test_campaign_image_failure_does_not_abort(monkeypatch, tmp_path):
    """Si el generador de imágenes cae, la campaña se guarda igual (imagen
    regenerable después)."""
    company = _create_company(name="Clínica SinImg")
    cid = company["id"]
    _mock_pipeline(monkeypatch, tmp_path)

    async def broken_generate(prompt, width, height):
        from app.imagegen import ImageGenError

        raise ImageGenError("caído")

    monkeypatch.setattr(campaign_engine, "generate_image", broken_generate)
    resp = client.post(
        f"/api/companies/{cid}/campaigns",
        json={"brief": "Promo válida de prueba", "format": "carousel", "n_cards": 2},
    )
    assert resp.status_code == 200
    assert all(not c["image_path"] for c in resp.json()["cards"])
