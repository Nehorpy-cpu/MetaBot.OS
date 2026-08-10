"""Handlers de los trabajos durables.

Cada uno hace UNA cosa y falla ruidosamente si no puede: el reintento con
backoff lo maneja la cola. Nada de tragar excepciones acá.
"""
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from . import channels, jobs, whatsapp
from .models import Appointment, Company, Conversation, Doctor

logger = logging.getLogger("metabot.jobs")

REMINDER_KIND = "appointment_reminder"
REMINDER_HOURS_BEFORE = 24
SUPERVISION_KIND = "supervision"
# Lo que se le manda al supervisor del turno, acotado: un catálogo entero no
# entra en una fila de la cola ni aporta al análisis.
MAX_PAYLOAD_CHARS = 4000


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


# --- Supervisión del CEO en modo shadow ---


def schedule_supervision(
    db: Session,
    company: Company,
    conversation: Conversation,
    trigger,
    *,
    cliente: str,
    respuesta: str,
    actions: list[dict],
    turno: int,
    degradacion: str = "",
) -> None:
    """Encola la revisión del turno para que corra FUERA de la espera del cliente.

    Sin esto, el modo shadow le agregaba ~36 segundos a una respuesta que —por
    definición— la revisión no puede cambiar: ya se envió.
    """
    recortadas: list[dict] = []
    usados = 0
    for a in actions[:6]:
        resultado = a.get("result") or {}
        crudo = json.dumps(resultado, ensure_ascii=False)
        if usados + len(crudo) > MAX_PAYLOAD_CHARS:
            # No entra entero: va solo qué herramienta corrió. Truncar el JSON
            # lo dejaría inválido, y el guardia de cifras leería basura; con el
            # resultado ausente el guardia se pone más estricto, que es el
            # lado seguro del error.
            recortadas.append({"tool": a.get("tool", ""), "result": {}})
            continue
        usados += len(crudo)
        recortadas.append({"tool": a.get("tool", ""), "result": resultado})
    jobs.enqueue(
        db,
        company_id=company.id,
        kind=SUPERVISION_KIND,
        run_at=datetime.now(timezone.utc).replace(tzinfo=None),
        payload={
            "conversation_id": conversation.id,
            "trigger": trigger.key,
            "cliente": cliente[:1500],
            "respuesta": respuesta[:1500],
            "actions": recortadas,
            "degradacion": degradacion,
        },
        # Único por turno: una reentrega no supervisa dos veces lo mismo.
        dedup_key=f"{SUPERVISION_KIND}:{conversation.id}:{trigger.key}:{turno}",
        max_attempts=2,  # es una mejora, no un dato que no se pueda perder
    )


@jobs.handler(SUPERVISION_KIND)
async def _run_supervision(db: Session, company_id: int, payload: dict) -> None:
    from . import supervisor  # import tardío: supervisor importa este módulo

    company = db.get(Company, company_id)
    conversation = db.get(Conversation, payload.get("conversation_id"))
    trigger = supervisor._POR_KEY.get(payload.get("trigger", ""))
    if not company or not conversation or not trigger:
        logger.info("supervisión: turno %s ya no existe", payload.get("conversation_id"))
        return
    if conversation.company_id != company_id:
        # No debería pasar; si pasa, es un cruce de tenants y se corta acá.
        logger.error("supervisión: conversación %s no es de la empresa %s",
                     conversation.id, company_id)
        return
    await supervisor.ejecutar(
        db, company, conversation, trigger,
        cliente=payload.get("cliente", ""),
        respuesta=payload.get("respuesta", ""),
        actions=payload.get("actions", []),
        modo="shadow",
        degradacion=payload.get("degradacion", ""),
    )
