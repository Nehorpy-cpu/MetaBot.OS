"""Super-Configurator: administración de agentes del enjambre.

NOTA: estos endpoints exponen y editan system prompts. Cuando el panel se
publique fuera de localhost, deben quedar detrás de autenticación (Fase 2).
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import Identity, assert_company_access, get_identity
from ..db import get_db
from ..models import Agent
from ..permissions import Perm

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


def _owned_agent(agent_id: int, identity: Identity, db: Session, perm: Perm) -> Agent:
    """Agente validado contra la identidad.

    Esta ruta NO lleva company_id en el path, así que el middleware de tenant
    no la cubre: la pertenencia se comprueba acá, contra las membresías.
    """
    agent = db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "Agente no encontrado")
    assert_company_access(db, identity, agent.company_id, perm)
    return agent


@router.get("/{agent_id}", response_model=AgentDetail)
def get_agent(
    agent_id: int,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    return _owned_agent(agent_id, identity, db, Perm.READ)


@router.patch("/{agent_id}", response_model=AgentDetail)
def update_agent(
    agent_id: int,
    payload: AgentUpdate,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    # Editar el system prompt cambia la conducta del bot: exige rol con
    # permiso de configuración, no cualquier miembro.
    agent = _owned_agent(agent_id, identity, db, Perm.CONFIGURE_AGENTS)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(agent, field, value)
    db.commit()
    db.refresh(agent)
    return agent
