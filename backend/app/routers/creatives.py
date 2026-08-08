"""Estudio Visual: el Director Creativo redacta el copy y el Estudio Visual
genera la imagen. Cada agente con lo suyo, coordinados en un solo flujo."""
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..imagegen import ImageGenError, generate_image
from ..llm import LLMError, complete
from ..models import Agent, Company, Creative

router = APIRouter(tags=["creatives"])

MEDIA_DIR = Path(__file__).resolve().parents[2] / "media"


class CreativeIn(BaseModel):
    brief: str = Field(min_length=5, max_length=2000)
    width: int = Field(default=1024, ge=256, le=1536)
    height: int = Field(default=1024, ge=256, le=1536)


def _agent(db: Session, company_id: int, slug: str) -> Agent | None:
    return (
        db.query(Agent)
        .filter(Agent.company_id == company_id, Agent.slug == slug, Agent.active)
        .first()
    )


@router.post("/companies/{company_id}/creatives")
async def create_creative(company_id: int, payload: CreativeIn, db: Session = Depends(get_db)):
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Empresa no encontrada")
    creative_agent = _agent(db, company_id, "creative")
    visual_agent = _agent(db, company_id, "visual")

    try:
        copy_text = await complete(
            [
                {
                    "role": "user",
                    "content": (
                        f"{creative_agent.system_prompt if creative_agent else 'Sos copywriter.'}\n\n"
                        f"Negocio: {company.name} ({company.niche}).\n"
                        f"Brief: {payload.brief}\n\n"
                        "Escribí UN copy publicitario listo para publicar en redes: "
                        "gancho + beneficio + llamado a la acción. Máximo 60 palabras, "
                        "voseo paraguayo, precios en ₲ solo si el brief los da."
                    ),
                }
            ],
            model=creative_agent.model if creative_agent else None,
            temperature=creative_agent.temperature if creative_agent else 0.6,
            max_tokens=300,
        )
        image_prompt = await complete(
            [
                {
                    "role": "user",
                    "content": (
                        f"{visual_agent.system_prompt if visual_agent else 'Sos director de arte.'}\n\n"
                        f"Negocio: {company.name} ({company.niche}). Brief: {payload.brief}\n\n"
                        "Escribí SOLO el prompt de imagen en inglés para un generador "
                        "(una frase, estilo fotografía publicitaria profesional, sin texto "
                        "en la imagen, sin marcas). Nada más que el prompt."
                    ),
                }
            ],
            temperature=0.4,
            max_tokens=150,
        )
    except LLMError as exc:
        raise HTTPException(503, f"LLM no disponible: {exc}")

    image_prompt = image_prompt.strip().strip('"')
    try:
        image_bytes, provider = await generate_image(image_prompt, payload.width, payload.height)
    except ImageGenError as exc:
        raise HTTPException(503, str(exc))

    folder = MEDIA_DIR / str(company_id)
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.png"
    (folder / filename).write_bytes(image_bytes)

    creative = Creative(
        company_id=company_id,
        brief=payload.brief,
        copy_text=copy_text.strip(),
        image_prompt=image_prompt,
        image_path=f"/media/{company_id}/{filename}",
        provider=provider,
    )
    db.add(creative)
    db.commit()
    db.refresh(creative)
    return _serialize(creative)


@router.get("/companies/{company_id}/creatives")
def list_creatives(company_id: int, db: Session = Depends(get_db)):
    if not db.get(Company, company_id):
        raise HTTPException(404, "Empresa no encontrada")
    creatives = (
        db.query(Creative)
        .filter(Creative.company_id == company_id)
        .order_by(Creative.id.desc())
        .limit(50)
        .all()
    )
    return [_serialize(c) for c in creatives]


@router.delete("/companies/{company_id}/creatives/{creative_id}", status_code=204)
def delete_creative(company_id: int, creative_id: int, db: Session = Depends(get_db)):
    creative = db.get(Creative, creative_id)
    if not creative or creative.company_id != company_id:
        raise HTTPException(404, "Creativo no encontrado")
    if creative.image_path:
        file = MEDIA_DIR / creative.image_path.removeprefix("/media/")
        file.unlink(missing_ok=True)
    db.delete(creative)
    db.commit()


def _serialize(c: Creative) -> dict:
    return {
        "id": c.id,
        "brief": c.brief,
        "copy_text": c.copy_text,
        "image_prompt": c.image_prompt,
        "image_path": c.image_path,
        "provider": c.provider,
        "created_at": c.created_at.isoformat(),
    }
