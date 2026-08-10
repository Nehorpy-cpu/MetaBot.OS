"""Taxonomía de intención del cliente y clasificación barata.

Genérica para cualquier rubro: una perfumería, una clínica y una
inmobiliaria comparten estas intenciones; lo que cambia es qué agente y qué
herramientas las atienden (eso lo deciden los Business Packs).

La clasificación por señales es determinística y cuesta cero: no agrega
latencia al cliente que está esperando en WhatsApp. Solo cuando las señales
no alcanzan y la decisión importa, el CEO consulta al modelo.
"""
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum


class Intent(str, Enum):
    URGENCIA = "urgencia"          # riesgo real: se escala YA
    RECLAMO = "reclamo"            # queja, problema con lo comprado/atendido
    AGENDAR = "agendar"            # quiere turno / reserva
    COMPRAR = "comprar"            # quiere comprar / cerrar
    CONSULTA_PRODUCTO = "consulta_producto"  # precio, stock, recomendación
    CONSULTA_INFO = "consulta_info"          # horarios, dirección, formas de pago
    HUMANO = "humano"              # pide hablar con una persona
    SALUDO = "saludo"              # apertura sin pedido concreto
    OTRO = "otro"


def _normalizar(texto: str) -> str:
    """Minúsculas sin tildes: 'Cuánto' y 'cuanto' son lo mismo."""
    limpio = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in limpio if unicodedata.category(c) != "Mn")


# Señales por intención. El orden de evaluación lo fija PRIORIDAD.
SEÑALES: dict[Intent, tuple[str, ...]] = {
    Intent.URGENCIA: (
        r"\burgen", r"\bemergencia",
        # Dolor torácico: cubre "dolor de pecho", "me duele mucho el pecho",
        # "duele el pecho". En urgencias, una señal de más es mejor que una
        # de menos.
        r"(dolor|duele|duele mucho|aprieta)\b.{0,25}\bpecho",
        r"\bpecho\b.{0,25}(dolor|duele|aprieta|oprime)",
        r"no puedo respirar", r"(dificultad|cuesta).{0,15}respirar", r"me falta el aire",
        r"sangrado", r"sangra mucho", r"desmay", r"convuls", r"\bacv\b", r"infarto",
        r"me estoy muriendo", r"\bgrave\b", r"perdi el conocimiento",
    ),
    Intent.HUMANO: (
        r"hablar con (una |un )?(persona|humano|alguien|encargad|responsable)",
        r"\bno (sos|eres) (una )?(persona|humano)", r"\bcon un asesor",
        r"atencion humana", r"pasame con",
    ),
    Intent.RECLAMO: (
        r"\breclam", r"\bqueja", r"me llego (mal|roto|fallado)", r"no funciona",
        r"esta (roto|fallado|vencido)", r"\bdevoluc", r"quiero mi (plata|dinero)",
        r"\bestafa", r"pesim", r"muy mal", r"nunca llego", r"no me atendieron",
    ),
    Intent.AGENDAR: (
        r"\bturno", r"\bcita\b", r"\bagendar", r"\breserv", r"\bhora para",
        r"quiero (ir|venir) el", r"\bdisponibilidad", r"\bconsulta con (el|la) (dr|dra|doctor)",
        r"me atiende", r"\bsacar (un )?turno",
    ),
    Intent.COMPRAR: (
        r"\bcomprar", r"lo (quiero|llevo)", r"\bme lo llevo", r"como (pago|abono)",
        r"\bpedido", r"quiero (uno|una|dos|ese|esa)", r"\bcerrar la compra",
        r"\bhacer el pago", r"\btransferencia",
    ),
    Intent.CONSULTA_PRODUCTO: (
        r"\bcuanto (sale|cuesta|vale)", r"\bprecio", r"\btenes\b", r"\btienen\b",
        r"\bhay\b", r"\bstock", r"\bdisponible", r"\brecomend", r"\bbusco\b",
        r"\bque me (recomendas|sugeris)", r"\bopciones",
    ),
    Intent.CONSULTA_INFO: (
        r"\bhorario", r"\bdireccion", r"\bdonde (estan|quedan|es)", r"\bubicad",
        r"\bcomo llego", r"\benvio", r"\bdelivery", r"\bformas de pago",
        r"\baceptan\b", r"\batienden (hoy|los|el)",
    ),
    Intent.SALUDO: (
        r"^\s*(hola|buenas|buen dia|buenos dias|buenas tardes|buenas noches|hey|holis)\b",
        r"^\s*(que tal|como (estas|andas))\b",
    ),
}

# De más grave/específico a más genérico: una urgencia gana sobre todo.
PRIORIDAD: tuple[Intent, ...] = (
    Intent.URGENCIA,
    Intent.HUMANO,
    Intent.RECLAMO,
    Intent.AGENDAR,
    Intent.COMPRAR,
    Intent.CONSULTA_PRODUCTO,
    Intent.CONSULTA_INFO,
    Intent.SALUDO,
)

_COMPILADAS: dict[Intent, tuple[re.Pattern, ...]] = {
    intent: tuple(re.compile(p) for p in patrones) for intent, patrones in SEÑALES.items()
}


@dataclass
class Clasificacion:
    intent: Intent
    confianza: float          # 0.0–1.0
    señales: list[str]        # qué disparó la decisión (auditable)
    metodo: str               # "señales" | "modelo" | "por_defecto"


def clasificar_por_señales(texto: str) -> Clasificacion:
    """Clasificación determinística, sin costo ni latencia.

    La confianza sube con la cantidad de señales encontradas. Una sola señal
    de urgencia ya es suficiente: ante la duda, se prefiere escalar.
    """
    normalizado = _normalizar(texto)
    encontradas: dict[Intent, list[str]] = {}
    for intent in PRIORIDAD:
        for patron in _COMPILADAS[intent]:
            match = patron.search(normalizado)
            if match:
                encontradas.setdefault(intent, []).append(match.group().strip())

    if not encontradas:
        return Clasificacion(Intent.OTRO, 0.0, [], "por_defecto")

    ganadora = next(i for i in PRIORIDAD if i in encontradas)
    señales = encontradas[ganadora]
    # Urgencia y pedido de humano: una señal basta y se toma con confianza alta.
    if ganadora in (Intent.URGENCIA, Intent.HUMANO):
        confianza = 0.95
    else:
        # Más señales de la misma intención → más confianza; si otra intención
        # también disparó, baja (el mensaje es ambiguo).
        competencia = len(encontradas) - 1
        confianza = min(0.9, 0.55 + 0.15 * len(señales)) - 0.15 * competencia
        confianza = max(0.2, confianza)
    return Clasificacion(ganadora, round(confianza, 2), señales, "señales")
