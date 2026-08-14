"""Tests del catálogo real: importación, fotos reales en chat y campañas,
y sugerencias de servicios por rubro."""
import json

from tests.test_api import _create_company, client

from app import catalog as catalog_engine
from app import chat as chat_engine
from app import campaigns as campaign_engine

ARFAGI_HTML = """<html><script>
const items = [
 {id:'s1',name:'Miss Dior',brand:'Dior',category:'Perfume',gender:'femenino',salePrice:685000,inStock:true,image:'img/missdior.jpg'},
 {id:'s2',name:'Good Girl',brand:'Carolina Herrera',category:'Perfume',gender:'femenino',salePrice:720000,inStock:true,image:'img/goodgirl.jpg'},
 {id:'s3',name:'Asad',brand:'Lattafa',category:'Perfume árabe',gender:'masculino',salePrice:310000,inStock:false,image:''},
];</script></html>"""


def test_parse_js_products():
    items = catalog_engine._parse_js_products(ARFAGI_HTML)
    assert len(items) == 3
    assert items[0] == {
        "name": "Miss Dior", "brand": "Dior", "category": "Perfume",
        "gender": "femenino", "price_gs": 685000, "in_stock": True, "image": "img/missdior.jpg",
    }
    assert items[2]["in_stock"] is False


def _import_catalog(monkeypatch, cid):
    async def fake_get(self, url, **kwargs):
        class R:
            status_code = 200
            headers = {"content-type": "image/jpeg"}
            content = b"real-photo-bytes"
            text = ARFAGI_HTML

            def raise_for_status(self):
                pass

        return R()

    import httpx

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(catalog_engine, "MEDIA_DIR", catalog_engine.MEDIA_DIR)  # real media dir ok en tests
    return client.post(f"/api/companies/{cid}/catalog/import", json={"website": "https://arfagi.com"})


def test_import_catalog_downloads_real_images(monkeypatch, tmp_path):
    company = _create_company("ecommerce", "Perfumería Import")
    cid = company["id"]
    monkeypatch.setattr(catalog_engine, "MEDIA_DIR", tmp_path)
    resp = _import_catalog(monkeypatch, cid)
    assert resp.status_code == 200
    data = resp.json()
    assert data["method"] == "estructurado"
    assert data["imported"] == 3
    assert data["with_image"] == 2  # Asad no tiene imagen y NO se genera

    products = client.get(f"/api/companies/{cid}/products").json()
    assert len(products) == 3
    miss = next(p for p in products if p["name"] == "Miss Dior")
    assert miss["image_path"].startswith(f"/media/{cid}/catalog/")
    asad = next(p for p in products if p["name"] == "Asad")
    assert asad["image_path"] == ""  # sin foto real => sin foto, jamás inventada

    # Reimportar actualiza, no duplica
    resp2 = _import_catalog(monkeypatch, cid)
    assert resp2.json()["imported"] == 0
    assert resp2.json()["updated"] == 3


def test_import_dedupes_names_within_batch(monkeypatch, tmp_path):
    """Regresión de producción: el API de arfagi trae nombres duplicados
    (kits distintos, mismo nombre) y rompía la restricción única."""
    html = ARFAGI_HTML.replace(
        "{id:'s3',name:'Asad'",
        "{id:'s4',name:'Miss Dior',brand:'Dior',salePrice:900000,inStock:true,image:''},{id:'s3',name:'Asad'",
    )
    company = _create_company("ecommerce", "Perfumería Dup")
    cid = company["id"]
    monkeypatch.setattr(catalog_engine, "MEDIA_DIR", tmp_path)

    async def fake_get(self, url, **kwargs):
        class R:
            status_code = 200
            headers = {"content-type": "image/jpeg"}
            content = b"img"
            text = html

            def raise_for_status(self):
                pass

        return R()

    import httpx

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    resp = client.post(f"/api/companies/{cid}/catalog/import", json={"website": "https://x.com"})
    assert resp.status_code == 200
    products = client.get(f"/api/companies/{cid}/products").json()
    names = [p["name"] for p in products]
    assert names.count("Miss Dior") == 1  # se queda el primero, sin explotar


def test_chat_search_catalog_attaches_real_photos(monkeypatch, tmp_path):
    company = _create_company("ecommerce", "Perfumería Fotos")
    cid = company["id"]
    monkeypatch.setattr(catalog_engine, "MEDIA_DIR", tmp_path)
    _import_catalog(monkeypatch, cid)

    async def fake_chat(messages, tools=None, **kwargs):
        if not any(m.get("role") == "tool" for m in messages):
            return {"content": None, "tool_calls": [
                {"id": "c1", "function": {"name": "search_catalog", "arguments": json.dumps({"query": "perfume Dior mujer"})}}
            ]}
        return {"content": "¡Mirá! Te mando la foto de Miss Dior, sale ₲ 685.000."}

    monkeypatch.setattr(chat_engine, "chat_raw", fake_chat)
    resp = client.post(
        f"/api/companies/{cid}/chat",
        json={"contact_phone": "+595971515151", "text": "¿Tenés algo de Dior para mujer?"},
    )
    data = resp.json()
    assert data["media"], "debe adjuntar la foto real"
    assert data["media"][0]["path"].startswith(f"/media/{cid}/catalog/")
    assert "Miss Dior" in data["media"][0]["caption"]
    assert "₲ 685.000" in data["media"][0]["caption"]


def test_campaign_uses_real_catalog_photos(monkeypatch, tmp_path):
    company = _create_company("ecommerce", "Perfumería RealFoto")
    cid = company["id"]
    monkeypatch.setattr(catalog_engine, "MEDIA_DIR", tmp_path)
    _import_catalog(monkeypatch, cid)

    generated = []

    async def fake_complete(messages, **kwargs):
        content = messages[-1]["content"]
        if '"title"' in content:
            return '{"title": "Promo", "angle": "a", "audience": "p"}'
        if "tarjeta(s)" in content:
            return '[{"headline": "Good Girl te espera", "copy": "El clásico de Carolina Herrera"}, {"headline": "Regalos", "copy": "Envíos a todo el país"}]'
        return '{"severity": "ok", "note": "ok"}'

    async def fake_generate(prompt, width, height):
        generated.append(prompt)
        return b"x", "pollinations"

    monkeypatch.setattr(campaign_engine, "complete", fake_complete)
    monkeypatch.setattr(campaign_engine, "generate_image", fake_generate)
    resp = client.post(
        f"/api/companies/{cid}/campaigns",
        json={"brief": "Promo de perfumes", "format": "carousel", "n_cards": 2},
    )
    cards = resp.json()["cards"]
    # Tarjeta 1 matchea Good Girl por nombre; tarjeta 2 rota a otra foto real
    assert cards[0]["image_path"].startswith(f"/media/{cid}/catalog/")
    assert "FOTO REAL" in cards[0]["image_prompt"]
    assert "Good Girl" in cards[0]["image_prompt"]
    assert cards[1]["image_path"].startswith(f"/media/{cid}/catalog/")
    assert generated == []  # con catálogo real, JAMÁS se genera una imagen


def test_service_suggestions_come_from_industry_catalog_not_peers():
    """Antes las sugerencias salían de los servicios de OTRAS empresas, lo que
    filtraba su oferta y sus precios. Ahora salen de un catálogo curado del
    rubro (conocimiento público del sector)."""
    a = _create_company(name="Sanatorio A")
    b = _create_company(name="Sanatorio B")
    client.post(f"/api/companies/{a['id']}/services",
                json={"name": "Ecografía 4D Exclusiva", "category": "Estudios", "price_gs": 400000})

    suggestions = client.get(f"/api/companies/{b['id']}/services/suggestions").json()
    names = [s["name"] for s in suggestions]
    assert "Ecografía 4D Exclusiva" not in names  # no filtra la oferta ajena
    assert all(s["typical_price_gs"] == 0 for s in suggestions)  # ni sus precios
    # El catálogo curado por rubro: 233 estudios para "medical", cada uno
    # con su preparación previa. Antes salían 6 de una lista genérica.
    assert any("Consulta con clínico" in n for n in names), names[:5]
    assert len(names) > 50, f"el catálogo curado no se está usando: {len(names)} ítems"

    # Lo que la empresa ya tiene deja de sugerirse
    client.post(f"/api/companies/{b['id']}/services", json={"name": "Consulta clínica"})
    again = [s["name"] for s in client.get(f"/api/companies/{b['id']}/services/suggestions").json()]
    assert "Consulta clínica" not in again
