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
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger("metabot.chat")

DEFAULT_SLOT_MIN = 30  # duración por defecto de una cita, para detectar solapes

from sqlalchemy.orm import Session

from . import agenda, aranceles, job_handlers, packs, supervisor
from .config import TIMEZONE
from .textos import formato_gs, normalizar
from .llm import cadena_para, chat_raw
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
    """Para el bot, 0 no es "₲ 0": es que hay que preguntar."""
    return formato_gs(amount) if amount else "consultar"

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
- Escribí como una persona real de Paraguay por WhatsApp: mensajes breves, cálidos
  y naturales. Voseo SIEMPRE, sin excepción: "preferís" y no "prefieres",
  "querés" y no "quieres", "podés" y no "puedes", "tenés" y no "tienes",
  "decime" y no "dime", "vos" y no "tú". Se cuela un "prefieres" en la tercera
  respuesta y de golpe sonás a call center de afuera.
- CORTESÍA: tratás con pacientes y clientes, muchas veces preocupados. Nada de
  "¿qué onda?", "¡na!", "dale loco" ni muletillas de amigo. Cálido y respetuoso a
  la vez: cercano no es confianzudo.
- ENTENDÉS el guaraní y el jopara si el cliente los usa, pero RESPONDÉS en
  castellano. Nada de "¡Oĩma!", "na", "luego" ni saludos en guaraní: no todo el
  mundo lo habla y en un contexto de salud puede sonar desprolijo.
- LEÉ TODO el mensaje antes de contestar y respondé lo que realmente te pidieron.
  Si el cliente hace dos preguntas, contestá las dos. Si te dice que NO sabe algo,
  no se lo vuelvas a preguntar: ayudalo a averiguarlo.
- CONTESTÁ LO QUE PREGUNTARON, NI MÁS NI MENOS. Una consulta de una palabra
  ("¿Cardiología?") se responde corto —sí, tenemos— y con UNA pregunta para
  saber qué necesita. No vuelques precios, duraciones, preparaciones ni listas
  de profesionales que nadie pidió: la herramienta te da muchos datos, eso no
  significa que haya que recitarlos. Cada dato de más entierra tu pregunta y el
  cliente no sabe qué contestar.
- Si el cliente NO sabe qué necesita, ahí sí ofrecé opciones: hasta 5, en lista
  numerada, solo con el nombre —el precio y el detalle van cuando elija una.
- Cuando el cliente no sepa el nombre de lo que necesita pero sí la zona del
  cuerpo, el síntoma o la especialidad, BUSCÁ en el catálogo por eso y ofrecele
  hasta 5 opciones, empezando por las más comunes. Preguntar "¿cómo se llama el
  estudio?" a quien acaba de decir que no lo recuerda no lo ayuda en nada.
- Una idea por mensaje. Cuando ofrezcas opciones, una lista corta y numerada está
  bien; lo que no va son párrafos largos ni formato de robot.
- Nunca digas que sos una IA salvo que te pregunten directamente; en ese caso
  decilo con naturalidad.
- Montos siempre en Guaraníes: ₲ 150.000 (puntos de miles).
- Si no sabés algo del negocio, NO lo inventes: decí que lo consultás y usá la
  herramienta de escalar a humano.
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
    "my_appointments": {
        "type": "function",
        "function": {
            "name": "my_appointments",
            "description": (
                "Los turnos que YA tiene este paciente con nosotros, con fecha, hora, "
                "profesional y si están confirmados. Usar cuando pregunte por SU turno "
                "('¿cuándo tengo?', '¿a qué hora era?', 'quiero cambiar mi turno'). "
                "No confundir con check_agenda, que es la agenda del doctor."
            ),
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
            "description": (
                "Agenda una cita real. Solo usar tras confirmar con el cliente el "
                "profesional, la fecha/hora y el NOMBRE DEL PACIENTE. El teléfono "
                "NO hace falta pedirlo: se toma solo del WhatsApp desde el que "
                "te escriben."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "doctor_id": {"type": "integer"},
                    "patient_name": {
                        "type": "string",
                        "description": "Nombre real del PACIENTE que va a ser atendido, tal como lo dijo el cliente. Nunca un relleno tipo 'el paciente' o 'Usuario'.",
                    },
                    "patient_phone": {
                        "type": "string",
                        "description": "Solo si el paciente es otra persona Y te dieron su teléfono. Si no, dejalo vacío: se usa el de esta conversación.",
                    },
                    "para_otra_persona": {
                        "type": "boolean",
                        "description": "true si quien escribe agenda para otro (su hijo, su madre, su pareja).",
                    },
                    "datetime_iso": {"type": "string", "description": "Fecha y hora YYYY-MM-DDTHH:MM"},
                    "service_id": {
                        "type": "integer",
                        "description": "El service_id que devolvió list_services. Pasalo SIEMPRE que sepas qué se va a hacer: define cuánto dura el turno.",
                    },
                    "seguro": {
                        "type": "string",
                        "description": "El seguro o prepaga que dijo el paciente, TAL CUAL lo dijo. Vacío si va como particular o si no lo mencionó. No lo inventes ni lo supongas.",
                    },
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


# Confirmación de cita: se resuelve en el servidor, no interpretando el
# mensaje con un modelo. Solo dispara con mensajes CORTOS e inequívocos —un
# "sí, pero quiero cambiar la hora" no entra acá y lo maneja el bot.
_MAX_CHARS_CONFIRMACION = 28
_AFIRMATIVO = re.compile(
    r"^\W*(si|sii+|sisi|dale|ok|oka?y|listo|confirmo|confirmado|confirmar|perfecto|"
    r"de acuerdo|correcto|asi es|va|buenisimo|barbaro|joya|obvio|claro|"
    r"si confirmo|si dale|todo bien|me sirve|me viene bien)\b[\s\.\!]*$"
)
_NEGATIVO = re.compile(
    r"^\W*(no|nop|nel|no puedo|no me sirve|no me viene|cancelar|cancelo|"
    r"cancela|anular|anulo|no voy|no podre|no podre ir|otro dia|otro horario|"
    r"no gracias)\b[\s\.\!]*$"
)


# Baja de avisos proactivos. Es la palabra convenida del canal: se atiende
# sin modelo, sin ambigüedad y sin excusas.
_ES_BAJA = re.compile(
    r"^\W*(stop|baja|darme de baja|dar de baja|no quiero mas mensajes|"
    r"no me escriban mas|cancelar avisos|basta|unsubscribe)\b[\s\.\!]*$"
)
_ES_ALTA = re.compile(r"^\W*(alta|si quiero recordatorios|activar avisos)\b[\s\.\!]*$")


def _es_afirmativo(texto: str) -> bool:
    limpio = _normalizar(texto).strip()
    return len(limpio) <= _MAX_CHARS_CONFIRMACION and bool(_AFIRMATIVO.match(limpio))


def _es_negativo(texto: str) -> bool:
    limpio = _normalizar(texto).strip()
    return len(limpio) <= _MAX_CHARS_CONFIRMACION and bool(_NEGATIVO.match(limpio))


def _cita_por_confirmar(db: Session, company: Company, conversation: Conversation):
    """La próxima cita de este paciente que todavía espera confirmación."""
    ahora = datetime.now(ZoneInfo(TIMEZONE)).replace(tzinfo=None)
    return (
        db.query(Appointment)
        .filter(
            Appointment.company_id == company.id,
            Appointment.patient_phone == conversation.contact_phone,
            Appointment.status == "pending",
            Appointment.scheduled_at > ahora,
        )
        .order_by(Appointment.scheduled_at)
        .first()
    )


def _texto_confirmacion(appt: Appointment, doctor, company: Company) -> str:
    """Confirmación armada desde la base. La fecha no la escribe un modelo."""
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    cuando = appt.scheduled_at
    partes = [
        "¡Listo! Tu cita quedó *confirmada*. 🙌",
        "",
        f"📅 {dias[cuando.weekday()]} {cuando.strftime('%d/%m/%Y')} a las {cuando.strftime('%H:%M')}",
    ]
    if doctor:
        partes.append(f"👩‍⚕️ {doctor.name}" + (f" — {doctor.specialty}" if doctor.specialty else ""))
    if company.address:
        partes.append(f"📍 {company.address}")
    partes.extend(["", "Si te surge algo, escribinos y lo reprogramamos."])
    return "\n".join(partes)


# El paciente dice "corazón"; el catálogo dice "Cardiología". Sin este puente
# la búsqueda no encuentra nada y el bot termina preguntándole al paciente el
# nombre técnico del estudio que acaba de decir que no recuerda.
SINONIMOS_BUSQUEDA: dict[str, tuple[str, ...]] = {
    "corazon": ("cardiolog", "cardiac", "electrocardio", "ecocardio", "holter", "ergometr"),
    "cardiaco": ("cardiolog", "electrocardio", "ecocardio"),
    "presion": ("cardiolog", "mapa", "presion"),
    "pulmon": ("neumolog", "torax", "espirometr"),
    "respiracion": ("neumolog", "espirometr", "torax"),
    "hueso": ("traumatolog", "radiograf", "densitometr"),
    "huesos": ("traumatolog", "radiograf", "densitometr"),
    "columna": ("traumatolog", "radiograf", "resonancia"),
    "rodilla": ("traumatolog", "radiograf", "resonancia"),
    "cabeza": ("neurolog", "tomograf", "resonancia", "electroencefalo"),
    "cerebro": ("neurolog", "tomograf", "resonancia", "electroencefalo"),
    "estomago": ("gastroenterolog", "endoscop", "ecografia abdominal"),
    "digestivo": ("gastroenterolog", "endoscop", "colonoscop"),
    "higado": ("hepatograma", "gastroenterolog", "ecografia abdominal"),
    "rinon": ("nefrolog", "urea", "creatinina", "ecografia renal"),
    "rinones": ("nefrolog", "creatinina", "ecografia renal"),
    "vista": ("oftalmolog", "campimetr"),
    "ojos": ("oftalmolog", "campimetr"),
    "oido": ("otorrinolaringolog", "audiometr"),
    "oidos": ("otorrinolaringolog", "audiometr"),
    "garganta": ("otorrinolaringolog",),
    "piel": ("dermatolog",),
    "tiroides": ("tiroide", "tsh", "endocrinolog"),
    "azucar": ("glicemia", "glucosa", "hemoglobina glicosilada", "diabet"),
    "diabetes": ("glicemia", "hemoglobina glicosilada", "diabetolog"),
    "colesterol": ("lipidico", "colesterol", "triglicerid"),
    "embarazo": ("obstetric", "ginecolog", "ecografia obstetrica"),
    "prostata": ("urolog", "psa"),
    "sangre": ("hemograma", "laboratorio", "hematolog"),
    "dientes": ("odontolog", "dental"),
    "muela": ("odontolog", "extraccion", "endodoncia"),
}


def _expandir_busqueda(texto: str) -> list[str]:
    """Traduce lo que dice el paciente a términos del catálogo.

    Devuelve la lista de términos alternativos a probar. Vacía si no hay
    sinónimo conocido: entonces se busca tal cual lo escribió.
    """
    normalizado = _normalizar(texto)
    alternativas: list[str] = []
    for palabra, terminos in SINONIMOS_BUSQUEDA.items():
        if palabra in normalizado:
            alternativas.extend(terminos)
    return alternativas


# Vive en `textos.py`: el mismo criterio con el que el bot busca un convenio
# tiene que usar la planilla de honorarios cuando lo busca de nuevo.
_normalizar = normalizar


# Formatos de teléfono que se usan en Paraguay: 021 214-400, 0981 123456,
# +595981123456, (021) 214400. Se busca cualquier cosa con forma de teléfono.
_TELEFONO_RE = re.compile(r"(?:\+?595|0)\s*\(?\d{2,4}\)?[\s.-]*\d{3}[\s.-]*\d{3,4}")


# Rellenos que devuelve el modelo cuando agenda sin haber preguntado el
# nombre. Una cita a nombre de "el paciente" no le sirve a nadie en recepción.
_NOMBRES_DE_RELLENO = {
    "", "n/a", "na", "null", "none", "undefined", "-", "--", "sin nombre",
    "paciente", "el paciente", "la paciente", "nombre", "nombre del paciente",
    "usuario", "cliente", "el cliente", "la clienta", "desconocido",
    "patient", "patient name", "user", "customer", "unknown", "anonimo",
    "tu nombre", "su nombre", "mi nombre", "xxx", "test", "prueba",
}


def _nombre_de_persona(valor) -> str:
    """Devuelve el nombre si parece de una persona; si no, cadena vacía."""
    nombre = " ".join(str(valor or "").split())
    if len(nombre) < 3 or _normalizar(nombre) in _NOMBRES_DE_RELLENO:
        return ""
    # Al menos una letra: "12345" o "..." no son nombres.
    if not any(c.isalpha() for c in nombre):
        return ""
    return nombre[:200]


# El paciente dice cómo se llama en medio de una frase cualquiera ("Dr. Benítez
# está bien el martes a las 10, Marco Garcete me llamo"). Resolverlo en el
# servidor sale gratis y no depende de que el modelo se acuerde de guardarlo.
_DECLARA_NOMBRE = re.compile(
    r"(?:me\s+llamo|mi\s+nombre\s+es|soy)\s+(?P<nombre>[^\d,.;:!?\n]{3,60})"
    r"|(?P<nombre2>[^\d,.;:!?\n]{3,60})\s+(?:me\s+llamo|es\s+mi\s+nombre)",
    re.IGNORECASE,
)
# Palabras que descartan la captura: "soy alérgico", "soy de Luque". Se
# comparan SIN TILDES porque el paciente escribe "alérgico" y "alergico" por
# igual, y guardar "alérgico" como nombre termina en "¡Hola alérgico!".
_NO_ES_NOMBRE = re.compile(
    r"^(alergic|diabetic|hipertens|asmatic|celiac|paciente|de\s|el\s|la\s|"
    r"un\s|una\s|nuevo|nueva|del\s|para\s|mayor|menor|jubilad|"
    r"medic|doctor|enfermer|estudiante|embarazad)",
    re.IGNORECASE,
)


def _nombre_declarado(texto: str) -> str:
    """Extrae el nombre que la persona dijo, si lo dijo de forma inequívoca."""
    m = _DECLARA_NOMBRE.search(texto or "")
    if not m:
        return ""
    crudo = (m.group("nombre") or m.group("nombre2") or "").strip(" .,-")
    if not crudo or _NO_ES_NOMBRE.match(_normalizar(crudo)):
        return ""
    # Un nombre son una a cuatro palabras; más que eso es una frase.
    palabras = crudo.split()
    if not 1 <= len(palabras) <= 4:
        return ""
    return _nombre_de_persona(crudo)


def _solo_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto or "")


def _sanear_telefonos_inventados(db: Session, company: Company, conversation: Conversation,
                                 reply: str) -> tuple[str, list[str]]:
    """Saca de la respuesta cualquier teléfono que no exista en los datos.

    Observado en producción: el sanatorio no tiene teléfono cargado y el bot le
    dio a un paciente "021 214-400" —inventado— con un emoji de teléfono que lo
    hacía ver oficial. Un paciente llamaría a un desconocido.

    El prompt ya dice que no invente, pero los modelos igual inventan cuando
    les falta un dato. Esto lo verifica del lado del servidor, que es donde
    tienen que vivir las reglas que importan.
    """
    candidatos = _TELEFONO_RE.findall(reply or "")
    if not candidatos:
        return reply, []

    permitidos = {_solo_digitos(company.phone), _solo_digitos(conversation.contact_phone)}
    for d in db.query(Doctor).filter(Doctor.company_id == company.id).all():
        permitidos.add(_solo_digitos(d.phone))
    # También lo que el propio cliente escribió en el hilo: si él dio su
    # número, repetírselo para confirmar es legítimo.
    for m in (
        db.query(Message)
        .filter(Message.conversation_id == conversation.id, Message.direction == "in")
        .order_by(Message.id.desc()).limit(10).all()
    ):
        for t_ in _TELEFONO_RE.findall(m.body or ""):
            permitidos.add(_solo_digitos(t_))
    permitidos.discard("")

    inventados = []
    for encontrado in candidatos:
        digitos = _solo_digitos(encontrado)
        # Coincide si alguno de los permitidos termina igual (con o sin código
        # de país, con o sin el 0 inicial).
        if any(p.endswith(digitos[-8:]) or digitos.endswith(p[-8:]) for p in permitidos if len(p) >= 8):
            continue
        inventados.append(encontrado)
        reply = reply.replace(encontrado, "").replace("📞", "").replace("  ", " ")
    return reply.strip(), inventados


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
        # Buscar el convenio y calcular lo que paga el paciente son las DOS
        # cosas que la planilla de honorarios vuelve a hacer sobre la misma
        # atención. Están en `aranceles.py` para que den el mismo número: si
        # no, la diferencia no aparece como error sino como una discusión en
        # la caja o una planilla que la aseguradora rechaza.
        insurer = aranceles.buscar_convenio(db, company.id, args.get("insurer", ""))
        if not insurer:
            return {
                "covered": False,
                "note": (
                    "No tenemos convenio con ese seguro. Decíselo con honestidad "
                    "y pasale el precio particular."
                ),
                "convenios_disponibles": aranceles.convenios_activos(db, company.id),
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

        # El cálculo lo hace el servidor, no el modelo: un porcentaje mal
        # calculado en un precio es una discusión en la caja.
        cobertura = aranceles.cobertura_de(db, company.id, insurer, service)
        montos = aranceles.repartir(service.price_gs, cobertura)
        if cobertura.excluido:
            return {
                "service": service.name, "insurer": f"{insurer.name} {insurer.plan}".strip(),
                "covered": False, "patient_pays": _fmt_gs(montos.paga_el_paciente_gs),
                "note": "Este estudio NO está cubierto por ese convenio: se abona particular.",
            }
        respuesta = {
            "service": service.name,
            "insurer": f"{insurer.name} {insurer.plan}".strip(),
            "covered": True,
            "list_price": _fmt_gs(service.price_gs),
            "patient_pays": (
                _fmt_gs(montos.paga_el_paciente_gs)
                if montos.paga_el_paciente_gs else "sin costo"
            ),
            "prep": service.prep,
        }
        # Con un arancel cargado a mano NO hay porcentaje, y mandarle uno al
        # modelo es pedirle que invente. Se vio en producción: el número que
        # le dio al paciente era el correcto —lo calcula el servidor— pero lo
        # explicó con "tu plan cubre el 70%", que no era ni el porcentaje
        # guardado ni la proporción real. Un paciente que repite eso en la
        # caja arma una discusión por algo que nadie le dijo.
        if montos.arancel_manual:
            respuesta["cubre_el_seguro"] = _fmt_gs(montos.paga_el_seguro_gs)
            respuesta["note"] = (
                "El convenio paga un MONTO FIJO por esta práctica, no un porcentaje. "
                "Decí cuánto abona el paciente y nada más: no hables de porcentajes "
                "de cobertura porque acá no existen."
            )
        else:
            respuesta["coverage_pct"] = cobertura.cobertura_pct
        return respuesta

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
        crudo = args.get("query") or ""
        buscado = _normalizar(crudo).strip()
        if buscado:
            # El filtro va en Python y no en SQL porque hay que ignorar tildes
            # y ñ, y ni SQLite ni PostgreSQL lo hacen igual con ilike. Son unos
            # cientos de filas: no justifica una extensión de la base.
            def _texto(s):
                return _normalizar(f"{s.name} {s.category} {s.specialty}")

            palabras = [w for w in re.split(r"\W+", buscado) if len(w) > 3]
            exactos = [s for s in candidatos if all(w in _texto(s) for w in palabras)] if palabras else candidatos

            # Si el paciente habló de una parte del cuerpo o un síntoma, se
            # traduce a los términos del catálogo. "corazón" no aparece en
            # ningún nombre de estudio, pero "Cardiología" sí.
            sinonimos = _expandir_busqueda(crudo)
            por_sinonimo = (
                [s for s in candidatos if any(term in _texto(s) for term in sinonimos)]
                if sinonimos else []
            )
            vistos = {s.id for s in exactos}
            candidatos = exactos + [s for s in por_sinonimo if s.id not in vistos]
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
                # El id va para que al agendar se pueda pasar `service_id` y
                # el turno ocupe su duración real: sin esto una ecografía de
                # 45 minutos y una consulta de 20 bloqueaban lo mismo.
                "service_id": s.id,
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

    if name == "my_appointments":
        # El paciente preguntó "¿cuándo es mi turno?" y el bot le contestó con
        # los horarios OCUPADOS del doctor, diciéndole que su propio turno
        # estaba ocupado. Eran dos preguntas distintas sin dos herramientas.
        ahora = datetime.now(ZoneInfo(TIMEZONE)).replace(tzinfo=None)
        dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        propias = (
            db.query(Appointment)
            .filter(
                Appointment.company_id == company.id,
                Appointment.patient_phone == conversation.contact_phone,
                Appointment.scheduled_at >= ahora - timedelta(hours=2),
                Appointment.status.notin_(["cancelled"]),
            )
            .order_by(Appointment.scheduled_at)
            .limit(10)
            .all()
        )
        if not propias:
            return {
                "appointments": [],
                "note": "Este paciente no tiene ningún turno futuro con nosotros.",
            }
        doctores = {
            d.id: d
            for d in db.query(Doctor).filter(Doctor.company_id == company.id).all()
        }
        return {
            "appointments": [
                {
                    "id": a.id,
                    "cuando": (
                        f"{dias[a.scheduled_at.weekday()]} "
                        f"{a.scheduled_at.strftime('%d/%m/%Y a las %H:%M')}"
                    ),
                    "doctor": (doctores.get(a.doctor_id).name if doctores.get(a.doctor_id) else ""),
                    "paciente": a.patient_name,
                    "estado": (
                        "confirmado" if a.status == "confirmed"
                        else "pendiente de que el paciente confirme"
                    ),
                    "motivo": a.notes,
                }
                for a in propias
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
        # Los huecos los calcula el SERVIDOR. Antes se devolvían los horarios
        # ocupados y el horario laboral como texto, y el modelo tenía que
        # deducir qué quedaba libre: de ahí salían turnos fuera de horario.
        libres = agenda.huecos_del_dia(
            db, company, doctor, day.date(), args.get("service_id")
        )
        salida = {
            "doctor": doctor.name,
            "work_schedule": doctor.schedule or "no especificado",
            "busy_slots": [a.scheduled_at.strftime("%H:%M") for a in busy],
        }
        if doctor.agenda_mode == "estructurado":
            salida["horarios_libres"] = libres
            salida["nota"] = (
                "Ofrecele SOLO horarios de `horarios_libres`: son los que el "
                "sistema verificó contra la agenda del profesional."
                if libres
                else f"{doctor.name} no tiene horarios libres ese día. Ofrecele otra fecha."
            )
        else:
            salida["nota"] = (
                "Este profesional todavía no tiene su horario cargado en el "
                "sistema, así que NO se puede confirmar disponibilidad. Podés "
                "tomar el pedido de turno, pero avisale que recepción se lo "
                "confirma; no le digas que ese horario está libre."
            )
        return salida

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
        # El servidor decide si el turno existe: día de la semana, franja del
        # profesional, licencias, duración real del servicio y solape. Antes
        # solo se miraba el solape, así que un paciente quedaba agendado un
        # domingo a las 23:00 con un doctor que atiende de mañana.
        servicio_id = args.get("service_id")
        veredicto = agenda.verificar_turno(
            db, company, doctor, when, service_id=servicio_id
        )
        if not veredicto["ok"]:
            respuesta = {"error": veredicto["motivo"], "codigo": veredicto["codigo"]}
            if veredicto.get("alternativas"):
                respuesta["horarios_libres"] = veredicto["alternativas"]
            return respuesta
        # El nombre tiene que ser de una persona, no un relleno del modelo.
        # Una cita a nombre de "el paciente" no le sirve a nadie en la
        # recepción, y es lo que sale cuando el bot agenda sin haber preguntado.
        nombre = _nombre_de_persona(args.get("patient_name"))
        if not nombre:
            return {
                "error": (
                    "Falta el nombre del paciente. Preguntá '¿a nombre de quién "
                    "agendo el turno?' y volvé a intentar con lo que te diga."
                )
            }
        # El teléfono debe ser real: si el modelo manda placeholders
        # ("null", "your phone number", etc.) usamos el de la conversación.
        phone = str(args.get("patient_phone") or "").strip()
        if sum(c.isdigit() for c in phone) < 6:
            phone = conversation.contact_phone
        # Se recuerda para los próximos turnos: el historial se corta a 20
        # mensajes y el nombre se perdía, así que el bot lo volvía a preguntar.
        conversation.patient_name = nombre[:200]
        if not args.get("para_otra_persona") and not conversation.stated_name:
            conversation.stated_name = nombre[:200]
        # Por qué convenio viene. El modelo pasa lo que DIJO el paciente y el
        # servidor lo resuelve contra los convenios de esta empresa: si el
        # modelo mandara un id, una alucinación de un número le cargaría la
        # atención a la aseguradora equivocada, y eso se descubre recién
        # cuando rechazan la planilla dos meses después.
        convenio = aranceles.buscar_convenio(db, company.id, args.get("seguro", ""))
        appt = Appointment(
            company_id=company.id,
            doctor_id=doctor.id,
            patient_name=nombre,
            patient_phone=phone,
            scheduled_at=when,
            service_id=servicio_id or None,
            insurer_id=convenio.id if convenio else None,
            duration_min=veredicto["duracion_min"],
            verificacion=veredicto["verificacion"],
            status="pending",
            notes=args.get("notes", ""),
        )
        db.add(appt)
        db.commit()
        # El recordatorio T-24h queda programado de forma durable: sobrevive
        # a un reinicio del servidor y se reintenta si el envío falla.
        job_handlers.schedule_appointment_reminder(db, appt)
        dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        return {
            "ok": True,
            "appointment_id": appt.id,
            "doctor": doctor.name,
            "when": when.strftime("%d/%m/%Y %H:%M"),
            # El día de la semana lo calcula el servidor. El modelo se
            # equivocaba: agendó el 12/08/2026 y se lo anunció al paciente
            # como "martes 12 de agosto" cuando el 12 era miércoles.
            "dia_de_la_semana": dias[when.weekday()],
            "decirle_al_paciente": (
                f"{dias[when.weekday()]} {when.strftime('%d/%m/%Y')} a las "
                f"{when.strftime('%H:%M')}"
            ),
            "message": (
                "Cita agendada como PENDIENTE DE CONFIRMACIÓN. Repetile la "
                "fecha usando exactamente el texto de `decirle_al_paciente`, "
                "pedile que confirme respondiendo, y avisale que un día antes "
                "le vas a mandar el recordatorio por acá."
                + (
                    ""
                    if veredicto["verificacion"] == "verificado"
                    else " OJO: este profesional no tiene su horario cargado en "
                    "el sistema, así que NO le prometas que el horario está "
                    "libre. Decile que queda PEDIDO y que recepción se lo "
                    "confirma."
                )
            ),
        }

    return {"error": f"Herramienta desconocida: {name}"}


def _bloque_de_contacto(conversation: Conversation | None) -> str:
    """Con quién está hablando el bot. Sin esto pedía el teléfono que ya tiene.

    El número llega en el propio mensaje de WhatsApp y `contact_phone` lo
    guarda desde siempre; el modelo nunca lo veía, así que le preguntaba al
    paciente un dato que estaba a una línea de distancia.

    El nombre del PERFIL no se ofrece como nombre del paciente a propósito:
    la gente pone "Mami" o el nombre de su comercio, y el modelo lo usaría
    para agendar. Se pasa aparte y aclarado.
    """
    if not conversation:
        return ""
    lineas = [
        f"Te escribe por WhatsApp el número {conversation.contact_phone}. "
        "YA LO TENÉS: no se lo pidas nunca."
    ]
    if conversation.stated_name:
        lineas.append(
            f"Esta persona ya te dijo que se llama {conversation.stated_name}. "
            "Tratala por su nombre y no se lo vuelvas a preguntar."
        )
    elif conversation.contact_name:
        lineas.append(
            f"Su perfil de WhatsApp figura como '{conversation.contact_name}', "
            "que puede no ser su nombre real: no lo uses para agendar sin "
            "confirmarlo."
        )
    if conversation.patient_name:
        lineas.append(
            f"El turno es para {conversation.patient_name}"
            + (
                " (no es quien te escribe)."
                if conversation.patient_name != conversation.stated_name
                else "."
            )
        )
    return "DATOS DE ESTE CONTACTO:\n- " + "\n- ".join(lineas)


def _build_system_prompt(
    db: Session, company: Company, agent: Agent, directive: str = "",
    conversation: Conversation | None = None,
) -> str:
    now = datetime.now(ZoneInfo(TIMEZONE))
    days = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    contacto = _bloque_de_contacto(conversation)
    parts = [
        agent.system_prompt,
        STYLE_RULES,
        *([contacto] if contacto else []),
        f"Negocio: {company.name} ({company.niche}).",
        f"Ahora es {days[now.weekday()]} {now.strftime('%d/%m/%Y %H:%M')} en Paraguay. "
        f"Toda cita se agenda en fecha futura, con año {now.year} o posterior.",
        # El calendario ya resuelto. Sin esto el modelo hace la aritmética de
        # fechas y se equivoca: medido el martes 11/08/2026, a "el martes a
        # las 10" contestó "martes 12 de agosto", y el 12 era miércoles.
        # Sale casi gratis en tokens y le saca de encima la única cuenta que
        # no sabe hacer.
        "Calendario de los próximos días (usá ESTAS fechas, no las calcules):\n"
        + "\n".join(
            f"- {days[(now + timedelta(days=i)).weekday()]} "
            f"{(now + timedelta(days=i)).strftime('%d/%m/%Y')}"
            + (" (hoy)" if i == 0 else " (mañana)" if i == 1 else "")
            for i in range(8)
        )
        + "\nSi el paciente dice un día de la semana sin fecha, es el PRÓXIMO "
        "que viene en esta lista. Si dice el día de hoy y la hora ya pasó, es "
        "el de la semana que viene: confirmáselo con la fecha completa.",
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
    # Solo las CATEGORÍAS, no el catálogo con precios. Dos razones:
    #  1. Los precios acá invitaban al modelo a citarlos sin llamar a
    #     list_services, que es la única fuente exacta y la que sabe qué
    #     profesional atiende cada cosa.
    #  2. Cupo: los 25 servicios con precio pesaban 385 tokens de los 2.814
    #     fijos por llamada, y el proveedor rápido da 8.000 tokens por minuto.
    #     Cada token de más le saca turnos por minuto a la clínica.
    categorias = [
        c[0] for c in db.query(Service.category)
        .filter(Service.company_id == company.id, Service.active)
        .distinct().limit(20).all() if c[0]
    ]
    hay_servicios = db.query(Service.id).filter(
        Service.company_id == company.id, Service.active).first()
    if hay_servicios:
        parts.append(
            (f"Áreas que atiende este negocio: {', '.join(categorias)}. "
             if categorias else "")
            + "El catálogo exacto —nombre, precio, duración, qué profesional lo "
            "hace y la preparación previa— sale SIEMPRE de list_services. "
            "NUNCA des un precio ni afirmes que un estudio existe sin haberlo "
            "consultado ahí."
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

    # Si dijo cómo se llama, se guarda ACÁ y no cuando al modelo se le ocurra:
    # el historial se corta a 20 mensajes y el nombre se perdía, así que el
    # bot volvía a preguntarle algo que ya le habían contestado.
    if not conversation.stated_name:
        declarado = _nombre_declarado(text)
        if declarado:
            conversation.stated_name = declarado

    db.add(Message(company_id=company.id, conversation_id=conversation.id, direction="in",
                   body=text, external_id=external_id or None))
    db.commit()

    # Baja de avisos: si el paciente escribe STOP hay que parar YA. Dejar eso
    # en manos de la interpretación de un modelo es como termina el número del
    # cliente reportado.
    if _ES_BAJA.match(_normalizar(text).strip()):
        conversation.opted_out = True
        conversation.opted_out_at = datetime.now(timezone.utc).replace(tzinfo=None)
        respuesta_baja = (
            "Listo, no te mandamos más recordatorios automáticos. 👍\n\n"
            "Vas a seguir pudiendo escribirnos cuando quieras, y te "
            "respondemos igual. Si más adelante los querés de vuelta, "
            "decinos *ALTA*."
        )
        db.add(Message(company_id=company.id, conversation_id=conversation.id,
                       direction="out", body=respuesta_baja))
        db.commit()
        return {
            "conversation_id": conversation.id, "reply": respuesta_baja,
            "status": conversation.status,
            "actions": [{"tool": "opt_out", "args": {}, "result": {"ok": True}}],
            "media": [], "supervision": None,
        }
    if conversation.opted_out and _ES_ALTA.match(_normalizar(text).strip()):
        conversation.opted_out = False
        conversation.opted_out_at = None
        db.commit()

    # Confirmación de cita: guardia determinística ANTES del modelo. Que una
    # cita quede confirmada no puede depender de que un LLM interprete bien un
    # "dale". Además sale gratis y sin espera: este turno no llama al modelo.
    por_confirmar = _cita_por_confirmar(db, company, conversation)
    if por_confirmar and _es_afirmativo(text):
        por_confirmar.status = "confirmed"
        doctor = db.get(Doctor, por_confirmar.doctor_id)
        reply_confirmacion = _texto_confirmacion(por_confirmar, doctor, company)
        db.add(Message(company_id=company.id, conversation_id=conversation.id,
                       direction="out", body=reply_confirmacion))
        db.add(AgentRun(
            company_id=company.id, agent_slug="cx", conversation_id=conversation.id,
            model="(determinístico)", question=text[:2000], answer=reply_confirmacion[:2000],
            tools_used="confirm_appointment",
            latency_ms=int((time.monotonic() - started) * 1000),
            tool_rounds=0, escalated=False, booked=False,
        ))
        db.commit()
        return {
            "conversation_id": conversation.id, "reply": reply_confirmacion,
            "status": conversation.status,
            "actions": [{"tool": "confirm_appointment", "args": {},
                         "result": {"ok": True, "appointment_id": por_confirmar.id}}],
            "media": [], "supervision": None,
        }
    aviso_cancelacion = ""
    if por_confirmar and _es_negativo(text):
        por_confirmar.status = "cancelled"
        job_handlers.cancel_appointment_reminder(db, por_confirmar.id)
        db.commit()
        aviso_cancelacion = (
            f"[SISTEMA] El paciente rechazó la cita del "
            f"{por_confirmar.scheduled_at.strftime('%d/%m a las %H:%M')}: ya quedó cancelada. "
            "Ofrecele 1 o 2 horarios alternativos y esperá que elija."
        )

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
    if aviso_cancelacion:
        directive = f"{directive}\n{aviso_cancelacion}".strip()
    messages: list[dict] = [
        {"role": "system", "content": _build_system_prompt(
            db, company, agent, directive, conversation)}
    ]
    for m in reversed(history):
        messages.append({"role": "user" if m.direction == "in" else "assistant", "content": m.body})

    tools = _tools_for(company)
    # Cadena de modelos, no uno solo: si el primero no está o se queda sin
    # cupo, se pasa al siguiente en vez de caer al modelo por defecto del
    # proveedor equivocado. `agent.model` sigue mandando si el tenant lo fijó.
    cadena = cadena_para("cx", agent.model)
    modelo_usado = ""
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
            messages, tools=tools, models=cadena, temperature=agent.temperature
        )
        modelo_usado = assistant.pop("_modelo_usado", modelo_usado)
        assistant.pop("_proveedor_usado", None)
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
                # Por el CÓDIGO, no por una palabra del mensaje: antes esto
                # miraba si el texto decía "solapa", así que cambiar una
                # palabra del error desarmaba la guarda en silencio. Y ahora
                # vale para cualquier rechazo de agenda: si el doctor no
                # atiende los domingos, el bot tampoco puede elegir otro día
                # por su cuenta.
                if name == "book_appointment" and result.get("codigo"):
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
        final = await chat_raw(messages, models=cadena, temperature=agent.temperature)
        modelo_usado = final.get("_modelo_usado", modelo_usado)
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
    #
    # PERO no se PERSISTE. Se guarda una marca. Dos razones, las dos serias:
    #  1. Privacidad: `messages.body` alimenta la auditoría diaria del Guard,
    #     que manda las conversaciones a un LLM externo. Persistir el bloque
    #     mandaría nombre, diagnóstico y dosis del paciente fuera del país
    #     todos los días. La receta ya vive en `prescriptions`, que no sale.
    #  2. El historial del turno siguiente se arma con `messages.body`: si el
    #     bloque estuviera ahí, la receta volvería al contexto del modelo y
    #     podría parafrasearla —justo lo que la entrega verbatim evita.
    # Ningún teléfono inventado sale al cliente. Va antes del verbatim porque
    # la receta se arma desde la base y no necesita revisión.
    reply_text, telefonos_inventados = _sanear_telefonos_inventados(
        db, company, conversation, reply_text
    )
    if telefonos_inventados:
        logger.warning(
            "empresa %s: el modelo inventó teléfono(s) %s; se quitaron de la respuesta",
            company.id, telefonos_inventados,
        )

    reply_a_enviar = reply_text
    if verbatim:
        reply_a_enviar = "\n\n".join([reply_text, *verbatim])
        marca = f"[se le envió al paciente su receta ({len(verbatim)} adjunto/s)]"
        reply_text = f"{reply_text}\n\n{marca}".strip()

    db.add(Message(company_id=company.id, conversation_id=conversation.id, direction="out", body=reply_text))
    tools_used = [a["tool"] for a in actions]
    db.add(AgentRun(
        company_id=company.id,
        agent_slug="cx",
        conversation_id=conversation.id,
        # El modelo que contestó DE VERDAD, no el que se pidió: con fallback
        # entre proveedores, guardar el pedido hacía que las métricas de
        # latencia midieran un modelo que quizá nunca corrió.
        model=(modelo_usado or agent.model)[:120],
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
        # Al canal va la respuesta CON la receta; a la base fue sin ella.
        "reply": reply_a_enviar,
        "status": conversation.status,
        "actions": actions,
        "media": media[:5],
        "supervision": revision.get("trigger") or None,
    }
