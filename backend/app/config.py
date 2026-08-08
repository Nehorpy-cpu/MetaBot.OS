"""Configuración central. Todo secreto se lee de variables de entorno."""
import os
from pathlib import Path

# Carga .env si existe (sin dependencia externa)
_env_file = Path(__file__).resolve().parents[2] / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./metabot.db")
TIMEZONE = os.environ.get("TIMEZONE", "America/Asuncion")

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
]
