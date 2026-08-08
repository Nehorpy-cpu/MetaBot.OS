"""Módulo médico: doctores, citas y resumen diario por doctor."""
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Appointment, Company, Doctor

router = APIRouter(tags=["medical"])

VALID_STATUSES = {"pending", "confirmed", "cancelled", "attended", "no_show"}
STATUS_ES = {
    "pending": "Pendiente",
    "confirmed": "Confirmado",
    "cancelled": "Cancelado",
    "attended": "Atendido",
    "no_show": "No asistió",
}


def _get_company(company_id: int, db: Session) -> Company:
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Empresa no encontrada")
    return company


# --- Doctores ---

class DoctorIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    specialty: str = ""
    schedule: str = ""
    phone: str = ""
    email: str = ""


class DoctorOut(DoctorIn):
    id: int

    model_config = {"from_attributes": True}


@router.post("/companies/{company_id}/doctors", response_model=DoctorOut, status_code=201)
def create_doctor(company_id: int, payload: DoctorIn, db: Session = Depends(get_db)):
    _get_company(company_id, db)
    doctor = Doctor(company_id=company_id, **payload.model_dump())
    db.add(doctor)
    db.commit()
    db.refresh(doctor)
    return doctor


@router.get("/companies/{company_id}/doctors", response_model=list[DoctorOut])
def list_doctors(company_id: int, db: Session = Depends(get_db)):
    _get_company(company_id, db)
    return db.query(Doctor).filter(Doctor.company_id == company_id).order_by(Doctor.id).all()


@router.delete("/companies/{company_id}/doctors/{doctor_id}", status_code=204)
def delete_doctor(company_id: int, doctor_id: int, db: Session = Depends(get_db)):
    doctor = db.get(Doctor, doctor_id)
    if not doctor or doctor.company_id != company_id:
        raise HTTPException(404, "Doctor no encontrado")
    if db.query(Appointment).filter(Appointment.doctor_id == doctor_id).count():
        raise HTTPException(409, "El doctor tiene citas registradas; no se puede eliminar")
    db.delete(doctor)
    db.commit()


# --- Citas ---

class AppointmentIn(BaseModel):
    doctor_id: int
    patient_name: str = Field(min_length=1, max_length=200)
    patient_phone: str = ""
    scheduled_at: datetime
    notes: str = ""


class AppointmentOut(AppointmentIn):
    id: int
    status: str

    model_config = {"from_attributes": True}


class AppointmentStatusUpdate(BaseModel):
    status: str


@router.post("/companies/{company_id}/appointments", response_model=AppointmentOut, status_code=201)
def create_appointment(company_id: int, payload: AppointmentIn, db: Session = Depends(get_db)):
    _get_company(company_id, db)
    doctor = db.get(Doctor, payload.doctor_id)
    if not doctor or doctor.company_id != company_id:
        raise HTTPException(404, "Doctor no encontrado en esta empresa")
    appt = Appointment(company_id=company_id, **payload.model_dump())
    db.add(appt)
    db.commit()
    db.refresh(appt)
    return appt


@router.get("/companies/{company_id}/appointments", response_model=list[AppointmentOut])
def list_appointments(
    company_id: int,
    doctor_id: int | None = None,
    on_date: date | None = None,
    db: Session = Depends(get_db),
):
    _get_company(company_id, db)
    q = db.query(Appointment).filter(Appointment.company_id == company_id)
    if doctor_id is not None:
        q = q.filter(Appointment.doctor_id == doctor_id)
    if on_date is not None:
        start = datetime(on_date.year, on_date.month, on_date.day)
        q = q.filter(Appointment.scheduled_at >= start, Appointment.scheduled_at < start.replace(hour=23, minute=59, second=59))
    return q.order_by(Appointment.scheduled_at).all()


@router.patch("/companies/{company_id}/appointments/{appt_id}", response_model=AppointmentOut)
def update_appointment_status(
    company_id: int, appt_id: int, payload: AppointmentStatusUpdate, db: Session = Depends(get_db)
):
    if payload.status not in VALID_STATUSES:
        raise HTTPException(422, f"Estado inválido. Válidos: {sorted(VALID_STATUSES)}")
    appt = db.get(Appointment, appt_id)
    if not appt or appt.company_id != company_id:
        raise HTTPException(404, "Cita no encontrada")
    appt.status = payload.status
    db.commit()
    db.refresh(appt)
    return appt


# --- Resumen diario por doctor (plantilla WhatsApp) ---

@router.get("/companies/{company_id}/doctors/{doctor_id}/daily-summary")
def daily_summary(
    company_id: int, doctor_id: int, on_date: date | None = None, db: Session = Depends(get_db)
):
    """Plantilla de fin de día SOLO con las citas del doctor indicado."""
    _get_company(company_id, db)
    doctor = db.get(Doctor, doctor_id)
    if not doctor or doctor.company_id != company_id:
        raise HTTPException(404, "Doctor no encontrado")
    target = on_date or date.today()
    start = datetime(target.year, target.month, target.day)
    end = start.replace(hour=23, minute=59, second=59)
    appts = (
        db.query(Appointment)
        .filter(
            Appointment.company_id == company_id,
            Appointment.doctor_id == doctor_id,
            Appointment.scheduled_at >= start,
            Appointment.scheduled_at <= end,
            Appointment.status != "cancelled",
        )
        .order_by(Appointment.scheduled_at)
        .all()
    )
    lines = [
        f"📋 *AGENDA MÉDICA DIARIA - {doctor.name.upper()}*",
        f"📅 Fecha: {target.strftime('%d/%m/%Y')}",
        "━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    for i, a in enumerate(appts, 1):
        lines.append(
            f"{i}. *Hora:* {a.scheduled_at.strftime('%H:%M')} | *Paciente:* {a.patient_name}"
        )
        lines.append(f"   📞 Tel: {a.patient_phone} | *Motivo:* {a.notes} | {STATUS_ES.get(a.status, a.status)}")
        lines.append("")
    if not appts:
        lines.append("Sin citas para esta fecha.")
    lines.append("_Enviado automáticamente por MetaBot.OS_")
    return {"doctor": doctor.name, "date": target.isoformat(), "count": len(appts), "text": "\n".join(lines)}
