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
import time
import unicodedata
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DEFAULT_SLOT_MIN = 30  # duración por defecto de una cita, para detectar solapes

from sqlalchemy.orm import Session

from . import job_handlers, packs, supervisor
from .config import TIMEZONE
from .llm import chat_raw
from .models import (
    Agent,
    AgentRun,
    Appointment,
    Company,
    Conversation,
    Doctor,
    DoctorService,
    GlossaryTerm,
    Insurer,
    Message,
    Prescription,
    PrescriptionItem,
    Product,
    Service,
    ServiceCoverage,
)


def _fmt_gs(amount: int) -> str:
    return f"₲ {amount:,}".replace(",", ".") if amount else "consultar"

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

# Catálogo de herramientas del enjambre. Qué recibe cada bot lo decide su
# Business Pack (packs.py), no un `if vertical == "medical"`.
TOOL_SPECS: dict[str, dict] = {
    "search_catalog": {
        "type": "function",
        "function": {
            "name": "search_catalog",
            "description": (
                "Busca productos REALES del catálogo con precio exacto y foto real. "
                "Filtrá por lo que pide el cliente: presupuesto máximo, para quién es, "
                "perfil buscado. Las fotos de lo que devuelva se envían solas al cliente."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Qué busca: perfil, notas, marca, tipo (ej. 'dulce floral', 'Dior')"},
                    "budget_max": {"type": "integer", "description": "Presupuesto máximo en Guaraníes (ej. 350000)"},
                    "budget_min": {"type": "integer", "description": "Mínimo en Guaraníes (opcional)"},
                    "gender": {"type": "string", "description": "Para quién: 'femenino', 'masculino' o 'unisex'"},
                    "avoid": {"type": "string", "description": "Qué NO quiere (ej. 'muy pesado')"},
                    "in_stock_only": {"type": "boolean", "description": "Solo con stock (default true)"},
                    "max_results": {"type": "integer", "description": "Máx resultados (default 3)"},
                },
                "required": ["query"],
            },
        },
    },
    "list_services": {
        "type": "function",
        "function": {
            "name": "list_services",
            "description": (
                "Busca servicios y estudios del negocio: precio exacto en Guaraníes, duración, "
                "qué profesional lo atiende y LA PREPARACIÓN PREVIA que el paciente debe hacer "
                "(ayuno, vejiga llena, traer estudios anteriores). Usar SIEMPRE antes de dar un "
                "precio y antes de agendar un estudio. Pasá en `query` lo que pidió el paciente."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Qué busca el paciente, ej. 'ecografía abdominal', 'hemograma', 'extracción de muela'"},
                    "category": {"type": "string", "description": "Filtrar por categoría (opcional)"},
                },
            },
        },
    },
    "check_coverage": {
        "type": "function",
        "function": {
            "name": "check_coverage",
            "description": (
                "Cuánto le sale un estudio o consulta al paciente CON SU SEGURO, según los "
                "convenios que este negocio tiene cargados. Usar siempre antes de dar un "
                "precio a alguien que menciona su seguro o prepaga."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {"type": "string", "description": "Nombre del estudio o consulta"},
                    "insurer": {"type": "string", "description": "Seguro o prepaga que dijo el paciente"},
                },
                "required": ["service", "insurer"],
            },
        },
    },
    "get_prescription": {
        "type": "function",
        "function": {
            "name": "get_prescription",
            "description": (
                "Le manda al paciente su última receta TAL CUAL la cargó el doctor. "
                "Usar cuando el paciente pide su receta o pregunta qué le recetaron. "
                "La receta se adjunta sola: vos NO la repetís ni la resumís."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "list_doctors": {
        "type": "function",
        "function": {
            "name": "list_doctors",
            "description": "Lista los profesionales del negocio con especialidad, horario e id.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "check_agenda": {
        "type": "function",
        "function": {
            "name": "check_agenda",
            "description": "Devuelve los horarios YA OCUPADOS de un profesional en una fecha. Usar antes de ofrecer un horario.",
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
    "book_appointment": {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": "Agenda una cita real. Solo usar tras confirmar profesional, fecha/hora, nombre y teléfono con el cliente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doctor_id": {"type": "integer"},
                    "patient_name": {"type": "string"},
                    "patient_phone": {"type": "string"},
                    "datetime_iso": {"type": "string", "description": "Fecha y hora YYYY-MM-DDTHH:MM"},
                    "notes": {"type": "string", "description": "Motivo"},
                },
                "required": ["doctor_id", "patient_name", "datetime_iso"],
            },
        },
    },
    "escalate_to_human": {
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
    },
}


def _tools_for(company: Company) -> list[dict]:
    """Herramientas del bot según los Business Packs activos del tenant."""
    keys = {"escalate_to_human"} | packs.tools_for(company)
    return [TOOL_SPECS[k] for k in TOOL_SPECS if k in keys]


def _normalizar(texto: str) -> str:
    """Minúsculas sin tildes ni ñ, para comparar lo que la gente escribe.

    En WhatsApp nadie pone tildes: "Seguro Nanduti" tiene que encontrar
    "Seguro Ñandutí". Sin esto el sistema le dice al paciente que no hay
    convenio mientras se lo lista entre los disponibles.
    """
    limpio = unicodedata.normalize("NFD", (texto or "").lower())
    return "".join(c for c in limpio if unicodedata.category(c) != "Mn")


def _receta_verbatim(receta, doctor, items: list, company: Company) -> str:
    """Arma el texto de la receta con los campos de la base, sin modelo.

    Esto es lo que le llega al paciente. Que lo arme `format` y no un LLM es
    la única garantía real de que nadie parafrasee una dosis: un prompt que
    dice "no cambies nada" es una intención, esto es un hecho.
    """
    lineas = [
        f"*Receta — {company.name}*",
        f"Paciente: {receta.patient_name}",
        f"Profesional: {doctor.name if doctor else 'no registrado'}"
        + (f" ({doctor.specialty})" if doctor and doctor.specialty else ""),
        f"Fecha: {receta.issued_at.strftime('%d/%m/%Y')}",
    ]
    if receta.diagnosis:
        lineas.append(f"Diagnóstico: {receta.diagnosis}")
    lineas.append("")
    for n, it in enumerate(items, 1):
        pauta = it.frequency or (f"cada {it.every_hours} horas" if it.every_hours else "")
        detalle = " · ".join(x for x in (it.dose, it.route, pauta) if x)
        if it.duration_days:
            detalle += f" · por {it.duration_days} días"
        lineas.append(f"{n}. *{it.medication}* — {detalle}")
        if it.instructions:
            lineas.append(f"   {it.instructions}")
    if receta.indications:
        lineas.extend(["", f"Indicaciones: {receta.indications}"])
    lineas.extend([
        "",
        "Esta receta es la que cargó tu profesional, copiada tal cual. "
        "Ante cualquier duda o si algo te cae mal, hablá con el consultorio: "
        "por acá no podemos cambiar ni interpretar una indicación médica.",
    ])
    return "\n".join(lineas)


def _execute_tool(
    name: str, args: dict, db: Session, company: Company, conversation: Conversation,
    media_out: list | None = None, verbatim_out: list | None = None,
) -> dict:
    if name == "search_catalog":
        # Vendedor consultivo: el LLM traduce el pedido del cliente a
        # criterios; el CATÁLOGO confirma. Los filtros duros (presupuesto,
        # stock, género) los aplica SQL, no el modelo.
        query = str(args.get("query", "")).strip().lower()
        avoid = str(args.get("avoid", "")).strip().lower()
        gender = str(args.get("gender", "")).strip().lower()
        limit = min(int(args.get("max_results") or 3), 5)
        in_stock_only = args.get("in_stock_only", True)

        def _amount(key: str) -> int | None:
            raw = args.get(key)
            try:
                value = int(raw)
            except (TypeError, ValueError):
                return None
            return value if value > 0 else None

        budget_max = _amount("budget_max")
        budget_min = _amount("budget_min")

        q = db.query(Product).filter(Product.company_id == company.id, Product.active)
        if in_stock_only:
            q = q.filter(Product.in_stock.is_(True))
        if budget_max:
            # price_gs == 0 significa "consultar": no se filtra por precio
            q = q.filter((Product.price_gs <= budget_max) | (Product.price_gs == 0))
        if budget_min:
            q = q.filter((Product.price_gs >= budget_min) | (Product.price_gs == 0))
        if gender in ("femenino", "masculino", "unisex"):
            q = q.filter((Product.gender.ilike(f"%{gender}%")) | (Product.gender == ""))
        candidates = q.all()

        words = [w for w in re.split(r"\W+", query) if len(w) > 2]
        avoid_words = [w for w in re.split(r"\W+", avoid) if len(w) > 3]

        def score(p: Product) -> int:
            hay = f"{p.name} {p.brand} {p.category} {p.gender} {p.notes}".lower()
            points = sum(2 if w in f"{p.name} {p.brand}".lower() else 1 for w in words if w in hay)
            points -= sum(3 for w in avoid_words if w in hay)  # lo que NO quiere pesa
            return points

        matched = sorted((p for p in candidates if score(p) > 0), key=score, reverse=True)[:limit]
        # Sin coincidencias de texto pero sí dentro de presupuesto: se ofrece
        # lo que hay, en vez de dejar al cliente sin respuesta.
        ranked = matched or candidates[:limit]

        out = []
        for p in ranked:
            out.append(
                {
                    "name": p.name,
                    "brand": p.brand,
                    "price": _fmt_gs(p.price_gs),
                    "price_gs": p.price_gs,
                    "in_stock": p.in_stock,
                    "notes": p.notes[:300],
                    "photo_attached": bool(p.image_path),
                }
            )
            if p.image_path and media_out is not None:
                media_out.append({"path": p.image_path, "caption": f"{p.name} — {_fmt_gs(p.price_gs)}"})
        if out:
            return {"products": out, "exact_match": bool(matched)}
        note = "Sin coincidencias en el catálogo."
        if budget_max:
            cheapest = (
                db.query(Product)
                .filter(Product.company_id == company.id, Product.active, Product.price_gs > 0)
                .order_by(Product.price_gs)
                .first()
            )
            if cheapest:
                note = (
                    f"No hay nada hasta {_fmt_gs(budget_max)}. Lo más accesible del "
                    f"catálogo es {cheapest.name} a {_fmt_gs(cheapest.price_gs)}. "
                    "Decíselo con honestidad al cliente."
                )
        return {"products": [], "note": note}
    if name == "check_coverage":
        # El convenio lo cargó ESTA empresa: no hay base compartida de
        # aseguradoras, porque eso sería inventar acuerdos que no existen.
        pedido = _normalizar(args.get("insurer", "")).strip()
        convenios = (
            db.query(Insurer)
            .filter(Insurer.company_id == company.id, Insurer.active)
            .all()
        )
        # Se compara sin tildes ni ñ, y también contra el plan: el paciente
        # escribe "Nanduti Plan Oro" y el convenio se llama "Seguro Ñandutí".
        insurer = None
        if pedido:
            for i in convenios:
                nombre = _normalizar(i.name)
                completo = _normalizar(f"{i.name} {i.plan}").strip()
                plan = _normalizar(i.plan)
                if nombre in pedido or pedido in completo:
                    # Si el paciente nombró un plan, tiene que coincidir: los
                    # planes de una misma prepaga cubren distinto.
                    if not plan or plan in pedido or not any(
                        _normalizar(o.plan) in pedido for o in convenios if _normalizar(o.name) == nombre
                    ):
                        insurer = i
                        break
        if not insurer:
            disponibles = [
                f"{i.name} {i.plan}".strip()
                for i in db.query(Insurer)
                .filter(Insurer.company_id == company.id, Insurer.active)
                .limit(15)
                .all()
            ]
            return {
                "covered": False,
                "note": (
                    "No tenemos convenio con ese seguro. Decíselo con honestidad "
                    "y pasale el precio particular."
                ),
                "convenios_disponibles": disponibles,
            }

        buscado = _normalizar(args.get("service", "")).strip()
        candidatos = (
            db.query(Service)
            .filter(Service.company_id == company.id, Service.active)
            .all()
        )
        service = next((s for s in candidatos if buscado and buscado in _normalizar(s.name)), None)
        if not service and buscado:
            # Segunda pasada: que todas las palabras aparezcan, en cualquier
            # orden. "eco abdominal" encuentra "Ecografía abdominal total".
            palabras = [w for w in re.split(r"\W+", buscado) if len(w) > 3]
            service = next(
                (s for s in candidatos if palabras and all(w in _normalizar(s.name) for w in palabras)),
                None,
            )
        if not service:
            return {"error": f"No encontré '{args.get('service')}' en el catálogo. Usá list_services."}

        cobertura, copago, excluido = insurer.coverage_pct, insurer.copay_gs, False
        override = (
            db.query(ServiceCoverage)
            .filter(
                ServiceCoverage.company_id == company.id,
                ServiceCoverage.insurer_id == insurer.id,
                ServiceCoverage.service_id == service.id,
            )
            .first()
        )
        if override:
            cobertura, copago, excluido = override.coverage_pct, override.copay_gs, override.excluded

        if excluido:
            return {
                "service": service.name, "insurer": f"{insurer.name} {insurer.plan}".strip(),
                "covered": False, "patient_pays": _fmt_gs(service.price_gs),
                "note": "Este estudio NO está cubierto por ese convenio: se abona particular.",
            }
        # El cálculo lo hace el servidor, no el modelo: un porcentaje mal
        # calculado en un precio es una discusión en la caja.
        a_pagar = max(0, round(service.price_gs * (100 - cobertura) / 100) + copago)
        return {
            "service": service.name,
            "insurer": f"{insurer.name} {insurer.plan}".strip(),
            "covered": True,
            "list_price": _fmt_gs(service.price_gs),
            "coverage_pct": cobertura,
            "patient_pays": _fmt_gs(a_pagar) if a_pagar else "sin costo",
            "prep": service.prep,
        }

    if name == "get_prescription":
        # Se busca por el teléfono DE ESTA conversación, nunca por un nombre
        # que cualquiera podría escribir: es un dato de salud.
        receta = (
            db.query(Prescription)
            .filter(
                Prescription.company_id == company.id,
                Prescription.patient_phone == conversation.contact_phone,
                Prescription.status == "active",
            )
            .order_by(Prescription.issued_at.desc())
            .first()
        )
        if not receta:
            return {
                "found": False,
                "note": (
                    "No hay receta cargada a nombre de este número. Ofrecé "
                    "consultarlo con el consultorio; NO inventes ninguna indicación."
                ),
            }
        doctor = db.get(Doctor, receta.doctor_id)
        items = (
            db.query(PrescriptionItem)
            .filter(PrescriptionItem.prescription_id == receta.id)
            .order_by(PrescriptionItem.id)
            .all()
        )
        if verbatim_out is not None:
            verbatim_out.append(_receta_verbatim(receta, doctor, items, company))
        return {
            "found": True,
            "sent_verbatim": True,
            "note": (
                "La receta ya se le adjuntó al paciente palabra por palabra. "
                "NO la repitas, NO la resumas y NO la interpretes: solo avisale "
                "que se la mandaste y ofrecé ayudarlo con otra cosa."
            ),
        }

    if name == "escalate_to_human":
        conversation.status = "needs_human"
        db.commit()
        return {"ok": True, "message": "Conversación derivada al equipo humano."}

    if name == "list_services":
        # Un sanatorio tiene ~300 estudios: devolverlos todos no le sirve al
        # modelo ni entra en su contexto. Se busca por texto y se acota.
        q = db.query(Service).filter(Service.company_id == company.id, Service.active)
        category = str(args.get("category") or "").strip()
        if category:
            q = q.filter(Service.category.ilike(f"%{category}%"))
        candidatos = q.order_by(Service.category, Service.name).all()
        buscado = _normalizar(args.get("query") or "").strip()
        if buscado:
            # El filtro va en Python y no en SQL porque hay que ignorar tildes
            # y ñ, y ni SQLite ni PostgreSQL lo hacen igual con ilike. Son unos
            # cientos de filas: no justifica una extensión de la base.
            palabras = [w for w in re.split(r"\W+", buscado) if len(w) > 3]
            if palabras:
                candidatos = [
                    s for s in candidatos
                    if all(
                        w in _normalizar(f"{s.name} {s.category} {s.specialty}")
                        for w in palabras
                    )
                ]
        total = len(candidatos)
        services = candidatos[:12]
        if not services:
            return {
                "services": [],
                "note": (
                    "No hay ningún servicio con ese criterio. Preguntale al paciente "
                    "cómo se llama el estudio o quién se lo pidió; NO inventes uno."
                ),
            }

        # Los profesionales de todos los servicios en UNA consulta: antes se
        # hacía una por servicio (300 consultas para listar un catálogo).
        ids = [s.id for s in services]
        links = (
            db.query(DoctorService, Doctor)
            .join(Doctor, Doctor.id == DoctorService.doctor_id)
            .filter(DoctorService.service_id.in_(ids), Doctor.company_id == company.id)
            .all()
        )
        por_servicio: dict[int, list[str]] = {}
        for link, doctor in links:
            por_servicio.setdefault(link.service_id, []).append(doctor.name)

        out = []
        for s in services:
            fila = {
                "name": s.name,
                "category": s.category,
                "price": _fmt_gs(s.price_gs),
                "duration_min": s.duration_min,
                "attended_by": por_servicio.get(s.id) or ["cualquier profesional del equipo"],
            }
            if s.specialty:
                fila["specialty"] = s.specialty
            if s.prep:
                # Lo más importante para el paciente: qué tiene que hacer ANTES
                # de venir. Si no se lo decimos, viaja al vicio.
                fila["preparacion"] = s.prep
            if s.sample:
                fila["muestra"] = s.sample
            if s.description:
                fila["description"] = s.description[:200]
            out.append(fila)
        resultado = {"services": out}
        if total > len(out):
            resultado["note"] = (
                f"Hay {total} que coinciden; te muestro {len(out)}. Si el paciente "
                "busca otra cosa, afiná la búsqueda."
            )
        return resultado

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
        # Choque por SOLAPAMIENTO (citas de 30 min), no solo igualdad exacta:
        # una cita nueva [when, when+30) no debe pisar a otra existente.
        slot = timedelta(minutes=DEFAULT_SLOT_MIN)
        window_lo = when - slot
        window_hi = when + slot
        clash = (
            db.query(Appointment)
            .filter(
                Appointment.doctor_id == doctor.id,
                Appointment.status.notin_(["cancelled"]),
                Appointment.scheduled_at > window_lo,
                Appointment.scheduled_at < window_hi,
            )
            .first()
        )
        if clash:
            return {
                "error": (
                    f"Ese horario se solapa con otra cita ({clash.scheduled_at.strftime('%H:%M')}). "
                    "Ofrecé un horario que no choque."
                )
            }
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
        # El recordatorio T-24h queda programado de forma durable: sobrevive
        # a un reinicio del servidor y se reintenta si el envío falla.
        job_handlers.schedule_appointment_reminder(db, appt)
        return {
            "ok": True,
            "appointment_id": appt.id,
            "doctor": doctor.name,
            "when": when.strftime("%d/%m/%Y %H:%M"),
            "message": "Cita agendada como pendiente de confirmación.",
        }

    return {"error": f"Herramienta desconocida: {name}"}


def _build_system_prompt(
    db: Session, company: Company, agent: Agent, directive: str = ""
) -> str:
    now = datetime.now(ZoneInfo(TIMEZONE))
    days = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    parts = [
        agent.system_prompt,
        STYLE_RULES,
        f"Negocio: {company.name} ({company.niche}).",
        f"Ahora es {days[now.weekday()]} {now.strftime('%d/%m/%Y %H:%M')} en Paraguay. "
        f"Toda cita se agenda en fecha futura, con año {now.year} o posterior.",
    ]
    # Anclaje al catálogo real: el bot solo vende lo que el negocio vende.
    try:
        profile = json.loads(company.profile or "{}")
    except json.JSONDecodeError:
        profile = {}
    products = profile.get("products") or []
    if company.industry or products:
        parts.append(
            f"Rubro del negocio: {company.industry or company.niche}. "
            + (f"Catálogo/servicios reales: {', '.join(str(p) for p in products[:20])}. " if products else "")
            + "REGLA DURA: solo ofrecés lo que este negocio realmente vende. Si el cliente "
            "pide algo de OTRO rubro (ej. ropa si vendés perfumes), aclaralo con amabilidad "
            "y redirigí al catálogo real. Nunca sigas la corriente ofreciendo productos inexistentes."
        )
    services = (
        db.query(Service).filter(Service.company_id == company.id, Service.active).limit(25).all()
    )
    if services:
        listing = "; ".join(f"{s.name} ({_fmt_gs(s.price_gs)})" for s in services)
        parts.append(
            f"Servicios/estudios cargados: {listing}. Antes de confirmar un precio usá la "
            "herramienta list_services (tiene el dato exacto y qué profesional atiende cada uno). "
            "NUNCA inventes servicios ni precios que no estén en esa lista."
        )
    parts.extend(packs.rules_for(company))
    if "book_appointment" in {t["function"]["name"] for t in _tools_for(company)}:
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
    if directive:
        # Instrucción que dejó el supervisor tras revisar el turno anterior.
        # Vale solo para este turno: se consume al usarla.
        parts.append(f"NOTA DEL SUPERVISOR para este mensaje: {directive}")
    return "\n\n".join(parts)


async def handle_incoming(
    db: Session,
    company: Company,
    contact_phone: str,
    text: str,
    contact_name: str = "",
    channel: str = "whatsapp",
    external_id: str = "",
) -> dict:
    """Procesa un mensaje entrante.

    Idempotente por `external_id`: WhatsApp reentrega mensajes al reconectar
    y una reentrega no debe generar otra respuesta ni otra cita.
    """
    started = time.monotonic()
    if external_id:
        ya_procesado = (
            db.query(Message)
            .filter(Message.company_id == company.id, Message.external_id == external_id)
            .first()
        )
        if ya_procesado:
            # Ya se respondió a este mensaje: no se vuelve a procesar.
            previa = (
                db.query(Message)
                .filter(
                    Message.conversation_id == ya_procesado.conversation_id,
                    Message.direction == "out",
                    Message.id > ya_procesado.id,
                )
                .order_by(Message.id)
                .first()
            )
            return {
                "conversation_id": ya_procesado.conversation_id,
                "reply": previa.body if previa else None,
                "status": "duplicate",
                "duplicate": True,
                "actions": [],
                "media": [],
            }
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

    db.add(Message(company_id=company.id, conversation_id=conversation.id, direction="in",
                   body=text, external_id=external_id or None))
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
    # Directiva que dejó el supervisor en el turno anterior: se usa una vez.
    directive = conversation.pending_directive or ""
    if directive:
        conversation.pending_directive = ""
    messages: list[dict] = [
        {"role": "system", "content": _build_system_prompt(db, company, agent, directive)}
    ]
    for m in reversed(history):
        messages.append({"role": "user" if m.direction == "in" else "assistant", "content": m.body})

    tools = _tools_for(company)
    actions: list[dict] = []
    media: list[dict] = []  # fotos reales de catálogo a enviar al cliente
    # Bloques que salen TAL CUAL de la base (recetas). No pasan por el modelo
    # ni por el supervisor: se anexan a la respuesta ya terminada.
    verbatim: list[str] = []
    reply_text = ""
    rondas_agotadas = False
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
                result = _execute_tool(
                    name, args, db, company, conversation,
                    media_out=media, verbatim_out=verbatim,
                )
                if name == "book_appointment" and "solapa" in result.get("error", ""):
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
        rondas_agotadas = True
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

    # El CEO revisa DESPUÉS, y solo si el resultado del CX muestra que el
    # turno salió mal. Con supervision="off" (el default) esto no cuesta nada.
    revision = await supervisor.review(
        db, company, conversation,
        cliente=text,
        respuesta=reply_text,
        actions=actions,
        turnos_cliente=sum(1 for m in history if m.direction == "in"),
        rondas_agotadas=rondas_agotadas,
    )
    if revision.get("reply"):
        reply_text = revision["reply"]
    if revision.get("escalate"):
        conversation.status = "needs_human"

    # La receta se anexa DESPUÉS de la supervisión, a propósito: ni el CX ni el
    # CEO pueden reescribirla. Lo que el doctor cargó es lo que el paciente lee.
    if verbatim:
        reply_text = "\n\n".join([reply_text, *verbatim])

    db.add(Message(company_id=company.id, conversation_id=conversation.id, direction="out", body=reply_text))
    tools_used = [a["tool"] for a in actions]
    db.add(AgentRun(
        company_id=company.id,
        agent_slug="cx",
        conversation_id=conversation.id,
        model=agent.model,
        question=text[:2000],
        answer=reply_text[:2000],
        tools_used=",".join(tools_used)[:300],
        latency_ms=int((time.monotonic() - started) * 1000),
        tool_rounds=len(actions),
        escalated="escalate_to_human" in tools_used or bool(revision.get("escalate")),
        booked=any(a["tool"] == "book_appointment" and a["result"].get("ok") for a in actions),
    ))
    db.commit()
    return {
        "conversation_id": conversation.id,
        "reply": reply_text,
        "status": conversation.status,
        "actions": actions,
        "media": media[:5],
        "supervision": revision.get("trigger") or None,
    }
