"""Módulo médico: doctores, citas, recordatorios, iCalendar y resúmenes."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import channels, job_handlers, outbound, registry, whatsapp
from ..config import TIMEZONE
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
    # Verificación contra el padrón público de especialistas certificados.
    verification: str = "unverified"
    cert_number: str = ""
    cert_specialty: str = ""
    cert_expires_at: date | None = None

    model_config = {"from_attributes": True}


@router.post("/companies/{company_id}/doctors/verify")
def verify_doctors(company_id: int, db: Session = Depends(get_db)):
    """Contrasta los profesionales de la empresa con el padrón del CPM.

    Devuelve cuántos están certificados y vigentes, a cuántos se les venció y
    cuántos no figuran. `not_found` no significa "trucho": el padrón es solo
    de médicos especialistas, así que una bioquímica o un veterinario no van a
    estar ahí.
    """
    _get_company(company_id, db)
    resumen = registry.verificar_empresa(db, company_id)
    return {
        **resumen,
        "nota": (
            "El padrón cubre médicos especialistas certificados. Que un "
            "profesional no figure puede significar que no es médico "
            "especialista, no que su matrícula sea inválida."
        ),
    }


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
    job_handlers.schedule_appointment_reminder(db, appt)
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
    if payload.status == "cancelled":
        job_handlers.cancel_appointment_reminder(db, appt.id)
    db.refresh(appt)
    return appt


# --- Recordatorios de citas (día siguiente por defecto) ---

def _reminder_text(appt: Appointment, doctor: Doctor, company: Company) -> str:
    lines = [
        f"¡Hola {appt.patient_name}! 😊 Te escribimos de {company.name} para recordarte tu cita de mañana:",
        "",
        f"🗓 {appt.scheduled_at.strftime('%d/%m/%Y')} a las {appt.scheduled_at.strftime('%H:%M')} hs",
        f"👩‍⚕️ Te atiende: {doctor.name}" + (f" ({doctor.specialty})" if doctor.specialty else ""),
    ]
    if company.address:
        lines.append(f"📍 Dirección: {company.address}")
    if appt.notes:
        lines.append(f"📝 Motivo: {appt.notes}")
    lines += [
        "",
        "Si no podés venir, avisanos por acá nomás y lo reprogramamos sin problema. ¡Te esperamos! 🙌",
    ]
    return "\n".join(lines)


@router.get("/companies/{company_id}/reminders")
def list_reminders(company_id: int, on_date: date | None = None, db: Session = Depends(get_db)):
    """Recordatorios para las citas de la fecha dada (mañana por defecto)."""
    company = _get_company(company_id, db)
    target = on_date or (date.today() + timedelta(days=1))
    start = datetime(target.year, target.month, target.day)
    end = start.replace(hour=23, minute=59, second=59)
    appts = (
        db.query(Appointment)
        .filter(
            Appointment.company_id == company_id,
            Appointment.scheduled_at >= start,
            Appointment.scheduled_at <= end,
            Appointment.status.in_(["pending", "confirmed"]),
        )
        .order_by(Appointment.scheduled_at)
        .all()
    )
    reminders = []
    for a in appts:
        doctor = db.get(Doctor, a.doctor_id)
        reminders.append(
            {
                "appointment_id": a.id,
                "patient_name": a.patient_name,
                "phone": a.patient_phone,
                "text": _reminder_text(a, doctor, company),
            }
        )
    return {"date": target.isoformat(), "count": len(reminders), "reminders": reminders}


@router.post("/companies/{company_id}/reminders/send")
async def send_reminders(company_id: int, on_date: date | None = None, db: Session = Depends(get_db)):
    """Envía los recordatorios por WhatsApp (dry-run si no hay token).

    Un recordatorio es un mensaje PROACTIVO (le escribimos primero al
    cliente). Solo se envía por canales que declaran esa capability: por el
    conector de comunidad (QR) no se manda, porque es justamente lo que hace
    que WhatsApp restrinja el número.
    """
    company = _get_company(company_id, db)
    data = list_reminders(company_id, on_date, db)
    profile = channels.profile_for(company.wa_mode)
    if not profile.can(channels.Capability.SEND_PROACTIVE):
        return {
            "date": data["date"],
            "skipped": True,
            "reason": (
                f"El canal actual ({profile.name}) no admite mensajes proactivos. "
                "Los recordatorios quedan listos para enviarse a mano o al activar Cloud API."
            ),
            "results": [{**r, "send": {"skipped": True}} for r in data["reminders"]],
        }
    results = []
    for r in data["reminders"]:
        if not r["phone"]:
            results.append({**r, "send": {"error": "sin teléfono"}})
            continue
        # Por el canal que corresponda a la empresa, no siempre por Meta.
        send = await outbound.enviar(db, company_id, r["phone"], r["text"])
        results.append({**r, "send": send})
    return {"date": data["date"], "results": results}


# --- Export iCalendar (Google Calendar) por doctor ---

@router.get("/companies/{company_id}/doctors/{doctor_id}/calendar.ics")
def doctor_calendar_ics(company_id: int, doctor_id: int, db: Session = Depends(get_db)):
    """Agenda del doctor en formato iCalendar, importable en Google Calendar."""
    company = _get_company(company_id, db)
    doctor = db.get(Doctor, doctor_id)
    if not doctor or doctor.company_id != company_id:
        raise HTTPException(404, "Doctor no encontrado")
    appts = (
        db.query(Appointment)
        .filter(
            Appointment.doctor_id == doctor_id,
            Appointment.status.in_(["pending", "confirmed"]),
        )
        .order_by(Appointment.scheduled_at)
        .all()
    )
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//MetaBot.OS//Agenda Medica//ES",
        f"X-WR-CALNAME:{doctor.name} - {company.name}",
        f"X-WR-TIMEZONE:{TIMEZONE}",
    ]
    for a in appts:
        start_s = a.scheduled_at.strftime("%Y%m%dT%H%M%S")
        end_s = (a.scheduled_at + timedelta(minutes=30)).strftime("%Y%m%dT%H%M%S")
        summary = f"Cita: {a.patient_name}" + (f" — {a.notes}" if a.notes else "")
        lines += [
            "BEGIN:VEVENT",
            f"UID:metabot-appt-{a.id}@metabot.os",
            f"DTSTART;TZID={TIMEZONE}:{start_s}",
            f"DTEND;TZID={TIMEZONE}:{end_s}",
            f"SUMMARY:{summary}",
            f"DESCRIPTION:Tel paciente: {a.patient_phone or 's/d'} | Estado: {STATUS_ES.get(a.status, a.status)}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return Response(
        content="\r\n".join(lines),
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="agenda-{doctor_id}.ics"'},
    )


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
