"""Salida proactiva unificada: el servidor inicia un envío.

El motor no sabe qué canal hay detrás. Acá se resuelve si sale por la Cloud
API de Meta o por el bridge de Baileys, según `company.wa_mode`, y se corta
si el canal no admite mensajes proactivos.
"""
import logging

import httpx
from sqlalchemy.orm import Session

from . import channels, whatsapp
from .config import BRIDGE_SECRET, BRIDGE_URL
from .models import Company

logger = logging.getLogger("metabot.outbound")


async def enviar(db: Session, company_id: int, telefono: str, texto: str) -> dict:
    """Manda un mensaje que inicia el servidor. Nunca lanza: devuelve el error."""
    company = db.get(Company, company_id)
    if not company:
        return {"error": "empresa inexistente"}
    if not telefono or not texto:
        return {"error": "falta teléfono o texto"}

    if not channels.can_send_proactive(company.wa_mode):
        # Ej. wa_mode="none": no hay canal conectado. Es un no-envío legítimo,
        # no un fallo: no tiene sentido reintentarlo.
        logger.info("empresa %s: el canal %s no admite proactivos", company_id, company.wa_mode)
        return {"sent": False, "skipped": True, "reason": f"canal {company.wa_mode} sin proactivos"}

    if company.wa_mode == "meta":
        return await whatsapp.send_text(company.wa_phone_number_id, telefono, texto)

    if company.wa_mode == "qr":
        try:
            async with httpx.AsyncClient(timeout=25) as client:
                resp = await client.post(
                    f"{BRIDGE_URL}/sessions/{company_id}/send",
                    headers={"X-Bridge-Secret": BRIDGE_SECRET},
                    json={"to": telefono, "text": texto},
                )
                if resp.status_code == 409:
                    # Sesión caída: el cliente tiene que volver a escanear.
                    # Es reintentable, así que va como error.
                    return {"error": "la sesión de WhatsApp no está conectada"}
                resp.raise_for_status()
                return {"sent": True, **resp.json()}
        except httpx.HTTPError as exc:
            return {"error": f"bridge no disponible: {type(exc).__name__}"}

    return {"sent": False, "skipped": True, "reason": f"canal desconocido: {company.wa_mode}"}
