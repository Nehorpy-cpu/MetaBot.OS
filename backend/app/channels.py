"""Omnichannel Gateway: contrato único de canal.

El cerebro no sabe qué canal hay detrás. Recibe `InboundMessage` normalizado
y devuelve `OutboundMessage`; el adaptador decide si sale por Baileys (QR),
WhatsApp Cloud API, o el simulador del panel.

Migrar un tenant de QR a Cloud API no toca agentes, memoria ni catálogo:
solo cambia qué conector resuelve su `company.wa_mode`.
"""
from dataclasses import dataclass, field
from enum import Enum


class Capability(str, Enum):
    """Qué puede hacer un canal, técnica Y legítimamente."""

    REPLY = "can_reply"
    SEND_MEDIA = "can_send_media"
    SEND_CATALOG = "can_send_catalog"
    SEND_TEMPLATE = "can_send_template"
    SEND_PROACTIVE = "can_send_proactive"
    RECEIVE_VOICE = "can_receive_voice"
    RECEIVE_IMAGES = "can_receive_images"
    RECEIVE_LOCATION = "can_receive_location"


@dataclass
class InboundMessage:
    """Mensaje entrante ya normalizado, sea cual sea el canal."""

    channel: str          # "whatsapp" | "instagram" | "webchat" | ...
    tenant_id: int        # SIEMPRE derivado del enrutamiento del servidor
    customer_id: str      # teléfono / id del contacto en ese canal
    text: str
    customer_name: str = ""
    external_id: str = ""  # id del mensaje en el canal → deduplicación
    media_urls: list[str] = field(default_factory=list)


@dataclass
class OutboundMessage:
    """Respuesta a enviar. `media` son rutas locales de fotos REALES."""

    text: str = ""
    media: list[dict] = field(default_factory=list)  # [{path, caption}]


@dataclass
class ChannelProfile:
    """Descripción de un conector: qué es y qué puede hacer.

    `official` distingue integraciones autorizadas por la plataforma de las
    de comunidad. No se le presenta al cliente una conexión de comunidad
    como si fuera oficial.
    """

    key: str
    name: str
    official: bool
    capabilities: set[Capability]
    warning: str = ""

    def can(self, capability: Capability) -> bool:
        return capability in self.capabilities


# --- Perfiles de los conectores disponibles ---

WHATSAPP_CLOUD = ChannelProfile(
    key="meta",
    name="WhatsApp Business Platform (Cloud API)",
    official=True,
    capabilities={
        Capability.REPLY,
        Capability.SEND_MEDIA,
        Capability.SEND_TEMPLATE,
        Capability.SEND_PROACTIVE,
        Capability.RECEIVE_VOICE,
        Capability.RECEIVE_IMAGES,
        Capability.RECEIVE_LOCATION,
    },
)

WHATSAPP_QR = ChannelProfile(
    key="qr",
    name="WhatsApp QR (conector de comunidad, Baileys)",
    official=False,
    capabilities={
        Capability.REPLY,
        Capability.SEND_MEDIA,
        Capability.RECEIVE_IMAGES,
        Capability.RECEIVE_VOICE,
        Capability.RECEIVE_LOCATION,
        # SEND_PROACTIVE está, pero acotado: el bridge ya tiene endpoint de
        # envío, así que técnicamente puede. Lo que NO puede es mandar
        # mensajes no solicitados: enviar campañas por acá es lo que hace que
        # restrinjan el número. Solo salen avisos que el paciente pidió o
        # consintió (recordatorio de su propia cita, de su propia medicación),
        # con horario silencioso y con baja por "STOP".
        Capability.SEND_PROACTIVE,
        # Sin SEND_TEMPLATE: las plantillas son un mecanismo de la API oficial.
    },
    warning=(
        "Conector de comunidad: usa WhatsApp Web y NO es una integración "
        "oficial ni autorizada por WhatsApp. Responde a quien escribe "
        "primero; no envía campañas ni mensajes proactivos. Para operación "
        "formal, alto volumen o datos sensibles, usar Cloud API."
    ),
)

SIMULATOR = ChannelProfile(
    key="none",
    name="Simulador interno del panel",
    official=True,
    capabilities={Capability.REPLY, Capability.SEND_MEDIA},
)

PROFILES: dict[str, ChannelProfile] = {
    p.key: p for p in (WHATSAPP_CLOUD, WHATSAPP_QR, SIMULATOR)
}


def profile_for(wa_mode: str) -> ChannelProfile:
    """Perfil del canal configurado en la empresa."""
    return PROFILES.get(wa_mode or "none", SIMULATOR)


def can_send_proactive(wa_mode: str) -> bool:
    """¿Se le puede escribir primero al cliente por este canal?

    Lo usan los recordatorios de citas y las campañas: por el conector de
    comunidad no se envían mensajes no solicitados.
    """
    return profile_for(wa_mode).can(Capability.SEND_PROACTIVE)
