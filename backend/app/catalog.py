"""Importador de catálogo REAL desde la web del negocio.

Principio innegociable: ningún agente inventa productos ni imágenes.
1. Se parsean los datos estructurados embebidos en el HTML (objetos JS tipo
   {name:'Miss Dior', brand:'Dior', salePrice:685000, image:'...'}).
2. Las imágenes se DESCARGAN del sitio (fotos reales), nunca se generan.
3. Si el sitio no tiene datos estructurados, un LLM extrae SOLO lo que está
   en el texto scrapeado (extracción, no creación).
"""
import json
import re
import uuid
from pathlib import Path
from urllib.parse import urljoin

import httpx
from sqlalchemy.orm import Session

from .llm import complete
from .models import Company, Product

MEDIA_DIR = Path(__file__).resolve().parents[1] / "media"

# Objetos JS con al menos name y algún precio/imagen
_JS_OBJ_RE = re.compile(r"\{[^{}]*?name\s*:\s*['\"][^{}]*?\}", re.DOTALL)
_FIELD_RE = re.compile(r"(\w+)\s*:\s*(?:'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"|([\d.]+)|true|false)")


def _parse_js_products(html: str) -> list[dict]:
    products = []
    for match in _JS_OBJ_RE.finditer(html):
        obj_src = match.group()
        fields: dict = {}
        for fm in _FIELD_RE.finditer(obj_src):
            key = fm.group(1)
            if fm.group(2) is not None:
                value = fm.group(2)      # string con comillas simples (puede ser vacío)
            elif fm.group(3) is not None:
                value = fm.group(3)      # string con comillas dobles
            elif fm.group(4) is not None:
                value = fm.group(4)      # número
            else:
                value = "true" in fm.group(0)
            fields[key] = value
        if "inStock" in obj_src:
            fields["inStock"] = bool(re.search(r"inStock\s*:\s*true", obj_src))
        name = str(fields.get("name", "")).strip()
        if not name or len(name) < 2:
            continue
        price_raw = fields.get("salePrice") or fields.get("price") or 0
        try:
            price = int(float(price_raw))
        except (TypeError, ValueError):
            price = 0
        products.append(
            {
                "name": name[:200],
                "brand": str(fields.get("brand", ""))[:100],
                "category": str(fields.get("category", ""))[:100],
                "gender": str(fields.get("gender", ""))[:30],
                "price_gs": price,
                "in_stock": bool(fields.get("inStock", True)),
                "image": str(fields.get("image", "")),
            }
        )
    # dedupe por nombre conservando el primero
    seen: set[str] = set()
    unique = []
    for p in products:
        if p["name"].lower() not in seen:
            seen.add(p["name"].lower())
            unique.append(p)
    return unique


async def _llm_extract_products(text: str) -> list[dict]:
    """Fallback: extracción (no invención) desde texto scrapeado."""
    raw = await complete(
        [
            {
                "role": "user",
                "content": (
                    "Extraé los productos que APARECEN LITERALMENTE en este texto de una "
                    "tienda (nombre, marca, precio si figura). NO agregues productos que no "
                    'estén escritos. Respondé SOLO JSON: [{"name": "...", "brand": "...", '
                    '"category": "", "price_gs": 0}]\n\n' + text[:8000]
                ),
            }
        ],
        temperature=0.1,
        max_tokens=1500,
    )
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        return []
    try:
        items = json.loads(match.group())
    except json.JSONDecodeError:
        return []
    return [
        {
            "name": str(i.get("name", ""))[:200],
            "brand": str(i.get("brand", ""))[:100],
            "category": str(i.get("category", ""))[:100],
            "gender": "",
            "price_gs": int(i.get("price_gs") or 0),
            "in_stock": True,
            "image": "",
        }
        for i in items
        if isinstance(i, dict) and i.get("name")
    ]


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _map_api_item(item: dict) -> dict | None:
    """Mapea un producto de un API JSON a nuestro esquema (solo campos reales)."""
    name = str(item.get("name") or item.get("nombre") or item.get("title") or "").strip()
    if not name:
        return None
    price_raw = item.get("salePrice") or item.get("price") or item.get("precio") or 0
    try:
        price = int(float(price_raw))
    except (TypeError, ValueError):
        price = 0
    stock = item.get("inStock", item.get("in_stock", item.get("stock", True)))
    notes = " | ".join(
        _strip_html(str(item.get(k, ""))) for k in ("shortDescription", "description", "descripcion") if item.get(k)
    )[:1500]
    return {
        "name": name[:200],
        "brand": str(item.get("brand") or item.get("marca") or "")[:100],
        "category": str(item.get("category") or item.get("categoria") or "")[:100],
        "gender": str(item.get("gender") or item.get("genero") or "")[:30],
        "price_gs": price,
        "in_stock": bool(stock) if not isinstance(stock, (int, float)) or isinstance(stock, bool) else stock > 0,
        "image": str(item.get("image") or item.get("imageUrl") or item.get("imagen") or ""),
        "notes": notes,
    }


async def _discover_api_products(client: httpx.AsyncClient, html: str, base_url: str) -> list[dict]:
    """Busca en el HTML endpoints JSON de catálogo (api/catalog, products…)
    y devuelve los productos REALES que expongan."""
    from urllib.parse import urljoin

    candidates = []
    for ref in re.findall(r'["\'](https?://[^"\'\s]+|/[^"\'\s]+)["\']', html):
        if re.search(r"(catalog|products?)", ref, re.I) and not re.search(
            r"\.(css|js|png|jpe?g|svg|webp|ico|html?)([?#]|$)", ref, re.I
        ):
            url = urljoin(base_url, ref)
            if url not in candidates:
                candidates.append(url)
    for url in candidates[:5]:
        try:
            resp = await client.get(url)
            if resp.status_code != 200 or "json" not in resp.headers.get("content-type", ""):
                continue
            data = resp.json()
            items = data if isinstance(data, list) else (
                data.get("items") or data.get("products") or data.get("data") or []
            )
            mapped = [m for i in items if isinstance(i, dict) and (m := _map_api_item(i))]
            if len(mapped) >= 3:
                return mapped
        except (httpx.HTTPError, ValueError):
            continue
    return []


async def _download_image(client: httpx.AsyncClient, base_url: str, image_ref: str, folder: Path) -> str:
    if not image_ref:
        return ""
    url = urljoin(base_url, image_ref)
    try:
        resp = await client.get(url)
        if resp.status_code != 200 or not resp.headers.get("content-type", "").startswith("image"):
            return ""
        ext = ".png" if "png" in resp.headers["content-type"] else ".jpg"
        filename = f"{uuid.uuid4().hex}{ext}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / filename).write_bytes(resp.content)
        return filename
    except httpx.HTTPError:
        return ""


async def import_catalog(db: Session, company: Company, website: str) -> dict:
    async with httpx.AsyncClient(
        timeout=40, follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (MetaBot.OS catalog)"},
    ) as client:
        resp = await client.get(website)
        resp.raise_for_status()
        html = resp.text

        items = await _discover_api_products(client, html, website)
        method = "api"
        if not items:
            items = _parse_js_products(html)
            method = "estructurado"
        if len(items) < 3:
            text = re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I))
            items = await _llm_extract_products(re.sub(r"\s+", " ", text))
            method = "extracción LLM"
        if not items:
            raise ValueError("No se encontraron productos en el sitio.")

        folder = MEDIA_DIR / str(company.id) / "catalog"
        imported = updated = with_image = 0
        for item in items:
            item.setdefault("notes", "")
            filename = await _download_image(client, website, item.pop("image", ""), folder)
            image_path = f"/media/{company.id}/catalog/{filename}" if filename else ""
            if image_path:
                with_image += 1
            existing = (
                db.query(Product)
                .filter(Product.company_id == company.id, Product.name == item["name"])
                .first()
            )
            if existing:
                for field, value in item.items():
                    setattr(existing, field, value)
                if image_path:
                    existing.image_url = website
                    existing.image_path = image_path
                updated += 1
            else:
                db.add(
                    Product(
                        company_id=company.id,
                        source_url=website,
                        image_url=website if image_path else "",
                        image_path=image_path,
                        **item,
                    )
                )
                imported += 1
        db.commit()
    return {"method": method, "imported": imported, "updated": updated, "with_image": with_image}
