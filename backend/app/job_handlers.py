"""Handlers de los trabajos durables.

Cada uno hace UNA cosa y falla ruidosamente si no puede: el reintento con
backoff lo maneja la cola. Nada de tragar excepciones acá.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from . import channels, jobs, whatsapp
from .config import TIMEZONE
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


def local_a_utc(local_ingenuo: datetime) -> datetime:
    """Convierte una hora de la agenda (hora de Paraguay) a UTC.

    La agenda se guarda en hora local: es lo que el paciente dice, lo que el
    panel muestra y lo que sale en el mensaje. La cola de trabajos, en cambio,
    compara `run_at` contra `datetime.now(timezone.utc)`.

    Sin esta conversión los dos relojes se mezclan y el recordatorio sale 3
    horas ANTES de lo previsto: el aviso de una cita de las 06:00 le llega al
    paciente a las 03:00 de la madrugada.
    """
    return (
        local_ingenuo.replace(tzinfo=ZoneInfo(TIMEZONE))
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )


def schedule_appointment_reminder(db: Session, appointment: Appointment) -> None:
    """Programa el recordatorio T-24h de una cita.

    Se llama al agendar (por el bot o desde el panel). Si la cita es en menos
    de 24 horas, no se programa: el cliente acaba de hablar con nosotros.
    """
    # El resumen del profesional va PRIMERO y fuera del early return: son dos
    # cosas independientes. Con el orden anterior, un turno tomado a menos de
    # 24 horas cortaba en el `return` del recordatorio y el doctor nunca se
    # enteraba de ese paciente —justo el caso donde más falta hace, porque no
    # tuvo tiempo de mirar la agenda.
    #
    # El `dedup_key` por (doctor, día) hace que el quinto paciente del martes
    # no genere un quinto mensaje: se programa una vez y se arma con la agenda
    # del momento en que sale.
    doctor = db.get(Doctor, appointment.doctor_id)
    if doctor and doctor.company_id == appointment.company_id:
        schedule_previsita(db, doctor, appointment.scheduled_at.date())

    # scheduled_at está en hora de Paraguay; la cola razona en UTC.
    run_at = local_a_utc(appointment.scheduled_at - timedelta(hours=REMINDER_HOURS_BEFORE))
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

    # Enruta según el canal de la empresa: Cloud API o bridge de Baileys.
    # Llamar directo a la Cloud API mandaría el aviso por el canal equivocado
    # a toda empresa conectada por QR.
    from . import outbound

    result = await outbound.enviar(
        db, company_id, appointment.patient_phone,
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


# --- Evaluación de un prompt candidato (etapa 5) ---

PROMPT_EVAL_KIND = "prompt_eval"


def schedule_prompt_eval(db: Session, company_id: int, agent_id: int,
                         version_id: int, suggestion_id: int | None = None) -> None:
    """Encola la evaluación de un candidato.

    Va a la cola y no al request porque el conjunto dorado tarda minutos: cada
    caso corre el motor de verdad, con sus ~60 s de herramientas. Un HTTP de
    cinco minutos lo corta cualquier proxy.
    """
    jobs.enqueue(
        db,
        company_id=company_id,
        kind=PROMPT_EVAL_KIND,
        run_at=datetime.now(timezone.utc).replace(tzinfo=None),
        payload={"agent_id": agent_id, "version_id": version_id,
                 "suggestion_id": suggestion_id},
        dedup_key=f"{PROMPT_EVAL_KIND}:{version_id}",
        max_attempts=2,
    )


@jobs.handler(PROMPT_EVAL_KIND)
async def _run_prompt_eval(db: Session, company_id: int, payload: dict) -> None:
    from . import evaluator
    from .models import Agent, AgentPromptVersion, PromptSuggestion

    company = db.get(Company, company_id)
    agent = db.get(Agent, payload.get("agent_id"))
    version = db.get(AgentPromptVersion, payload.get("version_id"))
    if not company or not agent or not version or agent.company_id != company_id:
        logger.info("eval de prompt: el candidato ya no existe")
        return

    corrida = await evaluator.correr(db, company, agent, version)
    sugerencia = (
        db.get(PromptSuggestion, payload["suggestion_id"])
        if payload.get("suggestion_id") else None
    )

    if corrida.verdict != "pass":
        # El candidato queda registrado con su evidencia. No se activa nada:
        # que un cambio de prompt necesite evidencia es justamente el punto.
        if sugerencia:
            sugerencia.status = "blocked_by_eval"
        db.commit()
        logger.warning("candidato v%s rechazado por el evaluador: %s",
                       version.version, corrida.reason)
        return

    resultado = evaluator.activar(db, agent, version.id)
    if sugerencia:
        sugerencia.status = "applied" if resultado["ok"] else "blocked_by_eval"
    db.commit()
    logger.info("candidato v%s: %s", version.version, resultado)


# --- Mensaje entrante de WhatsApp (Cloud API) ---

INBOUND_KIND = "whatsapp_inbound"


def schedule_inbound_message(db: Session, company_id: int, *, telefono: str,
                             texto: str, nombre: str = "", external_id: str = "",
                             phone_number_id: str = "") -> None:
    """Encola un mensaje entrante para procesarlo fuera del webhook.

    El dedup_key es el id del mensaje de Meta: si Meta reenvía el webhook —lo
    hace cuando no recibe el 200 a tiempo—, el mensaje no se procesa dos veces
    ni se le responde dos veces al cliente.
    """
    jobs.enqueue(
        db,
        company_id=company_id,
        kind=INBOUND_KIND,
        run_at=datetime.now(timezone.utc).replace(tzinfo=None),
        payload={
            "telefono": telefono, "texto": texto, "nombre": nombre,
            "external_id": external_id, "phone_number_id": phone_number_id,
        },
        dedup_key=f"{INBOUND_KIND}:{company_id}:{external_id}" if external_id else None,
        max_attempts=3,
    )


@jobs.handler(INBOUND_KIND)
async def _procesar_entrante(db: Session, company_id: int, payload: dict) -> None:
    from . import chat as chat_engine
    from . import whatsapp
    from .llm import LLMError

    company = db.get(Company, company_id)
    if not company:
        return
    try:
        salida = await chat_engine.handle_incoming(
            db, company, payload["telefono"], payload["texto"],
            contact_name=payload.get("nombre", ""),
            external_id=payload.get("external_id", ""),
        )
    except LLMError as exc:
        # Reintentable: el proveedor puede volver. Lanzar deja el trabajo en la
        # cola con backoff en vez de perder el mensaje del cliente.
        raise RuntimeError(f"LLM no disponible: {exc}")

    if salida.get("duplicate"):
        logger.info("mensaje %s ya procesado", payload.get("external_id"))
        return

    pnid = payload.get("phone_number_id", "") or company.wa_phone_number_id
    destino = payload["telefono"].lstrip("+")
    for item in (salida.get("media") or [])[:5]:
        await whatsapp.send_image(pnid, destino, item.get("path", ""), item.get("caption", ""))
    respuesta = salida.get("reply")
    if respuesta:
        resultado = await whatsapp.send_text(pnid, destino, respuesta)
        if resultado.get("error"):
            raise RuntimeError(resultado["error"])


# --- Resumen pre-visita para el profesional ---

PREVISITA_KIND = "previsita"
# A las 20:00 del día anterior: el doctor todavía está despierto y le queda
# tiempo de mirar la agenda antes de la mañana siguiente.
PREVISITA_HORA = 20


def previsita_dedup_key(doctor_id: int, dia: str) -> str:
    return f"{PREVISITA_KIND}:{doctor_id}:{dia}"


def schedule_previsita(db: Session, doctor: Doctor, dia) -> None:
    """Programa el envío del resumen la noche anterior.

    No se manda si el profesional no tiene teléfono cargado: son datos
    clínicos y no van a un número que nadie verificó.
    """
    if not doctor.phone or sum(c.isdigit() for c in doctor.phone) < 6:
        return
    salida_local = datetime(dia.year, dia.month, dia.day, PREVISITA_HORA) - timedelta(days=1)
    run_at = local_a_utc(salida_local)
    if run_at <= datetime.now(timezone.utc).replace(tzinfo=None):
        return
    jobs.enqueue(
        db,
        company_id=doctor.company_id,
        kind=PREVISITA_KIND,
        run_at=run_at,
        payload={"doctor_id": doctor.id, "dia": dia.isoformat()},
        dedup_key=previsita_dedup_key(doctor.id, dia.isoformat()),
    )


@jobs.handler(PREVISITA_KIND)
async def _send_previsita(db: Session, company_id: int, payload: dict) -> None:
    from datetime import date as _date

    from . import outbound, previsita

    company = db.get(Company, company_id)
    doctor = db.get(Doctor, payload["doctor_id"])
    # El doctor puede haberse dado de baja entre que se programó y ahora, o
    # ser de otra empresa si alguien tocó el payload: las dos cosas se chequean.
    if not company or not doctor or doctor.company_id != company_id:
        return
    if not doctor.phone or sum(c.isdigit() for c in doctor.phone) < 6:
        return

    resumen = previsita.armar(db, company, doctor, _date.fromisoformat(payload["dia"]))
    if not resumen["total"]:
        # Sin pacientes no se manda nada: un mensaje diario que casi siempre
        # dice "no tenés nada" es un mensaje que se deja de leer.
        return
    salida = await outbound.enviar(db, company_id, doctor.phone, resumen["texto"])
    if salida.get("error"):
        raise RuntimeError(salida["error"])
