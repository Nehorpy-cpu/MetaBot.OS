"""Webhook de WhatsApp Cloud API.

Flujo: Meta manda POST → se valida la firma → se identifica el tenant por
phone_number_id → el mensaje se ENCOLA y se responde 200 al toque. El motor
conversacional corre después, en el worker.

Por qué encolar y no procesar en el request: `handle_incoming` tarda 40-60
segundos (el modelo con herramientas). Meta espera un 200 rápido y reintenta
si no lo recibe: procesarlo adentro haría que cada mensaje se reintente varias
veces y que el endpoint quede marcado como lento, lo que degrada la entrega.

Seguridad:
- GET de verificación con WHATSAPP_VERIFY_TOKEN.
- POST verificado con HMAC SHA-256 (X-Hub-Signature-256) sobre los BYTES
  CRUDOS. Sin WHATSAPP_APP_SECRET configurado se RECHAZA: este endpoint es
  público y sin firma cualquiera podría inyectarle conversaciones al bot.
"""
import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from ..config import WHATSAPP_APP_SECRET, WHATSAPP_VERIFY_TOKEN
from ..db import get_db
from ..models import Company

logger = logging.getLogger("metabot.whatsapp")
router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp"])


@router.get("")
def verify(
    mode: str = Query("", alias="hub.mode"),
    token: str = Query("", alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
):
    """Handshake de verificación.

    Los parámetros llegan con punto (`hub.mode`), de ahí los alias: con
    nombres pelados FastAPI no los toma y el handshake devuelve 422. Y el
    challenge se devuelve en TEXTO PLANO: como JSON llega entre comillas y
    Meta lo rechaza.
    """
    if mode == "subscribe" and WHATSAPP_VERIFY_TOKEN and token == WHATSAPP_VERIFY_TOKEN:
        return Response(content=challenge, media_type="text/plain")
    return Response(status_code=403)


def _signature_valid(body: bytes, header: str) -> bool:
    """Valida la firma sobre los bytes CRUDOS del cuerpo.

    Calcularla sobre el JSON ya parseado y vuelto a serializar da distinto:
    cambia el orden de las claves y los espacios.
    """
    if not WHATSAPP_APP_SECRET:
        # Falla CERRADO. Antes esto devolvía True con un warning, o sea que un
        # despliegue sin el secreto dejaba el webhook abierto: cualquiera
        # podía inyectarle conversaciones al bot de cualquier empresa.
        logger.error(
            "WHATSAPP_APP_SECRET sin configurar: se rechaza el webhook. "
            "Sin él no hay forma de saber si el mensaje viene de Meta."
        )
        return False
    if not header.startswith("sha256="):
        return False
    expected = hmac.new(WHATSAPP_APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header[len("sha256="):], expected)


@router.post("")
async def receive(request: Request, db: Session = Depends(get_db)):
    from .. import job_handlers

    body = await request.body()
    if not _signature_valid(body, request.headers.get("X-Hub-Signature-256", "")):
        return Response(status_code=403)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return {"status": "ignored"}

    encolados = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            # `statuses` son acuses de entrega, no mensajes. Se ignoran solos
            # porque solo se recorre `messages`, pero conviene tenerlo claro:
            # procesarlos como entrantes haría que el bot se responda a sí mismo.
            phone_number_id = value.get("metadata", {}).get("phone_number_id", "")
            company = (
                db.query(Company).filter(Company.wa_phone_number_id == phone_number_id).first()
                if phone_number_id
                else None
            )
            if not company:
                logger.warning("Mensaje para phone_number_id sin tenant: %s", phone_number_id)
                continue
            contactos = {
                c.get("wa_id"): c.get("profile", {}).get("name", "")
                for c in value.get("contacts", [])
            }
            for msg in value.get("messages", []):
                if msg.get("type") != "text":
                    continue  # audio/imagen: fase de voz (ASR) pendiente
                wa_from = msg.get("from", "")
                texto = msg.get("text", {}).get("body", "")
                if not wa_from or not texto:
                    continue
                job_handlers.schedule_inbound_message(
                    db, company.id,
                    telefono=f"+{wa_from}",
                    texto=texto,
                    nombre=contactos.get(wa_from, ""),
                    external_id=msg.get("id", ""),
                    phone_number_id=phone_number_id,
                )
                encolados += 1
    db.commit()
    # 200 SIEMPRE y rápido: si Meta no lo recibe a tiempo reintenta en bucle.
    return {"status": "ok", "queued": encolados}
