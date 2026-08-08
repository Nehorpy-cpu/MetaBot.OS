"""Informes, auditoría y competencia: la cara HTTP del enjambre autónomo."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy.orm import Session

from .. import swarm
from ..analytics import compute_stats
from ..db import get_db
from ..llm import LLMError
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
    suggestion = db.get(PromptSuggestion, suggestion_id)
    if not suggestion or suggestion.company_id != company_id:
        raise HTTPException(404, "Sugerencia no encontrada")
    if suggestion.status != "pending":
        raise HTTPException(409, f"La sugerencia ya está en estado '{suggestion.status}'")
    agent = db.get(Agent, suggestion.agent_id)
    if not agent:
        raise HTTPException(404, "El agente ya no existe")
    agent.system_prompt = suggestion.suggested_prompt
    suggestion.status = "applied"
    db.commit()
    return {"applied": True, "agent_id": agent.id}


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
    source = CompetitorSource(company_id=company_id, url=url, label=payload.label)
    db.add(source)
    db.commit()
    db.refresh(source)
    return {"id": source.id, "url": source.url, "label": source.label}


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
