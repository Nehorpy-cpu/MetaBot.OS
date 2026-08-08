"""Integración con el puente WhatsApp Web (Baileys, QR).

Dos partes:
1. Webhook interno POST /webhooks/bridge: el bridge entrega el mensaje
   entrante y recibe la respuesta del motor conversacional en el mismo
   request (canal "qr").
2. Proxy de gestión /companies/{id}/wa/*: el panel consulta estado, inicia
   sesión (obtiene el QR) o cierra sesión, sin hablar directo con el bridge.
"""
import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import chat as chat_engine
from ..config import BRIDGE_SECRET, BRIDGE_URL
from ..db import get_db
from ..llm import LLMError
from ..models import Company

router = APIRouter(tags=["bridge"])


def _check_secret(secret: str | None):
    if BRIDGE_SECRET and secret != BRIDGE_SECRET:
        raise HTTPException(403, "Secreto de bridge inválido")


class BridgeMessage(BaseModel):
    company_id: int
    from_: str = Field(alias="from", min_length=3, max_length=50)
    name: str = ""
    text: str = Field(min_length=1, max_length=4000)

    model_config = {"populate_by_name": True}


@router.post("/webhooks/bridge")
async def bridge_incoming(
    payload: BridgeMessage,
    db: Session = Depends(get_db),
    x_bridge_secret: str | None = Header(default=None),
):
    _check_secret(x_bridge_secret)
    company = db.get(Company, payload.company_id)
    if not company:
        raise HTTPException(404, "Empresa no encontrada")
    if company.wa_mode != "qr":
        raise HTTPException(409, "La empresa no tiene el canal QR activo")
    try:
        outcome = await chat_engine.handle_incoming(
            db, company, payload.from_, payload.text,
            contact_name=payload.name, channel="whatsapp",
        )
    except LLMError as exc:
        # El bridge no reintenta: registrar y no responder nada al cliente
        raise HTTPException(503, f"LLM no disponible: {exc}")
    return {"reply": outcome.get("reply"), "status": outcome.get("status")}


# ---- Proxy de gestión de sesión QR para el panel ----

async def _bridge_call(method: str, path: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.request(
                method,
                f"{BRIDGE_URL}{path}",
                headers={"X-Bridge-Secret": BRIDGE_SECRET},
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError:
        raise HTTPException(
            502,
            "Bridge de WhatsApp no disponible. Arrancalo con: cd bridge && npm start",
        )


def _qr_company(company_id: int, db: Session) -> Company:
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Empresa no encontrada")
    return company


@router.get("/companies/{company_id}/wa/status")
async def wa_status(company_id: int, db: Session = Depends(get_db)):
    company = _qr_company(company_id, db)
    if company.wa_mode != "qr":
        return {"mode": company.wa_mode, "status": "n/a"}
    info = await _bridge_call("GET", f"/sessions/{company_id}/status")
    return {"mode": "qr", **info}


@router.post("/companies/{company_id}/wa/start")
async def wa_start(company_id: int, db: Session = Depends(get_db)):
    company = _qr_company(company_id, db)
    if company.wa_mode != "qr":
        raise HTTPException(409, "Activá primero el modo QR en la empresa")
    return await _bridge_call("POST", f"/sessions/{company_id}/start")


@router.post("/companies/{company_id}/wa/logout")
async def wa_logout(company_id: int, db: Session = Depends(get_db)):
    _qr_company(company_id, db)
    return await _bridge_call("POST", f"/sessions/{company_id}/logout")
