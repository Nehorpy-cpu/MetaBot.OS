"""Business Packs: qué capacidades se activan según el negocio.

El núcleo es genérico. Una clínica no es un caso especial del código: es un
tenant con los packs `booking` + `healthcare` activos. Una perfumería tiene
`commerce`. Una agencia de viajes tendrá `travel`. Nadie escribe
`if vertical == "medical"` en el núcleo.
"""
import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Pack:
    key: str
    name: str
    description: str
    # Módulos del panel que habilita
    modules: tuple[str, ...]
    # Herramientas que gana el CX Bot
    tools: tuple[str, ...]
    # Reglas de conducta que se inyectan al system prompt
    rules: str = ""
    # Packs que necesita para funcionar
    requires: tuple[str, ...] = field(default_factory=tuple)


CORE = Pack(
    key="core",
    name="Recepción Digital (núcleo)",
    description="El bot que atiende el WhatsApp, con el catálogo y los servicios del negocio.",
    # `services` vive acá y no en la agenda a propósito: una clínica que solo
    # quiere que le contesten "¿hacen ecografía y cuánto sale?" tiene que poder
    # cargar sus estudios con precio sin comprar el módulo de turnos. Además,
    # las reglas sanitarias dicen "sale de list_services": esa herramienta no
    # puede depender de un bloque que el cliente quizá no compró.
    modules=("inbox", "dashboard", "agents", "services", "catalog"),
    tools=("list_services", "search_catalog"),
    rules=(
        "REGLAS DE LO QUE OFRECÉS (obligatorias):\n"
        "- Nunca inventes un servicio, un producto, un precio, un stock ni una "
        "promoción. Lo que ofrecés sale de las herramientas; si no está ahí, "
        "no existe.\n"
        "- Cuando muestres opciones, decí el precio exacto.\n"
        "- Si no tenés lo que piden, decilo con honestidad y ofrecé lo más "
        "cercano que sí tengas."
    ),
)


BOOKING = Pack(
    key="booking",
    name="Agenda / Reservas",
    description="Servicios, profesionales, disponibilidad, citas y recordatorios.",
    modules=("agenda", "reminders"),
    tools=("list_doctors", "check_agenda", "book_appointment", "my_appointments"),
    rules=(
        "REGLAS DE AGENDA (obligatorias):\n"
        "- Consultá la disponibilidad real antes de ofrecer un horario. Nunca la inventes.\n"
        "- EL TELÉFONO YA LO TENÉS: te está escribiendo por WhatsApp desde su "
        "número. NUNCA se lo pidas, queda ridículo. Solo pedí un teléfono "
        "distinto si el turno es para otra persona y te lo ofrecen.\n"
        "- Preguntá el nombre DEL PACIENTE, no 'tu nombre': mucha gente agenda "
        "para el hijo, la madre o la pareja. Preguntá así: '¿A nombre de quién "
        "agendo el turno?'. Si te contesta con un nombre suelto, ese es el "
        "nombre del paciente: usalo y no lo vuelvas a preguntar.\n"
        "- Cuando ya sepas el nombre, tratá a la persona por su nombre.\n"
        "- Si el horario pedido no está libre, ofrecé 1 o 2 alternativas y esperá que elija.\n"
        "- Solo confirmá la reserva cuando la herramienta devuelva ok, con la fecha y hora exactas.\n"
        "- Al agendar, cerrá SIEMPRE con dos cosas: pedile que confirme el "
        "turno respondiendo, y avisale que un día antes le vas a mandar un "
        "recordatorio por acá."
    ),
)

HEALTHCARE = Pack(
    key="healthcare",
    name="Salud (encima de Agenda)",
    description="Reglas sanitarias: sin diagnósticos, urgencias derivadas, datos sensibles.",
    modules=("prescriptions", "insurance", "registry", "medication"),
    tools=("check_coverage", "get_prescription"),
    requires=("booking",),
    rules=(
        "REGLAS SANITARIAS (obligatorias, Ley 7593/2025 de datos personales):\n"
        "- JAMÁS des diagnósticos, dosis ni indicaciones médicas por chat.\n"
        "- Si el paciente pide su receta, usá get_prescription. La receta se le "
        "adjunta TAL CUAL la escribió el doctor: NO la repitas, NO la resumas, "
        "NO la interpretes y NO agregues ni saques nada. Vos solo avisás que se "
        "la mandaste.\n"
        "- Si el paciente pregunta si puede cambiar una dosis, dejar el "
        "tratamiento, o te cuenta que un remedio le cayó mal: NO opines. "
        "Escalá a humano.\n"
        # Antes decía "avisá SIEMPRE la preparación previa". Eso hacía que a un
        # "¿hacen cardiología?" el bot contestara con precios, duraciones y
        # ayunos de tres estudios que nadie pidió. La preparación importa
        # cuando el paciente YA tiene turno —si no se la decimos, viaja en
        # vano—, no cuando pregunta si el estudio existe.
        "- La preparación previa (ayuno, vejiga llena, traer estudios "
        "anteriores) se avisa AL AGENDAR el estudio, no cuando el paciente "
        "pregunta si existe o cuánto sale. Sale de list_services.\n"
        "- Ante síntomas: empatía y ofrecer turno; nunca interpretar clínicamente.\n"
        "- Ante urgencia (dolor de pecho, dificultad para respirar, sangrado fuerte): "
        "indicá acudir a urgencias YA y escalá a humano.\n"
        "- Los datos de salud son sensibles: no los repitas ni los compartas fuera de lo necesario.\n"
        # Sin esto la atención queda como particular y el profesional no la
        # puede incluir en la planilla de su prepaga: cobra de menos por un
        # dato que el paciente habría dado si se lo preguntaban.
        "- AL AGENDAR preguntá una sola vez si viene con seguro o particular, "
        "y pasá lo que te diga tal cual en `seguro`. Si ya lo dijo antes en "
        "la conversación, no se lo vuelvas a preguntar."
    ),
)

PRACTITIONER = Pack(
    key="practitioner",
    name="Portal del Profesional",
    description="Cada profesional entra con su usuario y ve solo sus pacientes, sus recetas y su resumen del día.",
    modules=("previsita", "portal"),
    tools=(),
    requires=("healthcare",),
    rules="",
)


PACKS: dict[str, Pack] = {
    p.key: p for p in (CORE, BOOKING, HEALTHCARE, PRACTITIONER)
}

# Qué packs propone el Arquitecto de Negocio según el rubro detectado.
VERTICAL_PACKS: dict[str, tuple[str, ...]] = {
    # Qué bloques se le proponen a una empresa nueva según su rubro. El núcleo
    # NO se lista: va siempre, lo compre quien lo compre.
    "medical": ("booking", "healthcare"),
    "hospital": ("booking", "healthcare"),   # sanatorio: varias especialidades
    "dental": ("booking", "healthcare"),
    "veterinary": ("booking", "healthcare"),
    "laboratory": ("booking", "healthcare"),  # análisis clínicos
    "imaging": ("booking", "healthcare"),     # diagnóstico por imágenes
    # Los rubros de comercio se quedan con el núcleo, que ya trae el catálogo
    # y las reglas de venta. Antes apuntaban a un pack `commerce` que hoy no
    # existe: sin este cambio resolvían a CERO packs y el bot se quedaba sin
    # herramientas, en silencio.
    "ecommerce": (),
    "retail": (),
    "construction": (),
    "gastronomy": (),
    "travel": (),
    "beauty": ("booking",),
    "services": ("booking",),
    "education": ("booking",),
}


# Catálogo curado de servicios típicos por rubro (IndustryKnowledge).
# Es conocimiento público del sector, NO datos de otros tenants: sugerir a
# partir de lo que cargó otra empresa filtraría sus precios y su oferta.
INDUSTRY_SERVICES: dict[str, list[dict]] = {
    "medical": [
        {"name": "Consulta clínica", "category": "Consultas", "duration_min": 30},
        {"name": "Consulta de urgencia", "category": "Consultas", "duration_min": 20},
        {"name": "Electrocardiograma", "category": "Estudios", "duration_min": 20},
        {"name": "Ecografía abdominal", "category": "Estudios", "duration_min": 40},
        {"name": "Laboratorio: análisis de sangre", "category": "Estudios", "duration_min": 15},
        {"name": "Control de presión arterial", "category": "Controles", "duration_min": 15},
    ],
    "dental": [
        {"name": "Consulta odontológica", "category": "Consultas", "duration_min": 30},
        {"name": "Limpieza dental", "category": "Tratamientos", "duration_min": 45},
        {"name": "Blanqueamiento", "category": "Estética", "duration_min": 60},
        {"name": "Extracción simple", "category": "Tratamientos", "duration_min": 45},
        {"name": "Radiografía panorámica", "category": "Estudios", "duration_min": 20},
    ],
    "beauty": [
        {"name": "Corte de cabello", "category": "Peluquería", "duration_min": 45},
        {"name": "Coloración", "category": "Peluquería", "duration_min": 120},
        {"name": "Manicura", "category": "Manos y pies", "duration_min": 45},
        {"name": "Depilación", "category": "Estética", "duration_min": 30},
    ],
    "services": [
        {"name": "Consulta inicial", "category": "Consultas", "duration_min": 45},
        {"name": "Presupuesto a domicilio", "category": "Visitas", "duration_min": 60},
    ],
    "education": [
        {"name": "Clase particular", "category": "Clases", "duration_min": 60},
        {"name": "Evaluación de nivel", "category": "Evaluaciones", "duration_min": 30},
    ],
}


def industry_services(vertical: str) -> list[dict]:
    """Servicios típicos del rubro, de conocimiento público del sector."""
    return INDUSTRY_SERVICES.get(vertical, [])


def suggested_for(vertical: str) -> list[str]:
    """Bloques propuestos para un rubro. Un rubro desconocido se queda con el
    núcleo, que es lo mínimo que sirve: bot, catálogo y servicios."""
    return list(VERTICAL_PACKS.get(vertical, ()))


def packs_iniciales(vertical: str) -> str:
    """Lo que se le guarda a una empresa nueva, listo para la columna.

    Incluye `core` explícito aunque `active_packs` lo agregue solo: la fila
    de la base tiene que poder leerse sola y decir qué compró el cliente.
    Es también lo que escribió la migración b8d2e5f70a91, así que una
    empresa vieja y una nueva se ven igual.
    """
    return ",".join(["core"] + suggested_for(vertical))


def active_packs(company) -> list[Pack]:
    """Packs activos de una empresa, resolviendo dependencias.

    Lo que la empresa tiene contratado sale de `company.packs` y de ningún
    otro lado. Antes, si venía vacío se derivaba del rubro: eso convertía a
    `packs` en decorativo —una clínica a la que le sacabas la agenda la
    recuperaba sola en la siguiente request— y hacía imposible vender por
    bloques. La compatibilidad con las empresas viejas se resolvió de una
    vez en la migración b8d2e5f70a91, que es donde corresponde: en los
    datos. Vacío ahora significa lo que dice: solo el núcleo.
    """
    keys = [k for k in (company.packs or "").split(",") if k]
    # El núcleo no se compra ni se apaga: es el bot, el catálogo y los
    # servicios. Va primero para que sus reglas encabecen el prompt.
    keys = ["core"] + [k for k in keys if k != "core"]
    resolved: list[str] = []
    # Los que se están resolviendo ahora. Sin esto, un `requires` circular
    # —A necesita B y B necesita A, que es un error de tipeo perfectamente
    # posible— hace que el servidor entero se caiga con RecursionError.
    en_curso: set[str] = set()

    def _resolver(clave: str) -> None:
        """Agrega el pack y TODO lo que necesita, en cadena.

        Antes esto miraba solo un nivel de `requires`: con una cadena de tres
        —el portal del profesional necesita el módulo clínico, que necesita la
        agenda— el del medio se resolvía y el de abajo quedaba afuera, así que
        la empresa se quedaba sin poder agendar sin que nada avisara.
        """
        pack = PACKS.get(clave)
        if not pack or clave in resolved or clave in en_curso:
            return
        en_curso.add(clave)
        for dep in pack.requires:
            _resolver(dep)
        en_curso.discard(clave)
        if clave not in resolved:
            resolved.append(clave)

    for key in keys:
        _resolver(key)
    return [PACKS[k] for k in resolved]


def tools_for(company) -> set[str]:
    """Herramientas del CX Bot según los packs activos."""
    tools: set[str] = set()
    for pack in active_packs(company):
        tools.update(pack.tools)
    return tools


def rules_for(company) -> list[str]:
    """Reglas de conducta a inyectar en el system prompt."""
    return [p.rules for p in active_packs(company) if p.rules]


def modules_for(company) -> set[str]:
    """Módulos del panel habilitados."""
    modules: set[str] = set()
    for pack in active_packs(company):
        modules.update(pack.modules)
    return modules


def pack_del_modulo(modulo: str) -> Pack | None:
    """Qué bloque hay que comprar para tener ese módulo."""
    for pack in PACKS.values():
        if modulo in pack.modules:
            return pack
    return None


# ─────────────────────────────────────────────────────────────────────────
# El gate del servidor: qué bloque exige cada ruta.
#
# Se aplica POR PATH y nunca por router. `medical.py` mezcla en un solo
# archivo la agenda (bloque 2), el padrón del Círculo de Médicos (bloque 3)
# y el resumen pre-visita (bloque 4): gatear el router entero le regalaría
# dos bloques al que compró uno.
#
# El orden ES la prioridad: gana la primera regla que coincide. Por eso
# `/doctors/7/pre-visit` cae en `previsita` y no en `agenda`.
#
# Los patrones se comparan contra el sufijo que sigue al id de la empresa,
# y usan `[^/]+` para el id porque el mismo patrón tiene que servir para la
# ruta real (`/doctors/7/schedule`) y para la plantilla de FastAPI
# (`/doctors/{doctor_id}/schedule`), que es contra lo que corre el test.
# ─────────────────────────────────────────────────────────────────────────

NUCLEO = ""  # lo que devuelve `modulo_de_ruta` cuando la ruta va siempre

_RUTAS_POR_MODULO: tuple[tuple[str, str], ...] = (
    # Bloque 4 — Portal del Profesional
    (r"^/doctors/[^/]+/pre-visit(/send)?$", "previsita"),
    (r"^/portal(/|$)", "portal"),
    # Bloque 3 — Salud
    (r"^/doctors/(verify|verify-all|from-registry)$", "registry"),
    (r"^/registry(/|$)", "registry"),
    (r"^/prescriptions(/|$)", "prescriptions"),
    (r"^/insurers(/|$)", "insurance"),
    (r"^/medication(/|$)", "medication"),
    # Bloque 2 — Agenda
    (r"^/reminders(/|$)", "reminders"),
    (r"^/doctors(/|$)", "agenda"),
    (r"^/appointments(/|$)", "agenda"),
    (r"^/clinic-schedule(/|$)", "agenda"),
    (r"^/absences(/|$)", "agenda"),
)

# Rutas del núcleo: van con cualquier empresa, compre lo que compre.
#
# La lista es EXPLÍCITA a propósito. Si la regla fuera "lo que no está en el
# mapa de módulos es núcleo", un endpoint nuevo que nadie clasificó se
# regalaría en silencio — que es exactamente el agujero que este gate viene
# a tapar. Sin clasificar no es núcleo: es un error, y el test lo frena
# antes de que salga.
_RUTAS_DEL_NUCLEO: tuple[str, ...] = (
    r"^$",                              # GET/PATCH de la empresa
    r"^/agents(/|$)",
    r"^/supervision(/|$)",
    r"^/packs(/|$)",              # qué bloques compró: lo cambia la plataforma
    r"^/chat(/|$)",
    r"^/conversations(/|$)",
    r"^/dashboard(/|$)",
    r"^/stats(/|$)",
    r"^/glossary(/|$)",
    r"^/services(/|$)",
    r"^/products(/|$)",
    r"^/catalog(/|$)",
    r"^/wa(/|$)",                       # el canal de WhatsApp ES el núcleo
    r"^/reports(/|$)",
    r"^/audits(/|$)",
    r"^/segments(/|$)",
    r"^/prompt-suggestions(/|$)",
    r"^/competitors(/|$)",
    r"^/intelligence-sources(/|$)",
    r"^/campaigns(/|$)",
    r"^/creatives(/|$)",
)

_MODULO_COMPILADO = tuple((re.compile(p), m) for p, m in _RUTAS_POR_MODULO)
_NUCLEO_COMPILADO = tuple(re.compile(p) for p in _RUTAS_DEL_NUCLEO)


def modulo_de_ruta(sufijo: str) -> str | None:
    """Módulo que exige una ruta, a partir del path que sigue al id.

    Devuelve:
      - el nombre del módulo, si la ruta pertenece a un bloque vendible;
      - `NUCLEO` ("") si va con cualquier empresa;
      - None si nadie la clasificó todavía. None no es "permitido": es un
        error de programación que el test `test_bloques` frena antes del
        despliegue, y que en caliente se rechaza en vez de regalarse.
    """
    for patron, modulo in _MODULO_COMPILADO:
        if patron.match(sufijo):
            return modulo
    for patron in _NUCLEO_COMPILADO:
        if patron.match(sufijo):
            return NUCLEO
    return None
