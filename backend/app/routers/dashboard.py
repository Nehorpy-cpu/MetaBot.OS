from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import packs
from ..db import get_db
from ..models import Agent, Appointment, Company, Conversation, Doctor, Message, Product, Service

router = APIRouter(tags=["dashboard"])


@router.get("/companies/{company_id}/dashboard/series")
def dashboard_series(company_id: int, days: int = 14, db: Session = Depends(get_db)):
    """Series para los gráficos: actividad diaria y citas por estado.

    Los datos los arma el servidor; el frontend solo dibuja.
    """
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Empresa no encontrada")
    days = max(7, min(days, 90))
    today = date.today()
    start_day = today - timedelta(days=days - 1)
    start = datetime(start_day.year, start_day.month, start_day.day)

    # Mensajes entrantes por día (actividad real de clientes)
    rows = (
        db.query(Message.created_at)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(
            Conversation.company_id == company_id,
            Message.direction == "in",
            Message.created_at >= start,
        )
        .all()
    )
    per_day = {(start_day + timedelta(days=i)).isoformat(): 0 for i in range(days)}
    for (created,) in rows:
        key = created.date().isoformat()
        if key in per_day:
            per_day[key] += 1

    # Citas por estado (solo tiene sentido con pack de agenda)
    status_counts: dict[str, int] = {}
    for status, count in (
        db.query(Appointment.status, func.count(Appointment.id))
        .filter(Appointment.company_id == company_id)
        .group_by(Appointment.status)
        .all()
    ):
        status_counts[status] = count

    return {
        "activity": [{"date": k, "count": v} for k, v in per_day.items()],
        "appointments_by_status": status_counts,
        "has_booking": "book_appointment" in packs.tools_for(company),
    }


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
        "products": db.query(Product).filter(Product.company_id == company_id, Product.active).count(),
        "services": db.query(Service).filter(Service.company_id == company_id, Service.active).count(),
    }
