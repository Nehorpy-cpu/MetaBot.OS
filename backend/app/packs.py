"""Business Packs: qué capacidades se activan según el negocio.

El núcleo es genérico. Una clínica no es un caso especial del código: es un
tenant con los packs `booking` + `healthcare` activos. Una perfumería tiene
`commerce`. Una agencia de viajes tendrá `travel`. Nadie escribe
`if vertical == "medical"` en el núcleo.
"""
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


COMMERCE = Pack(
    key="commerce",
    name="Comercio / Venta de productos",
    description="Catálogo real con fotos, búsqueda por presupuesto y perfil, recomendación y pedidos.",
    modules=("catalog", "orders"),
    tools=("search_catalog",),
    rules=(
        "REGLAS DE VENTA (obligatorias):\n"
        "- Nunca inventes producto, precio, stock ni promoción: usá search_catalog "
        "y ofrecé SOLO lo que devuelva.\n"
        "- Preguntá para quién es, qué perfil busca y hasta cuánto quiere gastar "
        "antes de recomendar. Una pregunta por mensaje.\n"
        "- Cuando muestres opciones, decí precio exacto y si hay stock.\n"
        "- Si no hay nada en su presupuesto, decilo con honestidad y ofrecé lo más cercano."
    ),
)

BOOKING = Pack(
    key="booking",
    name="Agenda / Reservas",
    description="Servicios, profesionales, disponibilidad, citas y recordatorios.",
    modules=("services", "agenda", "reminders"),
    tools=("list_services", "list_doctors", "check_agenda", "book_appointment"),
    rules=(
        "REGLAS DE AGENDA (obligatorias):\n"
        "- Consultá la disponibilidad real antes de ofrecer un horario. Nunca la inventes.\n"
        "- Confirmá nombre y teléfono antes de agendar.\n"
        "- Si el horario pedido no está libre, ofrecé 1 o 2 alternativas y esperá que elija.\n"
        "- Solo confirmá la reserva cuando la herramienta devuelva ok, con la fecha y hora exactas."
    ),
)

HEALTHCARE = Pack(
    key="healthcare",
    name="Salud (encima de Agenda)",
    description="Reglas sanitarias: sin diagnósticos, urgencias derivadas, datos sensibles.",
    modules=("patients",),
    tools=(),
    requires=("booking",),
    rules=(
        "REGLAS SANITARIAS (obligatorias, Ley 7593/2025 de datos personales):\n"
        "- JAMÁS des diagnósticos, dosis ni indicaciones médicas por chat.\n"
        "- Ante síntomas: empatía y ofrecer turno; nunca interpretar clínicamente.\n"
        "- Ante urgencia (dolor de pecho, dificultad para respirar, sangrado fuerte): "
        "indicá acudir a urgencias YA y escalá a humano.\n"
        "- Los datos de salud son sensibles: no los repitas ni los compartas fuera de lo necesario."
    ),
)

TRAVEL = Pack(
    key="travel",
    name="Turismo / Viajes",
    description="Destinos, paquetes, cotizaciones y seguimiento.",
    modules=("catalog", "quotes"),
    tools=("search_catalog",),
    rules=(
        "REGLAS DE VIAJES:\n"
        "- Precios y disponibilidad salen del catálogo real, nunca de tu memoria.\n"
        "- Preguntá fechas, cantidad de personas y presupuesto antes de cotizar."
    ),
)

PACKS: dict[str, Pack] = {p.key: p for p in (COMMERCE, BOOKING, HEALTHCARE, TRAVEL)}

# Qué packs propone el Arquitecto de Negocio según el rubro detectado.
VERTICAL_PACKS: dict[str, tuple[str, ...]] = {
    "medical": ("booking", "healthcare"),
    "dental": ("booking", "healthcare"),
    "veterinary": ("booking", "healthcare"),
    "ecommerce": ("commerce",),
    "retail": ("commerce",),
    "construction": ("commerce",),
    "beauty": ("booking", "commerce"),
    "gastronomy": ("commerce",),
    "services": ("booking",),
    "education": ("booking",),
    "travel": ("travel",),
}


def suggested_for(vertical: str) -> list[str]:
    """Packs propuestos para un rubro. Genéricos por defecto: comercio."""
    return list(VERTICAL_PACKS.get(vertical, ("commerce",)))


def active_packs(company) -> list[Pack]:
    """Packs activos de una empresa, resolviendo dependencias.

    Compatibilidad: si la empresa no tiene packs guardados (creada antes de
    esta versión), se derivan de su vertical.
    """
    keys = [k for k in (company.packs or "").split(",") if k]
    if not keys:
        keys = suggested_for(company.vertical)
    resolved: list[str] = []
    for key in keys:
        pack = PACKS.get(key)
        if not pack:
            continue
        for dep in pack.requires:
            if dep not in resolved and dep in PACKS:
                resolved.append(dep)
        if key not in resolved:
            resolved.append(key)
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
