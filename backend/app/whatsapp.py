"""Cliente de WhatsApp Cloud API (Meta Graph API).

Si WHATSAPP_TOKEN no está configurado, los envíos se omiten (dry-run) y se
informa en el resultado: así todo el sistema funciona en desarrollo sin
credenciales de Meta.
"""
import httpx

from .config import WHATSAPP_API_BASE, WHATSAPP_TOKEN


async def send_text(phone_number_id: str, to: str, text: str) -> dict:
    """Envía un mensaje de texto. `to` en formato internacional sin '+'."""
    if not WHATSAPP_TOKEN or not phone_number_id:
        return {"skipped": True, "reason": "WHATSAPP_TOKEN o phone_number_id sin configurar"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{WHATSAPP_API_BASE}/{phone_number_id}/messages",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            json={
                "messaging_product": "whatsapp",
                "to": to.lstrip("+").replace(" ", ""),
                "type": "text",
                "text": {"body": text[:4096]},
            },
        )
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError:
            return {"error": f"WhatsApp API {resp.status_code}: {resp.text[:300]}"}
        return {"sent": True, "response": resp.json()}
