"""Webhook de WhatsApp Cloud API.

Flujo: Meta manda POST con los mensajes entrantes → se identifica el tenant
por phone_number_id → el motor conversacional genera la respuesta (con
herramientas) → se responde por la Graph API.

Seguridad:
- GET de verificación con WHATSAPP_VERIFY_TOKEN.
- POST verificado con HMAC SHA-256 (X-Hub-Signature-256) usando
  WHATSAPP_APP_SECRET. Si el secret está configurado, toda firma inválida
  se rechaza con 403.
"""
import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from .. import chat as chat_engine
from .. import whatsapp
from ..config import WHATSAPP_APP_SECRET, WHATSAPP_VERIFY_TOKEN
from ..db import get_db
from ..llm import LLMError
from ..models import Company

logger = logging.getLogger("metabot.whatsapp")
router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp"])


@router.get("")
def verify(
    mode: str = Query("", alias="hub.mode"),
    token: str = Query("", alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
):
    if mode == "subscribe" and WHATSAPP_VERIFY_TOKEN and token == WHATSAPP_VERIFY_TOKEN:
        return Response(content=challenge, media_type="text/plain")
    return Response(status_code=403)


def _signature_valid(body: bytes, header: str) -> bool:
    if not WHATSAPP_APP_SECRET:
        # Sin secret configurado no se puede verificar; se acepta pero se avisa.
        logger.warning("WHATSAPP_APP_SECRET no configurado: firma sin verificar")
        return True
    if not header.startswith("sha256="):
        return False
    expected = hmac.new(WHATSAPP_APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header[len("sha256="):], expected)


@router.post("")
async def receive(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    if not _signature_valid(body, request.headers.get("X-Hub-Signature-256", "")):
        return Response(status_code=403)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return {"status": "ignored"}

    results = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            phone_number_id = value.get("metadata", {}).get("phone_number_id", "")
            company = (
                db.query(Company).filter(Company.wa_phone_number_id == phone_number_id).first()
                if phone_number_id
                else None
            )
            if not company:
                logger.warning("Mensaje para phone_number_id sin tenant: %s", phone_number_id)
                continue
            contacts = {c.get("wa_id"): c.get("profile", {}).get("name", "") for c in value.get("contacts", [])}
            for msg in value.get("messages", []):
                if msg.get("type") != "text":
                    continue  # audio/imagen: fase de voz (ASR) pendiente
                wa_from = msg.get("from", "")
                text = msg.get("text", {}).get("body", "")
                if not wa_from or not text:
                    continue
                try:
                    outcome = await chat_engine.handle_incoming(
                        db, company, f"+{wa_from}", text,
                        contact_name=contacts.get(wa_from, ""),
                        # Meta reenvía el webhook si no recibe 200 a tiempo:
                        # el id del mensaje evita procesarlo dos veces.
                        external_id=msg.get("id", ""),
                    )
                except LLMError as exc:
                    logger.error("LLM caído para company %s: %s", company.id, exc)
                    continue
                if outcome.get("duplicate"):
                    # Reentrega de Meta: ya se respondió, no se manda de nuevo.
                    logger.info("mensaje %s ya procesado; se omite reenvío", msg.get("id"))
                    continue
                reply = outcome.get("reply")
                for item in (outcome.get("media") or [])[:5]:
                    await whatsapp.send_image(
                        phone_number_id, wa_from, item.get("path", ""), item.get("caption", "")
                    )
                if reply:
                    send_result = await whatsapp.send_text(phone_number_id, wa_from, reply)
                    results.append({"to": wa_from, "company_id": company.id, "send": send_result})
    # Meta requiere 200 siempre para no reintentar en loop
    return {"status": "ok", "processed": results}
