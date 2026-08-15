"""Configuración central. Todo secreto se lee de variables de entorno."""
import os
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]


def _cargar(archivo: Path) -> None:
    """Lee un .env sin dependencias. `utf-8-sig` a propósito: un archivo
    creado en Windows suele traer BOM, y ese carácter invisible pegado al
    principio del primer valor rompe una credencial sin que se note."""
    if not archivo.exists():
        return
    for linea in archivo.read_text(encoding="utf-8-sig").splitlines():
        linea = linea.strip()
        if linea and not linea.startswith("#") and "=" in linea:
            clave, _, valor = linea.partition("=")
            os.environ.setdefault(clave.strip(), valor.strip())


# El .env principal, y después el archivo aparte donde vive la clave de
# OpenAI en la máquina de desarrollo. Los dos están en .gitignore y en
# .dockerignore: no se versionan ni entran a la imagen.
_cargar(_RAIZ / ".env")
_cargar(_RAIZ / "GPTAPI.env")

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./metabot.db")
TIMEZONE = os.environ.get("TIMEZONE", "America/Asuncion")

# Token de acceso al panel/API. Sin él, /api queda protegido y nadie entra.
# En producción DEBE estar definido; si falta, el backend arranca en modo
# "cerrado" (rechaza todo /api salvo health y webhooks) para no exponer datos.
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")

# WhatsApp Cloud API (una app de Meta puede servir varios números;
# cada número/tenant se identifica por su phone_number_id)
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
WHATSAPP_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
WHATSAPP_APP_SECRET = os.environ.get("WHATSAPP_APP_SECRET", "")
WHATSAPP_API_BASE = "https://graph.facebook.com/v21.0"

# Puente WhatsApp Web por QR (Baileys) para tenants sin Meta API
BRIDGE_URL = os.environ.get("BRIDGE_URL", "http://localhost:3001")
BRIDGE_SECRET = os.environ.get("BRIDGE_SECRET", "")

# Proveedores LLM en orden de fallback. Todos exponen API OpenAI-compatible.
LLM_PROVIDERS = [
    {
        "name": "nvidia",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "api_key": os.environ.get("NVIDIA_API_KEY", ""),
        "default_model": "meta/llama-3.3-70b-instruct",
    },
    {
        "name": "groq",
        "base_url": "https://api.groq.com/openai/v1",
        "api_key": os.environ.get("GROQ_API_KEY", ""),
        "default_model": "llama-3.3-70b-versatile",
    },
    {
        "name": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": os.environ.get("OPENROUTER_API_KEY", ""),
        "default_model": "meta-llama/llama-3.3-70b-instruct:free",
    },
    {
        # Google AI Studio (free tier) vía endpoint OpenAI-compatible
        "name": "gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_key": os.environ.get("GOOGLE_API_KEY", ""),
        "default_model": "gemini-2.5-flash",
    },
]


# ─── CFO de Finanzas ─────────────────────────────────────────────────────
#
# OpenAI entra como un proveedor MÁS, solo para el CFO. No reemplaza el
# router de arriba: los otros bots del sistema no cambian porque el CFO gane
# un proveedor.
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

# ── Qué modelos puede tocar el sistema ───────────────────────────────────
#
# LISTA BLANCA. Tres modelos: uno de texto, uno de voz a texto, uno de texto
# a voz. Nada más.
#
# Está en código y no en el entorno a propósito, igual que la clasificación
# de riesgo y los CFO_ALLOW_*: habilitar un modelo cambia lo que el sistema
# puede gastar y hacer, así que tiene que verse en el diff de un commit y
# pasar por revisión. Una variable de entorno la cambia alguien a las once de
# la noche y nadie se entera.
#
# La clave habilita 124 modelos, incluidos `sora-2`, `gpt-image-2` y los
# `-pro`. Ninguno hace falta para contestar por WhatsApp, y todos se cobran.
# Que estén disponibles no es motivo para permitirlos: la cuenta la paga el
# dueño del negocio.
OPENAI_MODELOS_PERMITIDOS = frozenset({
    "gpt-4o-mini",             # texto: barato y llama bien a las herramientas
    "gpt-4o-mini-transcribe",  # voz → texto
    "gpt-4o-mini-tts",         # texto → voz
})


def _modelo(variable: str, por_defecto: str) -> str:
    """Permite elegir DENTRO de la lista blanca, nunca fuera.

    Si el entorno pide un modelo que no está permitido, se ignora y se usa el
    de siempre. Un despliegue mal configurado no puede ser la vía por la que
    el sistema empieza a llamar a un modelo que nadie autorizó.
    """
    elegido = os.environ.get(variable, "").strip() or por_defecto
    if elegido not in OPENAI_MODELOS_PERMITIDOS:
        print(
            f"[config] {variable}={elegido!r} no está en la lista blanca de "
            f"modelos; se usa {por_defecto!r}."
        )
        return por_defecto
    return elegido


# Los identificadores viven ACÁ y no desperdigados por el código: cambiar de
# modelo tiene que ser una línea de configuración, no una cacería.
#
# Antes acá decía gpt-5.6-luna / gpt-5.6-terra / gpt-5.6-sol, que vinieron de
# la especificación original. Son modelos grandes y caros, y el CFO no los
# necesita: narra un número que ya calculó el servidor.
OPENAI_TEXT_MODEL = _modelo("OPENAI_TEXT_MODEL", "gpt-4o-mini")
OPENAI_TRANSCRIPTION_MODEL = _modelo(
    "OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe"
)
OPENAI_TTS_MODEL = _modelo("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")

# Que OpenAI no guarde las respuestas del CFO de su lado. La memoria canónica
# del sistema vive en PostgreSQL.
# Dominio desde el que se sirven los informes. Vacío = el mismo del panel,
# que es lo correcto en un despliegue de un solo dominio.
CFO_REPORT_BASE_URL = os.environ.get("CFO_REPORT_BASE_URL", "").rstrip("/")

# OpenAI entra al router de proveedores como uno más, con la MISMA forma que
# los otros. No hay un camino aparte para OpenAI: si lo hubiera, la lista
# blanca de arriba habría que repetirla en dos lugares y uno de los dos se
# olvidaría.
LLM_PROVIDERS.append({
    "name": "openai",
    "base_url": OPENAI_BASE_URL,
    "api_key": OPENAI_API_KEY,
    "default_model": OPENAI_TEXT_MODEL,
})

OPENAI_STORE_RESPONSES = os.environ.get("OPENAI_STORE_RESPONSES", "false").lower() == "true"

# Qué hace el CFO con la IA. `deterministico` es el ÚNICO valor que no
# depende de ninguna credencial: calcula y responde con plantillas, sin
# narrativa generada. Es también el que queda si no hay proveedor.
CFO_POLITICA_IA = os.environ.get("CFO_POLITICA_IA", "router_existente")

CFO_ENABLED = os.environ.get("CFO_ENABLED", "true").lower() == "true"
CFO_REQUIRE_PIN_FOR_MEDIUM_RISK = os.environ.get(
    "CFO_REQUIRE_PIN_FOR_MEDIUM_RISK", "true"
).lower() == "true"

# La automejora nace apagada para escribir, y el código no tiene el camino
# para encender estas tres: instalar, fusionar y desplegar solos es
# exactamente lo que no puede pasar.
CFO_IMPROVEMENT_SCOUT_ENABLED = os.environ.get(
    "CFO_IMPROVEMENT_SCOUT_ENABLED", "false"
).lower() == "true"
CFO_ALLOW_AUTOMATIC_INSTALL = False
CFO_ALLOW_AUTOMATIC_MERGE = False
CFO_ALLOW_AUTOMATIC_DEPLOY = False
CFO_ALLOW_AUTOMATIC_METRIC_CHANGE = False


def openai_configurado() -> bool:
    """Si hay una clave cargada. NO dice si es válida: eso solo se sabe
    llamando, y lo comprueba `scripts/probar_openai.py`."""
    return bool(OPENAI_API_KEY)
