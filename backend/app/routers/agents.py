"""Super-Configurator: administración de agentes del enjambre.

NOTA: estos endpoints exponen y editan system prompts. Cuando el panel se
publique fuera de localhost, deben quedar detrás de autenticación (Fase 2).
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Agent

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentDetail(BaseModel):
    id: int
    company_id: int
    slug: str
    name: str
    role: str
    model: str
    system_prompt: str
    temperature: float
    active: bool

    model_config = {"from_attributes": True}


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=100)
    system_prompt: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    active: bool | None = None


@router.get("/{agent_id}", response_model=AgentDetail)
def get_agent(agent_id: int, db: Session = Depends(get_db)):
    agent = db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "Agente no encontrado")
    return agent


@router.patch("/{agent_id}", response_model=AgentDetail)
def update_agent(agent_id: int, payload: AgentUpdate, db: Session = Depends(get_db)):
    agent = db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "Agente no encontrado")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(agent, field, value)
    db.commit()
    db.refresh(agent)
    return agent
