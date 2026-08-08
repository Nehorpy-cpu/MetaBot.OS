"""Estadísticas operativas del tenant: la materia prima del Analista Quant.

Todo se calcula acá de forma determinística (SQL); el LLM solo redacta.
Así los números del informe nunca son inventados.
"""
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .models import Appointment, Company, Conversation, Doctor, Message


def compute_stats(db: Session, company: Company, days: int = 7) -> dict:
    since = datetime.now() - timedelta(days=days)

    appts = (
        db.query(Appointment)
        .filter(Appointment.company_id == company.id, Appointment.created_at >= since)
        .all()
    )
    by_status = Counter(a.status for a in appts)
    finished = by_status.get("attended", 0) + by_status.get("no_show", 0)
    no_show_rate = round(by_status.get("no_show", 0) / finished * 100, 1) if finished else 0.0

    by_doctor: Counter = Counter()
    by_hour: Counter = Counter()
    for a in appts:
        doctor = db.get(Doctor, a.doctor_id)
        by_doctor[doctor.name if doctor else f"doctor {a.doctor_id}"] += 1
        by_hour[a.scheduled_at.strftime("%H:00")] += 1

    convs = (
        db.query(Conversation)
        .filter(Conversation.company_id == company.id, Conversation.created_at >= since)
        .all()
    )
    conv_ids = [c.id for c in convs]
    msgs_in = (
        db.query(Message)
        .filter(Message.conversation_id.in_(conv_ids), Message.direction == "in")
        .count()
        if conv_ids
        else 0
    )
    escalated = sum(1 for c in convs if c.status == "needs_human")

    return {
        "period_days": days,
        "appointments": {
            "total": len(appts),
            "by_status": dict(by_status),
            "no_show_rate_pct": no_show_rate,
            "by_doctor": dict(by_doctor.most_common(10)),
            "peak_hours": dict(by_hour.most_common(5)),
        },
        "conversations": {
            "new": len(convs),
            "incoming_messages": msgs_in,
            "escalated_to_human": escalated,
        },
    }
