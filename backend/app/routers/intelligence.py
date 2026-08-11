"""Informes, auditoría y competencia: la cara HTTP del enjambre autónomo."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy.orm import Session

from .. import swarm
from ..analytics import compute_stats
from ..db import get_db
from ..llm import LLMError
from .. import evaluator, intelligence_sources, job_handlers
from ..models import Agent, AuditFinding, Company, CompetitorSource, PromptSuggestion, Report

router = APIRouter(tags=["intelligence"])


def _company(company_id: int, db: Session) -> Company:
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Empresa no encontrada")
    return company


@router.get("/companies/{company_id}/stats")
def stats(company_id: int, days: int = 7, db: Session = Depends(get_db)):
    return compute_stats(db, _company(company_id, db), min(days, 90))


@router.post("/companies/{company_id}/reports/weekly")
async def generate_weekly(company_id: int, db: Session = Depends(get_db)):
    try:
        report = await swarm.run_weekly_report(db, _company(company_id, db))
    except LLMError as exc:
        raise HTTPException(503, f"LLM no disponible: {exc}")
    return {"id": report.id, "title": report.title, "content": report.content}


@router.post("/companies/{company_id}/reports/competitive")
async def generate_competitive(company_id: int, db: Session = Depends(get_db)):
    try:
        report = await swarm.run_competitive_scan(db, _company(company_id, db))
    except LLMError as exc:
        raise HTTPException(503, f"LLM no disponible: {exc}")
    if not report:
        raise HTTPException(422, "No hay competidores cargados. Agregá URLs primero.")
    return {"id": report.id, "title": report.title, "content": report.content}


@router.get("/companies/{company_id}/reports")
def list_reports(company_id: int, db: Session = Depends(get_db)):
    _company(company_id, db)
    reports = (
        db.query(Report)
        .filter(Report.company_id == company_id)
        .order_by(Report.id.desc())
        .limit(30)
        .all()
    )
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "title": r.title,
            "content": r.content,
            "created_at": r.created_at.isoformat(),
        }
        for r in reports
    ]


@router.post("/companies/{company_id}/audits/run")
async def run_audit(company_id: int, db: Session = Depends(get_db)):
    try:
        findings = await swarm.run_guard_audit(db, _company(company_id, db))
    except LLMError as exc:
        raise HTTPException(503, f"LLM no disponible: {exc}")
    return {"new_findings": len(findings)}


@router.get("/companies/{company_id}/audits")
def list_audits(company_id: int, db: Session = Depends(get_db)):
    _company(company_id, db)
    findings = (
        db.query(AuditFinding)
        .filter(AuditFinding.company_id == company_id)
        .order_by(AuditFinding.id.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": f.id,
            "conversation_id": f.conversation_id,
            "severity": f.severity,
            "note": f.note,
            "created_at": f.created_at.isoformat(),
        }
        for f in findings
    ]


class SegmentResearchIn(BaseModel):
    website: str = Field(default="", max_length=500)


@router.post("/companies/{company_id}/segments/research")
async def segment_research(
    company_id: int, payload: SegmentResearchIn, db: Session = Depends(get_db)
):
    """Investiga el mercado con scraping real y define segmentos de clientes."""
    try:
        report = await swarm.run_segment_research(db, _company(company_id, db), payload.website)
    except LLMError as exc:
        raise HTTPException(503, f"LLM no disponible: {exc}")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"id": report.id, "title": report.title, "content": report.content}


# --- Optimizador de Prompts ---

@router.post("/companies/{company_id}/prompt-suggestions/run")
async def run_optimizer(company_id: int, db: Session = Depends(get_db)):
    try:
        suggestions = await swarm.run_prompt_optimization(db, _company(company_id, db))
    except LLMError as exc:
        raise HTTPException(503, f"LLM no disponible: {exc}")
    return {"new_suggestions": len(suggestions)}


@router.get("/companies/{company_id}/prompt-suggestions")
def list_suggestions(company_id: int, db: Session = Depends(get_db)):
    _company(company_id, db)
    suggestions = (
        db.query(PromptSuggestion)
        .filter(PromptSuggestion.company_id == company_id)
        .order_by(PromptSuggestion.id.desc())
        .limit(30)
        .all()
    )
    out = []
    for s in suggestions:
        agent = db.get(Agent, s.agent_id)
        out.append(
            {
                "id": s.id,
                "agent_id": s.agent_id,
                "agent_name": agent.name if agent else f"agente {s.agent_id}",
                "old_prompt": s.old_prompt,
                "suggested_prompt": s.suggested_prompt,
                "rationale": s.rationale,
                "status": s.status,
                "created_at": s.created_at.isoformat(),
            }
        )
    return out


@router.post("/companies/{company_id}/prompt-suggestions/{suggestion_id}/apply")
def apply_suggestion(company_id: int, suggestion_id: int, db: Session = Depends(get_db)):
    """Manda la sugerencia a evaluación. NO la aplica en el acto.

    Antes esto escribía `agent.system_prompt` directo, y eso hacía tres cosas
    malas a la vez: salteaba el evaluador, no dejaba historial al que volver, y
    desincronizaba el versionado —la tabla habría seguido diciendo que la
    versión 1 estaba activa mientras el agente tenía otro texto—.

    Ahora la sugerencia se convierte en candidato y se encola la corrida del
    conjunto dorado. Si pasa, se activa sola; si rompe un guardrail, queda
    registrada con la evidencia y nadie toca producción. Que un cambio de
    prompt necesite evidencia es justamente el punto de la etapa 5.
    """
    suggestion = db.get(PromptSuggestion, suggestion_id)
    if not suggestion or suggestion.company_id != company_id:
        raise HTTPException(404, "Sugerencia no encontrada")
    if suggestion.status != "pending":
        raise HTTPException(409, f"La sugerencia ya está en estado '{suggestion.status}'")
    agent = db.get(Agent, suggestion.agent_id)
    if not agent or agent.company_id != company_id:
        raise HTTPException(404, "El agente ya no existe")

    candidato = evaluator.crear_candidato(
        db, agent, suggestion.suggested_prompt,
        source="optimizer", suggestion_id=suggestion.id,
        note=suggestion.rationale[:300],
    )
    suggestion.status = "evaluating"
    db.commit()
    job_handlers.schedule_prompt_eval(
        db, company_id, agent.id, candidato.id, suggestion.id
    )
    db.commit()
    return {
        "applied": False,
        "status": "evaluating",
        "version_id": candidato.id,
        "version": candidato.version,
        "nota": (
            "El cambio quedó como candidato y se está evaluando contra el "
            "conjunto dorado. Si pasa se activa solo; si rompe un guardrail "
            "queda bloqueado con el detalle de qué falló. Tarda unos minutos: "
            "cada caso corre el bot de verdad."
        ),
    }


@router.post("/companies/{company_id}/prompt-suggestions/{suggestion_id}/reject")
def reject_suggestion(company_id: int, suggestion_id: int, db: Session = Depends(get_db)):
    suggestion = db.get(PromptSuggestion, suggestion_id)
    if not suggestion or suggestion.company_id != company_id:
        raise HTTPException(404, "Sugerencia no encontrada")
    if suggestion.status != "pending":
        raise HTTPException(409, f"La sugerencia ya está en estado '{suggestion.status}'")
    suggestion.status = "rejected"
    db.commit()
    return {"rejected": True}


class CompetitorIn(BaseModel):
    url: HttpUrl
    label: str = Field(default="", max_length=200)


@router.post("/companies/{company_id}/competitors", status_code=201)
def add_competitor(company_id: int, payload: CompetitorIn, db: Session = Depends(get_db)):
    _company(company_id, db)
    url = str(payload.url)
    exists = (
        db.query(CompetitorSource)
        .filter(CompetitorSource.company_id == company_id, CompetitorSource.url == url)
        .first()
    )
    if exists:
        raise HTTPException(409, "Ese competidor ya está cargado")

    # Se revisa ANTES de guardar. Aceptar una URL de Instagram para que después
    # el escaneo falle raro deja al cliente creyendo que es un bug nuestro; y
    # peor, si funcionara, le pondríamos la cuenta en riesgo a él.
    revision = intelligence_sources.revisar_url(url)
    if not revision["permitida"]:
        raise HTTPException(422, f"{revision['motivo']} {revision['alternativa']}".strip())

    source = CompetitorSource(company_id=company_id, url=url, label=payload.label)
    db.add(source)
    db.commit()
    db.refresh(source)
    return {
        "id": source.id, "url": source.url, "label": source.label,
        "fuente": revision["fuente"],
    }


@router.get("/companies/{company_id}/intelligence-sources")
def list_intelligence_sources(company_id: int, db: Session = Depends(get_db)):
    """Qué fuentes de inteligencia existen y en qué estado.

    Se muestra también lo que NO se implementa y por qué: un cliente que
    pregunta "¿pueden mirar el Instagram de mi competencia?" merece la razón,
    no un silencio.
    """
    _company(company_id, db)
    return {"fuentes": intelligence_sources.catalogo()}


@router.get("/companies/{company_id}/competitors")
def list_competitors(company_id: int, db: Session = Depends(get_db)):
    _company(company_id, db)
    return [
        {"id": s.id, "url": s.url, "label": s.label}
        for s in db.query(CompetitorSource).filter(CompetitorSource.company_id == company_id).all()
    ]


@router.delete("/companies/{company_id}/competitors/{source_id}", status_code=204)
def delete_competitor(company_id: int, source_id: int, db: Session = Depends(get_db)):
    source = db.get(CompetitorSource, source_id)
    if not source or source.company_id != company_id:
        raise HTTPException(404, "Competidor no encontrado")
    db.delete(source)
    db.commit()
