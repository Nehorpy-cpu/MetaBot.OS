from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Agent, Company
from ..templates import TEMPLATES

router = APIRouter(prefix="/companies", tags=["companies"])


class CompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    vertical: str = Field(pattern="^(medical|ecommerce)$")


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
    wa_phone_number_id: str

    model_config = {"from_attributes": True}


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    wa_phone_number_id: str | None = Field(default=None, max_length=50)


@router.post("", response_model=CompanyOut, status_code=201)
def create_company(payload: CompanyCreate, db: Session = Depends(get_db)):
    """Crea el tenant y siembra su enjambre de 6 agentes según la vertical."""
    template = TEMPLATES[payload.vertical]
    company = Company(name=payload.name, vertical=payload.vertical, niche=template["niche"])
    db.add(company)
    db.flush()
    for spec in template["agents"]:
        db.add(Agent(company_id=company.id, **spec))
    db.commit()
    db.refresh(company)
    return company


@router.get("", response_model=list[CompanyOut])
def list_companies(db: Session = Depends(get_db)):
    return db.query(Company).order_by(Company.id).all()


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
