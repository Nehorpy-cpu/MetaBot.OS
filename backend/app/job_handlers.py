"""Handlers de los trabajos durables.

Cada uno hace UNA cosa y falla ruidosamente si no puede: el reintento con
backoff lo maneja la cola. Nada de tragar excepciones acá.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from . import channels, jobs, whatsapp
from .models import Appointment, Company, Doctor

logger = logging.getLogger("metabot.jobs")

REMINDER_KIND = "appointment_reminder"
REMINDER_HOURS_BEFORE = 24


def reminder_dedup_key(appointment_id: int) -> str:
    return f"{REMINDER_KIND}:{appointment_id}"


def schedule_appointment_reminder(db: Session, appointment: Appointment) -> None:
    """Programa el recordatorio T-24h de una cita.

    Se llama al agendar (por el bot o desde el panel). Si la cita es en menos
    de 24 horas, no se programa: el cliente acaba de hablar con nosotros.
    """
    run_at = appointment.scheduled_at - timedelta(hours=REMINDER_HOURS_BEFORE)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if run_at <= now:
        return
    jobs.enqueue(
        db,
        company_id=appointment.company_id,
        kind=REMINDER_KIND,
        run_at=run_at,
        payload={"appointment_id": appointment.id},
        dedup_key=reminder_dedup_key(appointment.id),
    )


def cancel_appointment_reminder(db: Session, appointment_id: int) -> None:
    jobs.cancel(db, reminder_dedup_key(appointment_id))


@jobs.handler(REMINDER_KIND)
async def _send_appointment_reminder(db: Session, company_id: int, payload: dict) -> None:
    from .routers.medical import _reminder_text  # import tardío: evita ciclo

    appointment = db.get(Appointment, payload.get("appointment_id"))
    if not appointment or appointment.company_id != company_id:
        logger.info("recordatorio: la cita %s ya no existe", payload.get("appointment_id"))
        return
    if appointment.status == "cancelled":
        logger.info("recordatorio: cita %s cancelada, no se envía", appointment.id)
        return

    company = db.get(Company, company_id)
    doctor = db.get(Doctor, appointment.doctor_id)
    if not company or not doctor:
        return

    # Mensaje proactivo: solo por canales que lo admitan (Cloud API).
    if not channels.can_send_proactive(company.wa_mode):
        logger.info(
            "recordatorio de cita %s no enviado: el canal %s no admite proactivos",
            appointment.id, company.wa_mode,
        )
        return
    if not appointment.patient_phone:
        logger.info("recordatorio: cita %s sin teléfono", appointment.id)
        return

    result = await whatsapp.send_text(
        company.wa_phone_number_id, appointment.patient_phone,
        _reminder_text(appointment, doctor, company),
    )
    if result.get("error"):
        # Lanzar hace que la cola reintente con backoff en vez de perderlo.
        raise RuntimeError(result["error"])
    appointment.reminder_status = "sent" if result.get("sent") else "skipped"
    db.commit()
