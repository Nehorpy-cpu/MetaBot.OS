"""Super-Configurator: administración de agentes del enjambre.

NOTA: estos endpoints exponen y editan system prompts. Cuando el panel se
publique fuera de localhost, deben quedar detrás de autenticación (Fase 2).
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import Identity, assert_company_access, get_identity
from ..db import get_db
from .. import evaluator
from ..models import Agent, AgentPromptVersion, EvalResult
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


# --- Versionado de prompts y evaluación (etapa 5) ---


class CandidateIn(BaseModel):
    body: str = Field(min_length=10)
    note: str = Field(default="", max_length=300)


@router.get("/{agent_id}/versions")
def list_versions(
    agent_id: int, identity: Identity = Depends(get_identity), db: Session = Depends(get_db)
):
    """Historial del prompt: qué se activó, cuándo y con qué evidencia."""
    agent = _owned_agent(agent_id, identity, db, Perm.READ)
    evaluator.asegurar_version_inicial(db, agent)
    db.commit()
    filas = (
        db.query(AgentPromptVersion)
        .filter(
            AgentPromptVersion.company_id == agent.company_id,
            AgentPromptVersion.agent_id == agent.id,
        )
        .order_by(AgentPromptVersion.version.desc())
        .all()
    )
    return [
        {
            "id": v.id, "version": v.version, "role": v.role, "source": v.source,
            "note": v.note, "eval_run_id": v.eval_run_id,
            "created_at": v.created_at.isoformat(),
            "activated_at": v.activated_at.isoformat() if v.activated_at else None,
            "preview": v.body[:200],
        }
        for v in filas
    ]


@router.post("/{agent_id}/versions", status_code=201)
def create_candidate(
    agent_id: int, payload: CandidateIn,
    identity: Identity = Depends(get_identity), db: Session = Depends(get_db),
):
    """Registra un prompt candidato. NO toca lo que está en producción."""
    agent = _owned_agent(agent_id, identity, db, Perm.WRITE)
    v = evaluator.crear_candidato(db, agent, payload.body, note=payload.note)
    db.commit()
    return {"id": v.id, "version": v.version, "role": v.role}


@router.post("/{agent_id}/versions/{version_id}/activate")
def activate_version(
    agent_id: int, version_id: int,
    identity: Identity = Depends(get_identity), db: Session = Depends(get_db),
):
    """Promueve una versión, o vuelve a una anterior.

    Una versión nueva sin evaluación aprobada NO se activa. Un rollback a una
    versión que ya estuvo en producción sí: volver a algo que ya funcionaba no
    necesita permiso, y si hay que apagar un incendio el trámite es el enemigo.
    """
    agent = _owned_agent(agent_id, identity, db, Perm.WRITE)
    resultado = evaluator.activar(db, agent, version_id)
    if not resultado["ok"]:
        raise HTTPException(409, resultado["error"])
    db.commit()
    return resultado


@router.post("/{agent_id}/evaluate")
async def evaluate_agent(
    agent_id: int, version_id: int | None = None,
    identity: Identity = Depends(get_identity), db: Session = Depends(get_db),
):
    """Corre el conjunto dorado contra el prompt vigente o un candidato.

    Cada caso tiene respuesta verificable —qué herramienta hay que llamar, qué
    texto está prohibido—: no opina ningún modelo sobre si la respuesta "está
    bien". Los casos marcados como guardrail rechazan al candidato aunque todo
    el resto mejore.
    """
    from ..models import Company

    agent = _owned_agent(agent_id, identity, db, Perm.WRITE)
    company = db.get(Company, agent.company_id)
    version = db.get(AgentPromptVersion, version_id) if version_id else None
    if version_id and (not version or version.agent_id != agent.id):
        raise HTTPException(404, "Esa versión no es de este agente")

    corrida = await evaluator.correr(db, company, agent, version)
    resultados = (
        db.query(EvalResult).filter(EvalResult.eval_run_id == corrida.id).all()
    )
    return {
        "eval_run_id": corrida.id,
        "verdict": corrida.verdict,
        "reason": corrida.reason,
        "total": corrida.total,
        "passed": corrida.passed,
        "critical_failed": corrida.critical_failed,
        "latency_ms": corrida.latency_ms,
        "casos": [
            {
                "case": r.case_slug, "passed": r.passed, "critical": r.critical,
                "failures": r.failures, "tools": r.tools_used,
            }
            for r in resultados
        ],
    }
