import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import catalog as catalog_engine
from ..db import get_db
from ..llm import LLMError
from ..models import Company, Product

router = APIRouter(tags=["catalog"])


class ImportIn(BaseModel):
    website: str = Field(default="", max_length=500)


def _serialize(p: Product) -> dict:
    return {
        "id": p.id, "name": p.name, "brand": p.brand, "category": p.category,
        "gender": p.gender, "price_gs": p.price_gs, "in_stock": p.in_stock,
        "image_path": p.image_path, "notes": p.notes, "active": p.active,
    }


@router.post("/companies/{company_id}/catalog/import")
async def import_catalog(company_id: int, payload: ImportIn, db: Session = Depends(get_db)):
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Empresa no encontrada")
    website = payload.website.strip()
    if not website:
        try:
            website = json.loads(company.profile or "{}").get("website", "")
        except json.JSONDecodeError:
            website = ""
    if not website.startswith(("http://", "https://")):
        raise HTTPException(422, "Pasá la URL del sitio (https://...) o guardala en el perfil de la empresa")
    try:
        return await catalog_engine.import_catalog(db, company, website)
    except LLMError as exc:
        raise HTTPException(503, f"LLM no disponible: {exc}")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"No se pudo leer el sitio: {exc}")


@router.get("/companies/{company_id}/products")
def list_products(company_id: int, db: Session = Depends(get_db)):
    if not db.get(Company, company_id):
        raise HTTPException(404, "Empresa no encontrada")
    products = (
        db.query(Product)
        .filter(Product.company_id == company_id)
        .order_by(Product.brand, Product.name)
        .limit(500)
        .all()
    )
    return [_serialize(p) for p in products]
