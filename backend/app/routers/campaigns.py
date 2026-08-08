import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import campaigns as campaign_engine
from ..db import get_db
from ..llm import LLMError
from ..models import Campaign, Company

router = APIRouter(tags=["campaigns"])


class CampaignIn(BaseModel):
    brief: str = Field(min_length=10, max_length=2000)
    format: str = Field(pattern="^(carousel|single|video_script)$")
    n_cards: int = Field(default=4, ge=1, le=8)


def _serialize(c: Campaign) -> dict:
    return {
        "id": c.id,
        "title": c.title,
        "brief": c.brief,
        "format": c.format,
        "strategy": json.loads(c.strategy or "{}"),
        "cards": json.loads(c.cards or "[]"),
        "audit_severity": c.audit_severity,
        "audit_note": c.audit_note,
        "status": c.status,
        "created_at": c.created_at.isoformat(),
    }


@router.post("/companies/{company_id}/campaigns")
async def create_campaign(company_id: int, payload: CampaignIn, db: Session = Depends(get_db)):
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Empresa no encontrada")
    try:
        campaign = await campaign_engine.build_campaign(
            db, company, payload.brief, payload.format, payload.n_cards
        )
    except LLMError as exc:
        raise HTTPException(503, f"LLM no disponible: {exc}")
    except ValueError as exc:
        raise HTTPException(502, str(exc))
    return _serialize(campaign)


@router.get("/companies/{company_id}/campaigns")
def list_campaigns(company_id: int, db: Session = Depends(get_db)):
    if not db.get(Company, company_id):
        raise HTTPException(404, "Empresa no encontrada")
    items = (
        db.query(Campaign)
        .filter(Campaign.company_id == company_id)
        .order_by(Campaign.id.desc())
        .limit(30)
        .all()
    )
    return [_serialize(c) for c in items]


@router.delete("/companies/{company_id}/campaigns/{campaign_id}", status_code=204)
def delete_campaign(company_id: int, campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign or campaign.company_id != company_id:
        raise HTTPException(404, "Campaña no encontrada")
    db.delete(campaign)
    db.commit()
