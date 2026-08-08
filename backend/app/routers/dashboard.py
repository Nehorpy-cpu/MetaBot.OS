from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Agent, Appointment, Company, Conversation, Doctor

router = APIRouter(tags=["dashboard"])


@router.get("/companies/{company_id}/dashboard")
def dashboard(company_id: int, db: Session = Depends(get_db)):
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Empresa no encontrada")
    today = date.today()
    start = datetime(today.year, today.month, today.day)
    end = start.replace(hour=23, minute=59, second=59)
    return {
        "company": {"id": company.id, "name": company.name, "vertical": company.vertical, "niche": company.niche},
        "agents_active": db.query(Agent).filter(Agent.company_id == company_id, Agent.active).count(),
        "agents_total": db.query(Agent).filter(Agent.company_id == company_id).count(),
        "doctors": db.query(Doctor).filter(Doctor.company_id == company_id).count(),
        "appointments_today": db.query(Appointment)
        .filter(
            Appointment.company_id == company_id,
            Appointment.scheduled_at >= start,
            Appointment.scheduled_at <= end,
            Appointment.status != "cancelled",
        )
        .count(),
        "conversations": db.query(Conversation).filter(Conversation.company_id == company_id).count(),
    }
