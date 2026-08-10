from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import onboarding
from ..auth import Identity, allowed_company_ids, get_identity
from ..db import get_db
from ..llm import LLMError
from ..models import Agent, Company, Membership, Supervision
from ..permissions import Role
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
    supervision: str
    supervision_pct: int

    model_config = {"from_attributes": True}


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=300)
    wa_mode: str | None = Field(default=None, pattern="^(none|meta|qr)$")
    wa_phone_number_id: str | None = Field(default=None, max_length=50)
    # Supervisión del CEO. El patrón cierra la puerta a valores inventados:
    # cualquier cosa fuera de estos tres es 422, no un modo silencioso.
    supervision: str | None = Field(default=None, pattern="^(off|shadow|inline)$")
    supervision_pct: int | None = Field(default=None, ge=0, le=100)


def _grant_owner(db: Session, identity: Identity, company_id: int) -> None:
    """Quien crea una empresa queda como owner (si es un usuario, no el token)."""
    if identity.user_id:
        db.add(Membership(user_id=identity.user_id, company_id=company_id, role=Role.OWNER.value))


@router.post("", response_model=CompanyOut, status_code=201)
def create_company(
    payload: CompanyCreate,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Crea el tenant y siembra su enjambre de agentes según la vertical.

    Solo el operador de la plataforma da de alta empresas: si no, cualquier
    usuario autenticado podría crear tenants ilimitados.
    """
    if not identity.is_platform:
        raise HTTPException(403, "Solo el operador de la plataforma puede crear empresas")
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
    _grant_owner(db, identity, company.id)
    db.commit()
    db.refresh(company)
    return company


@router.post("/smart", response_model=CompanyOut, status_code=201)
async def create_company_smart(
    payload: SmartCompanyCreate,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Arquitecto de Negocio: perfila cualquier rubro y arma el enjambre a medida."""
    if not identity.is_platform:
        raise HTTPException(403, "Solo el operador de la plataforma puede crear empresas")
    website_text = ""
    if payload.website.startswith(("http://", "https://")):
        try:
            website_text = await _fetch_page_text(payload.website)
        except Exception:
            website_text = ""  # la web es opcional: si falla, se perfila sin ella
    try:
        company = await onboarding.profile_and_create(
            db, payload.name, payload.description, website_text, website=payload.website
        )
        _grant_owner(db, identity, company.id)
        db.commit()
        return company
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


@router.get("/{company_id}/supervision")
def supervision_report(company_id: int, db: Session = Depends(get_db)):
    """Qué está encontrando el CEO al revisar los turnos del CX.

    Sirve para responder la única pregunta que importa antes de activar
    `inline`: ¿supervisar mejora las respuestas o solo agrega costo? Por eso
    se muestran separados los dos brazos (supervisado y control).
    """
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Empresa no encontrada")

    filas = (
        db.query(Supervision)
        .filter(Supervision.company_id == company_id)
        .order_by(Supervision.created_at.desc())
        .limit(200)
        .all()
    )
    supervisadas = [f for f in filas if f.arm == "supervised"]
    por_disparador: dict[str, int] = {}
    por_accion: dict[str, int] = {}
    for f in filas:
        por_disparador[f.trigger_key] = por_disparador.get(f.trigger_key, 0) + 1
    for f in supervisadas:
        por_accion[f.action] = por_accion.get(f.action, 0) + 1

    latencias = [f.latency_ms for f in supervisadas if f.latency_ms]
    return {
        "supervision": company.supervision,
        "supervision_pct": company.supervision_pct,
        "total": len(filas),
        "supervisadas": len(supervisadas),
        "control": len(filas) - len(supervisadas),
        "por_disparador": por_disparador,
        "por_accion": por_accion,
        "latencia_media_ms": round(sum(latencias) / len(latencias)) if latencias else 0,
        "recientes": [
            {
                "id": f.id,
                "conversation_id": f.conversation_id,
                "trigger": f.trigger_key,
                "agente": f.agent_slug,
                "modo": f.mode,
                "brazo": f.arm,
                "accion": f.action,
                "motivo": f.reason,
                "degradado": f.downgraded,
                "latencia_ms": f.latency_ms,
                "creado": f.created_at.isoformat(),
            }
            for f in filas[:25]
        ],
    }


@router.get("/{company_id}/agents", response_model=list[AgentOut])
def list_agents(company_id: int, db: Session = Depends(get_db)):
    if not db.get(Company, company_id):
        raise HTTPException(404, "Empresa no encontrada")
    return db.query(Agent).filter(Agent.company_id == company_id).order_by(Agent.id).all()
