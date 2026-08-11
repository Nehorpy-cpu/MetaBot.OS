"""Contrato IntelligenceSource: de dónde sale la inteligencia de mercado.

Mismo criterio que `channels.py` con los canales: cada fuente declara qué
puede hacer y en qué términos. La honestidad acá no es un adorno —es lo que
evita venderle a un cliente una capacidad que va a dejar de funcionar el día
que la plataforma de turno apriete el torniquete, o peor, que le cierren la
cuenta por raspar.

Las tres categorías, y por qué importan:

  OFICIAL      hay una API pública del proveedor y términos que la permiten.
               Se puede prometer, facturar y sostener.
  PÚBLICA      contenido que el negocio publicó para que cualquiera lo lea
               (su propia web, su catálogo). Legítimo, pero frágil: cambia el
               HTML y se rompe.
  RESTRINGIDA  técnicamente alcanzable, prohibido por los términos del sitio,
               o protegido activamente. NO se implementa.

Sobre las redes sociales, que es lo que siempre se pide: raspar perfiles de
Instagram, Facebook o TikTok viola sus términos y está protegido activamente
—ya nos pasó con Fragrantica y Cloudflare—. La alternativa que SÍ se sostiene
es la Meta Ad Library: es pública por ley (transparencia electoral y
comercial), tiene API oficial y muestra los anuncios ACTIVOS de cualquier
página. Para saber qué está promocionando la competencia es mejor fuente que
un perfil raspado, porque muestra en qué están gastando de verdad.
"""
from dataclasses import dataclass, field
from enum import Enum


class Legalidad(str, Enum):
    OFICIAL = "oficial"
    PUBLICA = "publica"
    RESTRINGIDA = "restringida"


class Capacidad(str, Enum):
    CATALOGO = "catalogo"          # productos, precios, servicios
    PRECIOS = "precios"
    CONTACTO = "contacto"          # dirección, teléfono, horarios
    ANUNCIOS = "anuncios"          # qué está promocionando
    PUBLICACIONES = "publicaciones"
    RESENAS = "resenas"


@dataclass
class FuenteInteligencia:
    """Descripción de una fuente: qué es, qué da y con qué condiciones."""

    key: str
    name: str
    legalidad: Legalidad
    capacidades: set[Capacidad] = field(default_factory=set)
    requiere: str = ""       # credencial o gestión previa que hace falta
    advertencia: str = ""
    implementada: bool = False

    def puede(self, capacidad: Capacidad) -> bool:
        return capacidad in self.capacidades

    @property
    def usable(self) -> bool:
        return self.implementada and self.legalidad is not Legalidad.RESTRINGIDA


SITIO_PUBLICO = FuenteInteligencia(
    key="website",
    name="Sitio web público del negocio",
    legalidad=Legalidad.PUBLICA,
    capacidades={Capacidad.CATALOGO, Capacidad.PRECIOS, Capacidad.CONTACTO},
    advertencia=(
        "Lee lo que el negocio publicó para cualquiera. Se rompe si cambian el "
        "HTML: es una fuente útil, no un contrato."
    ),
    implementada=True,
)

API_PROPIA = FuenteInteligencia(
    key="api",
    name="API pública del propio negocio",
    legalidad=Legalidad.OFICIAL,
    capacidades={Capacidad.CATALOGO, Capacidad.PRECIOS},
    advertencia="La mejor fuente cuando existe: es el dato tal cual lo publica el negocio.",
    implementada=True,
)

META_AD_LIBRARY = FuenteInteligencia(
    key="meta_ad_library",
    name="Meta Ad Library (API oficial)",
    legalidad=Legalidad.OFICIAL,
    capacidades={Capacidad.ANUNCIOS},
    requiere="Token de Meta con acceso a la Ad Library API",
    advertencia=(
        "Muestra los anuncios ACTIVOS de cualquier página de Facebook e "
        "Instagram. Es pública por ley de transparencia publicitaria. Para "
        "saber qué promociona la competencia es MEJOR que un perfil raspado: "
        "muestra en qué están gastando de verdad, no lo que dicen que hacen."
    ),
    implementada=False,  # necesita el token; queda declarada y lista
)

# --- Las que NO se implementan, y por qué ---

INSTAGRAM_PERFIL = FuenteInteligencia(
    key="instagram_scrape",
    name="Raspado de perfiles de Instagram",
    legalidad=Legalidad.RESTRINGIDA,
    capacidades={Capacidad.PUBLICACIONES, Capacidad.CATALOGO},
    advertencia=(
        "Los términos de Meta prohíben el acceso automatizado sin permiso, y "
        "está protegido activamente. Le pone en riesgo la cuenta al cliente. "
        "Para anuncios usar la Ad Library, que es oficial; para catálogo, el "
        "sitio web o la API del negocio."
    ),
    implementada=False,
)

TIKTOK_PERFIL = FuenteInteligencia(
    key="tiktok_scrape",
    name="Raspado de perfiles de TikTok",
    legalidad=Legalidad.RESTRINGIDA,
    capacidades={Capacidad.PUBLICACIONES},
    advertencia=(
        "Mismo caso que Instagram. TikTok tiene una Research API, pero es solo "
        "para investigación académica acreditada: no cubre uso comercial."
    ),
    implementada=False,
)

FUENTES: dict[str, FuenteInteligencia] = {
    f.key: f
    for f in (SITIO_PUBLICO, API_PROPIA, META_AD_LIBRARY, INSTAGRAM_PERFIL, TIKTOK_PERFIL)
}


def fuente_de(url: str) -> FuenteInteligencia:
    """Clasifica una URL: qué fuente es y si se puede usar.

    Se llama ANTES de intentar nada. Que el sistema rechace una URL de
    Instagram con un motivo claro es mejor que intentarlo, fallar raro, y que
    el cliente crea que es un bug nuestro.
    """
    u = (url or "").lower()
    if "instagram.com" in u:
        return INSTAGRAM_PERFIL
    if "tiktok.com" in u:
        return TIKTOK_PERFIL
    if "facebook.com/ads/library" in u or "facebook.com/ads/archive" in u:
        return META_AD_LIBRARY
    if "facebook.com" in u:
        # Un perfil de Facebook cae en lo mismo que Instagram: mismos términos.
        return INSTAGRAM_PERFIL
    return SITIO_PUBLICO


def revisar_url(url: str) -> dict:
    """Devuelve si la URL se puede escanear y, si no, qué hacer en su lugar."""
    fuente = fuente_de(url)
    if fuente.legalidad is Legalidad.RESTRINGIDA:
        return {
            "permitida": False,
            "fuente": fuente.name,
            "motivo": fuente.advertencia,
            "alternativa": (
                "Cargá el sitio web del negocio. Si querés ver qué está "
                "promocionando, se usa la Meta Ad Library, que es oficial."
            ),
        }
    if not fuente.implementada:
        return {
            "permitida": False,
            "fuente": fuente.name,
            "motivo": f"Fuente todavía no conectada. Requiere: {fuente.requiere}",
            "alternativa": "",
        }
    return {"permitida": True, "fuente": fuente.name, "motivo": "", "alternativa": ""}


def catalogo() -> list[dict]:
    """Qué fuentes existen y en qué estado. Para mostrarlo en el panel."""
    return [
        {
            "key": f.key,
            "name": f.name,
            "legalidad": f.legalidad.value,
            "capacidades": sorted(c.value for c in f.capacidades),
            "requiere": f.requiere,
            "advertencia": f.advertencia,
            "implementada": f.implementada,
            "usable": f.usable,
        }
        for f in FUENTES.values()
    ]
