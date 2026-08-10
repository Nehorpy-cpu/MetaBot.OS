from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import onboarding
from ..auth import Identity, allowed_company_ids, get_identity
from ..db import get_db
from ..llm import LLMError
from ..models import Agent, Company
from ..swarm import _fetch_page_text
from ..packs import suggested_for
from ..templates import TEMPLATES

router = APIRouter(prefix="/companies", tags=["companies"])


class CompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    vertical: str = Field(pattern="^(medical|ecommerce)$")


class SmartCompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=10, max_length=2000)
    website: str = Field(default="", max_length=500)


class AgentOut(BaseModel):
    id: int
    slug: str
    name: str
    role: str
    model: str
    temperature: float
    active: bool

    model_config = {"from_attributes": True}


class CompanyOut(BaseModel):
    id: int
    name: str
    vertical: str
    niche: str
    industry: str
    address: str
    wa_mode: str
    wa_phone_number_id: str

    model_config = {"from_attributes": True}


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=300)
    wa_mode: str | None = Field(default=None, pattern="^(none|meta|qr)$")
    wa_phone_number_id: str | None = Field(default=None, max_length=50)


@router.post("", response_model=CompanyOut, status_code=201)
def create_company(payload: CompanyCreate, db: Session = Depends(get_db)):
    """Crea el tenant y siembra su enjambre de 6 agentes según la vertical."""
    template = TEMPLATES[payload.vertical]
    company = Company(
        name=payload.name,
        vertical=payload.vertical,
        niche=template["niche"],
        packs=",".join(suggested_for(payload.vertical)),
    )
    db.add(company)
    db.flush()
    for spec in template["agents"]:
        db.add(Agent(company_id=company.id, **spec))
    db.commit()
    db.refresh(company)
    return company


@router.post("/smart", response_model=CompanyOut, status_code=201)
async def create_company_smart(payload: SmartCompanyCreate, db: Session = Depends(get_db)):
    """Arquitecto de Negocio: perfila cualquier rubro y arma el enjambre a medida."""
    website_text = ""
    if payload.website.startswith(("http://", "https://")):
        try:
            website_text = await _fetch_page_text(payload.website)
        except Exception:
            website_text = ""  # la web es opcional: si falla, se perfila sin ella
    try:
        return await onboarding.profile_and_create(
            db, payload.name, payload.description, website_text, website=payload.website
        )
    except LLMError as exc:
        raise HTTPException(503, f"LLM no disponible: {exc}")
    except ValueError as exc:
        raise HTTPException(502, str(exc))


@router.get("", response_model=list[CompanyOut])
def list_companies(
    identity: Identity = Depends(get_identity), db: Session = Depends(get_db)
):
    """Solo las empresas donde la identidad tiene membresía activa.

    El operador de la plataforma ve todas; un usuario normal jamás puede
    enumerar tenants ajenos.
    """
    allowed = allowed_company_ids(db, identity)
    query = db.query(Company)
    if allowed is not None:
        if not allowed:
            return []
        query = query.filter(Company.id.in_(allowed))
    return query.order_by(Company.id).all()


@router.get("/{company_id}", response_model=CompanyOut)
def get_company(company_id: int, db: Session = Depends(get_db)):
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Empresa no encontrada")
    return company


@router.patch("/{company_id}", response_model=CompanyOut)
def update_company(company_id: int, payload: CompanyUpdate, db: Session = Depends(get_db)):
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Empresa no encontrada")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(company, field, value)
    db.commit()
    db.refresh(company)
    return company


@router.get("/{company_id}/agents", response_model=list[AgentOut])
def list_agents(company_id: int, db: Session = Depends(get_db)):
    if not db.get(Company, company_id):
        raise HTTPException(404, "Empresa no encontrada")
    return db.query(Agent).filter(Agent.company_id == company_id).order_by(Agent.id).all()
