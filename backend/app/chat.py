"""Motor conversacional del CX Bot.

Diseño:
- Memoria por contacto: el historial vive en la base (Conversation/Message).
- Contexto del negocio inyectado en el system prompt: fecha/hora local,
  doctores y horarios (vertical médica), glosario jopara del tenant.
- Herramientas (tool calling): el bot puede consultar la agenda, AGENDAR
  citas de verdad y escalar a un humano. Nunca inventa disponibilidad.
- Estilo humano: mensajes cortos, voseo, una pregunta por vez.
"""
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from .config import TIMEZONE
from .llm import chat_raw
from .models import Agent, Appointment, Company, Conversation, Doctor, GlossaryTerm, Message

HISTORY_LIMIT = 20
MAX_TOOL_ROUNDS = 4

# Algunos modelos escriben la llamada a herramienta como TEXTO en vez de usar
# tool_calls; eso jamás debe llegar al cliente. Se corta desde el primer tag.
_TOOL_TEXT_RE = re.compile(
    r"<\/?\s*(?:escalate_to_human|book_appointment|check_agenda|list_doctors|function|tool)[^>]*>.*",
    re.DOTALL | re.IGNORECASE,
)


def _sanitize_reply(text: str) -> str:
    return _TOOL_TEXT_RE.sub("", text).strip()

STYLE_RULES = """
REGLAS DE ESTILO (obligatorias):
- Escribí como una persona real de Paraguay por WhatsApp: mensajes cortos, cálidos y naturales.
- Usá voseo siempre (vos, tenés, querés). Jopara sutil solo cuando suene natural (ej. "¡Oĩma!", "na", "luego").
- Una sola pregunta por mensaje. Nada de listas largas ni formato de robot.
- Nunca digas que sos una IA salvo que te pregunten directamente; en ese caso decilo con naturalidad.
- Montos siempre en Guaraníes: ₲ 150.000 (puntos de miles).
- Si no sabés algo del negocio, NO lo inventes: decí que consultás y usá la herramienta de escalar a humano.
"""

MEDICAL_RULES = """
REGLAS MÉDICAS (obligatorias):
- JAMÁS des diagnósticos, dosis ni indicaciones médicas por chat. Ante síntomas, mostrá empatía y ofrecé turno.
- Si hay urgencia (dolor de pecho, dificultad para respirar, sangrado fuerte), indicá acudir a urgencias YA y escalá a humano.
- Para agendar usá SIEMPRE las herramientas: consultá la agenda real antes de ofrecer horarios. Nunca inventes disponibilidad.
- Confirmá nombre y teléfono del paciente antes de agendar.
- Si el horario pedido está ocupado o falla, NO agendes otro horario por tu cuenta: ofrecé 1 o 2 alternativas y esperá que el paciente elija.
- Solo confirmá una cita cuando la herramienta book_appointment devuelva ok=true, con la fecha y hora EXACTAS que devolvió.
"""


def _tools_for(company: Company) -> list[dict]:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "escalate_to_human",
                "description": "Marca la conversación para que la atienda una persona del equipo. Usar ante urgencias, reclamos, o cuando el cliente pide hablar con alguien o preguntás algo que no sabés.",
                "parameters": {
                    "type": "object",
                    "properties": {"reason": {"type": "string", "description": "Motivo breve"}},
                    "required": ["reason"],
                },
            },
        }
    ]
    if company.vertical == "medical":
        tools += [
            {
                "type": "function",
                "function": {
                    "name": "list_doctors",
                    "description": "Lista los doctores del centro con especialidad, horario e id.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "check_agenda",
                    "description": "Devuelve los horarios YA OCUPADOS de un doctor en una fecha. Usar antes de ofrecer un horario.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "doctor_id": {"type": "integer"},
                            "date": {"type": "string", "description": "Fecha YYYY-MM-DD"},
                        },
                        "required": ["doctor_id", "date"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "book_appointment",
                    "description": "Agenda una cita real. Solo usar tras confirmar doctor, fecha/hora, nombre y teléfono con el paciente.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "doctor_id": {"type": "integer"},
                            "patient_name": {"type": "string"},
                            "patient_phone": {"type": "string"},
                            "datetime_iso": {"type": "string", "description": "Fecha y hora YYYY-MM-DDTHH:MM"},
                            "notes": {"type": "string", "description": "Motivo de la consulta"},
                        },
                        "required": ["doctor_id", "patient_name", "datetime_iso"],
                    },
                },
            },
        ]
    return tools


def _execute_tool(
    name: str, args: dict, db: Session, company: Company, conversation: Conversation
) -> dict:
    if name == "escalate_to_human":
        conversation.status = "needs_human"
        db.commit()
        return {"ok": True, "message": "Conversación derivada al equipo humano."}

    if name == "list_doctors":
        doctors = db.query(Doctor).filter(Doctor.company_id == company.id).all()
        return {
            "doctors": [
                {"id": d.id, "name": d.name, "specialty": d.specialty, "schedule": d.schedule}
                for d in doctors
            ]
        }

    if name == "check_agenda":
        doctor = db.get(Doctor, args.get("doctor_id"))
        if not doctor or doctor.company_id != company.id:
            return {"error": "Doctor inexistente"}
        try:
            day = datetime.strptime(args["date"], "%Y-%m-%d")
        except (KeyError, ValueError):
            return {"error": "Fecha inválida, formato YYYY-MM-DD"}
        end = day.replace(hour=23, minute=59)
        busy = (
            db.query(Appointment)
            .filter(
                Appointment.doctor_id == doctor.id,
                Appointment.scheduled_at >= day,
                Appointment.scheduled_at <= end,
                Appointment.status.notin_(["cancelled"]),
            )
            .order_by(Appointment.scheduled_at)
            .all()
        )
        return {
            "doctor": doctor.name,
            "work_schedule": doctor.schedule or "no especificado",
            "busy_slots": [a.scheduled_at.strftime("%H:%M") for a in busy],
        }

    if name == "book_appointment":
        doctor = db.get(Doctor, args.get("doctor_id"))
        if not doctor or doctor.company_id != company.id:
            return {"error": "Doctor inexistente"}
        try:
            when = datetime.fromisoformat(args["datetime_iso"])
        except (KeyError, ValueError):
            return {"error": "Fecha/hora inválida, formato YYYY-MM-DDTHH:MM"}
        now_local = datetime.now(ZoneInfo(TIMEZONE)).replace(tzinfo=None)
        if when < now_local:
            return {
                "error": (
                    f"Esa fecha ya pasó ({when.strftime('%d/%m/%Y')}). "
                    f"Hoy es {now_local.strftime('%d/%m/%Y')}; usá el año correcto y reintentá."
                )
            }
        clash = (
            db.query(Appointment)
            .filter(
                Appointment.doctor_id == doctor.id,
                Appointment.scheduled_at == when,
                Appointment.status.notin_(["cancelled"]),
            )
            .first()
        )
        if clash:
            return {"error": f"Ese horario ya está ocupado ({when.strftime('%H:%M')}). Ofrecé otro."}
        # El teléfono debe ser real: si el modelo manda placeholders
        # ("null", "your phone number", etc.) usamos el de la conversación.
        phone = str(args.get("patient_phone") or "").strip()
        if sum(c.isdigit() for c in phone) < 6:
            phone = conversation.contact_phone
        appt = Appointment(
            company_id=company.id,
            doctor_id=doctor.id,
            patient_name=args["patient_name"],
            patient_phone=phone,
            scheduled_at=when,
            status="pending",
            notes=args.get("notes", ""),
        )
        db.add(appt)
        db.commit()
        return {
            "ok": True,
            "appointment_id": appt.id,
            "doctor": doctor.name,
            "when": when.strftime("%d/%m/%Y %H:%M"),
            "message": "Cita agendada como pendiente de confirmación.",
        }

    return {"error": f"Herramienta desconocida: {name}"}


def _build_system_prompt(db: Session, company: Company, agent: Agent) -> str:
    now = datetime.now(ZoneInfo(TIMEZONE))
    days = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    parts = [
        agent.system_prompt,
        STYLE_RULES,
        f"Negocio: {company.name} ({company.niche}).",
        f"Ahora es {days[now.weekday()]} {now.strftime('%d/%m/%Y %H:%M')} en Paraguay. "
        f"Toda cita se agenda en fecha futura, con año {now.year} o posterior.",
    ]
    if company.vertical == "medical":
        parts.append(MEDICAL_RULES)
        doctors = db.query(Doctor).filter(Doctor.company_id == company.id).all()
        if doctors:
            listing = "; ".join(
                f"{d.name} (id {d.id}, {d.specialty or 'general'}, horario {d.schedule or 's/d'})"
                for d in doctors
            )
            parts.append(f"Doctores del centro: {listing}.")
        else:
            parts.append("Aún no hay doctores cargados: no ofrezcas turnos, escalá a humano si piden cita.")
    terms = db.query(GlossaryTerm).filter(GlossaryTerm.company_id == company.id).all()
    if terms:
        glossary = "; ".join(f"'{t.heard}' significa '{t.meaning or t.corrected}'" for t in terms[:30])
        parts.append(f"Glosario local (guaraní/jopara): {glossary}.")
    return "\n\n".join(parts)


async def handle_incoming(
    db: Session,
    company: Company,
    contact_phone: str,
    text: str,
    contact_name: str = "",
    channel: str = "whatsapp",
) -> dict:
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.company_id == company.id,
            Conversation.contact_phone == contact_phone,
            Conversation.channel == channel,
        )
        .first()
    )
    if not conversation:
        conversation = Conversation(
            company_id=company.id,
            contact_phone=contact_phone,
            contact_name=contact_name,
            channel=channel,
        )
        db.add(conversation)
        db.flush()
    elif contact_name and not conversation.contact_name:
        conversation.contact_name = contact_name

    db.add(Message(conversation_id=conversation.id, direction="in", body=text))
    db.commit()

    agent = (
        db.query(Agent)
        .filter(Agent.company_id == company.id, Agent.slug == "cx", Agent.active)
        .first()
    )
    if not agent:
        return {
            "conversation_id": conversation.id,
            "reply": None,
            "status": conversation.status,
            "error": "El agente CX está pausado o no existe.",
        }

    history = (
        db.query(Message)
        .filter(Message.conversation_id == conversation.id)
        .order_by(Message.id.desc())
        .limit(HISTORY_LIMIT)
        .all()
    )
    messages: list[dict] = [{"role": "system", "content": _build_system_prompt(db, company, agent)}]
    for m in reversed(history):
        messages.append({"role": "user" if m.direction == "in" else "assistant", "content": m.body})

    tools = _tools_for(company)
    actions: list[dict] = []
    reply_text = ""
    booking_blocked = False  # tras un choque de agenda, no se agenda más en este turno
    for _ in range(MAX_TOOL_ROUNDS):
        assistant = await chat_raw(
            messages, tools=tools, model=agent.model, temperature=agent.temperature
        )
        tool_calls = assistant.get("tool_calls")
        if not tool_calls:
            reply_text = (assistant.get("content") or "").strip()
            break
        assistant.setdefault("role", "assistant")
        messages.append(assistant)
        for call in tool_calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            if name == "book_appointment" and booking_blocked:
                # Guardia determinística: el horario pedido falló; el bot debe
                # ofrecer alternativas y esperar la elección del paciente, no
                # elegir por él.
                result = {
                    "error": (
                        "NO agendes en este turno. El horario pedido no estaba "
                        "disponible: informale al paciente, ofrecé 1-2 "
                        "alternativas y esperá su confirmación."
                    )
                }
            else:
                result = _execute_tool(name, args, db, company, conversation)
                if name == "book_appointment" and "ocupado" in result.get("error", ""):
                    booking_blocked = True
            actions.append({"tool": name, "args": args, "result": result})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id", ""),
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
    else:
        # Se agotaron las rondas de herramientas: forzar una respuesta de
        # texto (sin tools) para que el cliente nunca quede sin contestación.
        messages.append(
            {
                "role": "user",
                "content": (
                    "[SISTEMA] Respondé ahora al cliente en texto, sin usar "
                    "herramientas, con la información que ya tenés."
                ),
            }
        )
        final = await chat_raw(messages, model=agent.model, temperature=agent.temperature)
        reply_text = (final.get("content") or "").strip()

    reply_text = _sanitize_reply(reply_text)
    if not reply_text:
        reply_text = "Perdoná, ¿me repetís eso último?"

    db.add(Message(conversation_id=conversation.id, direction="out", body=reply_text))
    db.commit()
    return {
        "conversation_id": conversation.id,
        "reply": reply_text,
        "status": conversation.status,
        "actions": actions,
    }
