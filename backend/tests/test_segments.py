"""Tests de la investigación de segmentos (scraping y LLM mockeados)."""
import json

from tests.test_api import _create_company, client

from app import swarm
from app import campaigns as campaign_engine

FAKE_SEGMENTS = {
    "products": ["Dior Sauvage", "Carolina Herrera Good Girl", "Lattafa"],
    "segments": [
        {"name": "Regaladores románticos", "perfil": "parejas jóvenes", "edad": "22-35",
         "intereses": "perfumes, regalos, aniversarios", "angulo": "el regalo perfecto",
         "formato_sugerido": "carousel"},
        {"name": "Coleccionistas árabes", "perfil": "fans de Lattafa", "edad": "18-30",
         "intereses": "perfumes árabes, TikTok", "angulo": "nicho premium accesible",
         "formato_sugerido": "video"},
        {"name": "Ejecutivos", "perfil": "profesionales", "edad": "30-50",
         "intereses": "marcas de lujo", "angulo": "presencia y estatus",
         "formato_sugerido": "single"},
    ],
    "insights": "Los perfumes árabes son la categoría de mayor crecimiento.",
}


def test_segment_research_creates_report(monkeypatch):
    company = _create_company("ecommerce", "Perfumería Test")
    cid = company["id"]

    async def fake_site(url, max_internal=3):
        assert "perfumeria-test" in url
        return "Catálogo: Dior Sauvage, Good Girl, Lattafa Asad. Envíos a todo Paraguay."

    async def fake_complete(messages, **kwargs):
        content = messages[-1]["content"]
        assert "Dior Sauvage" in content  # el prompt lleva el contenido scrapeado real
        assert "no inventes productos" in content
        return json.dumps(FAKE_SEGMENTS, ensure_ascii=False)

    monkeypatch.setattr(swarm, "_fetch_site", fake_site)
    monkeypatch.setattr(swarm, "complete", fake_complete)

    resp = client.post(
        f"/api/companies/{cid}/segments/research",
        json={"website": "https://perfumeria-test.com"},
    )
    assert resp.status_code == 200
    content = resp.json()["content"]
    assert "Regaladores románticos" in content
    assert "Dior Sauvage" in content
    assert "perfumes árabes" in content.lower() or "Lattafa" in content

    reports = client.get(f"/api/companies/{cid}/reports").json()
    assert any(r["kind"] == "segments" for r in reports)


def test_segment_research_without_sources_rejected(monkeypatch):
    company = _create_company("ecommerce", "Sin Fuentes")
    resp = client.post(f"/api/companies/{company['id']}/segments/research", json={})
    assert resp.status_code == 422
    assert "fuentes" in resp.json()["detail"].lower()


def test_campaign_uses_segments_research(monkeypatch, tmp_path):
    company = _create_company("ecommerce", "Perfumería Campaña")
    cid = company["id"]

    async def fake_site(url, max_internal=3):
        return "catálogo de perfumes"

    async def fake_complete_research(messages, **kwargs):
        return json.dumps(FAKE_SEGMENTS, ensure_ascii=False)

    monkeypatch.setattr(swarm, "_fetch_site", fake_site)
    monkeypatch.setattr(swarm, "complete", fake_complete_research)
    client.post(f"/api/companies/{cid}/segments/research", json={"website": "https://x.com"})

    seen = {}

    async def fake_complete_campaign(messages, **kwargs):
        content = messages[-1]["content"]
        if '"title"' in content:
            seen["ceo_prompt"] = content
            return '{"title": "Regalá amor", "angle": "regalo", "audience": "Regaladores románticos"}'
        if "tarjeta(s)" in content:
            return '[{"headline": "H1", "copy": "C1"}, {"headline": "H2", "copy": "C2"}]'
        if "prompt de imagen" in content:
            return '["p1", "p2"]'
        return '{"severity": "ok", "note": "bien"}'

    async def fake_generate(prompt, width, height):
        return b"img", "pollinations"

    monkeypatch.setattr(campaign_engine, "complete", fake_complete_campaign)
    monkeypatch.setattr(campaign_engine, "generate_image", fake_generate)
    monkeypatch.setattr(campaign_engine, "MEDIA_DIR", tmp_path)

    resp = client.post(
        f"/api/companies/{cid}/campaigns",
        json={"brief": "Campaña de perfumes para San Valentín", "format": "carousel", "n_cards": 2},
    )
    assert resp.status_code == 200
    # El CEO recibió los segmentos investigados en su prompt
    assert "Regaladores románticos" in seen["ceo_prompt"]
    assert "Segmentos investigados" in seen["ceo_prompt"]
