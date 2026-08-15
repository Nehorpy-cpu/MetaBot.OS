"""Integración con el puente WhatsApp Web (Baileys, QR).

Dos partes:
1. Webhook interno POST /webhooks/bridge: el bridge entrega el mensaje
   entrante y recibe la respuesta del motor conversacional en el mismo
   request (canal "qr").
2. Proxy de gestión /companies/{id}/wa/*: el panel consulta estado, inicia
   sesión (obtiene el QR) o cierra sesión, sin hablar directo con el bridge.
"""
import base64
import binascii
import logging

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audio, channels, sessions
from .. import chat as chat_engine
from ..config import BRIDGE_SECRET, BRIDGE_URL
from ..db import get_db
from ..llm import LLMError
from ..models import Company

logger = logging.getLogger("metabot.bridge")

# Lo que se contesta cuando la nota de voz no se pudo entender. Del otro lado
# hay alguien esperando: el silencio del bot se lee como que el negocio no
# atiende.
NO_SE_ENTENDIO = (
    "Perdón, no llegué a entender bien el audio. ¿Me lo repetís o me lo "
    "escribís?"
)

router = APIRouter(tags=["bridge"])


def _check_secret(secret: str | None):
    if BRIDGE_SECRET and secret != BRIDGE_SECRET:
        raise HTTPException(403, "Secreto de bridge inválido")


class BridgeMessage(BaseModel):
    company_id: int
    from_: str = Field(alias="from", min_length=3, max_length=50)
    name: str = ""
    # Vacio cuando lo que llego fue una nota de voz: el texto sale de
    # transcribirla, y recien despues arranca el camino de siempre.
    text: str = Field(default="", max_length=4000)
    # Nota de voz en base64. Va aca y no como multipart porque el bridge ya
    # manda JSON y una segunda forma de entrada es una segunda superficie que
    # mantener. El limite real lo pone `audio.MAXIMO_BYTES`; este de aca es el
    # tope del transporte, con el ~33% que agrega base64.
    audio_base64: str = Field(default="", max_length=12_000_000)
    audio_mime: str = Field(default="", max_length=100)
    # id del mensaje en WhatsApp: permite deduplicar reentregas
    external_id: str = Field(default="", max_length=120)

    model_config = {"populate_by_name": True}


class HeartbeatIn(BaseModel):
    company_id: int
    worker_id: str = Field(min_length=1, max_length=64)
    status: str = ""
    phone: str = ""


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

    # Una nota de voz se vuelve texto y entra por el MISMO camino, con las
    # mismas herramientas, los mismos permisos y los mismos guardias. Abrirle
    # una via paralela seria abrirle una segunda oportunidad de saltearse un
    # control.
    texto = payload.text
    era_audio = False
    if payload.audio_base64:
        try:
            datos = base64.b64decode(payload.audio_base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(422, "El audio no llegó en base64 válido")
        try:
            texto = await audio.transcribir(datos, "nota.ogg")
        except audio.AudioError as exc:
            logger.warning("empresa %s: no se pudo transcribir: %s",
                           company.id, exc)
            # Se contesta, no se calla. Del otro lado hay alguien esperando, y
            # el silencio del bot se lee como que el negocio no atiende.
            return {"reply": NO_SE_ENTENDIO, "status": "audio_ilegible",
                    "media": [], "duplicate": False}
        era_audio = True
        if not texto.strip():
            return {"reply": NO_SE_ENTENDIO, "status": "audio_vacio",
                    "media": [], "duplicate": False}

    if not texto.strip():
        raise HTTPException(422, "El mensaje llegó sin texto ni audio")

    try:
        outcome = await chat_engine.handle_incoming(
            db, company, payload.from_, texto,
            contact_name=payload.name, channel="whatsapp",
            external_id=payload.external_id,
        )
    except LLMError as exc:
        # El bridge no reintenta: registrar y no responder nada al cliente
        raise HTTPException(503, f"LLM no disponible: {exc}")
    respuesta = {
        "reply": outcome.get("reply"),
        "status": outcome.get("status"),
        "media": outcome.get("media", []),
        "duplicate": outcome.get("duplicate", False),
    }

    # Se contesta en el mismo medio en el que preguntaron. Quien manda un
    # audio suele estar manejando o con las manos ocupadas: devolverle un
    # parrafo para leer no le sirve. Va TAMBIEN el texto, porque un monto que
    # se escucha una vez no se puede volver a mirar.
    if era_audio and respuesta["reply"] and not respuesta["duplicate"]:
        try:
            hablado = await audio.hablar(audio.para_hablar(respuesta["reply"]))
            respuesta["audio_base64"] = base64.b64encode(hablado).decode()
            respuesta["audio_mime"] = "audio/ogg; codecs=opus"
        except audio.AudioError as exc:
            # Sin voz, pero con la respuesta escrita: mejor eso que nada.
            logger.warning("empresa %s: no se pudo hablar: %s", company.id, exc)
    return respuesta


@router.post("/webhooks/bridge/lease")
def bridge_lease(payload: HeartbeatIn, db: Session = Depends(get_db),
                 x_bridge_secret: str | None = Header(default=None)):
    """El worker pide el lease de la sesión. Si otro worker vivo lo tiene,
    responde granted=false y ese worker NO debe abrir la sesión."""
    _check_secret(x_bridge_secret)
    granted = sessions.acquire(db, payload.company_id, payload.worker_id)
    return {"granted": granted}


@router.post("/webhooks/bridge/heartbeat")
def bridge_heartbeat(payload: HeartbeatIn, db: Session = Depends(get_db),
                     x_bridge_secret: str | None = Header(default=None)):
    """Latido: renueva el lease y reporta estado. Si devuelve held=false, el
    worker perdió el lease y debe cerrar su sesión."""
    _check_secret(x_bridge_secret)
    held = sessions.heartbeat(db, payload.company_id, payload.worker_id,
                              status=payload.status, phone=payload.phone)
    return {"held": held}


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
    profile = channels.profile_for(company.wa_mode)
    meta = {
        "channel_name": profile.name,
        "official": profile.official,
        "warning": profile.warning,
        "capabilities": sorted(c.value for c in profile.capabilities),
    }
    if company.wa_mode != "qr":
        return {"mode": company.wa_mode, "status": "n/a", **meta}
    info = await _bridge_call("GET", f"/sessions/{company_id}/status")
    return {"mode": "qr", **info, **meta}


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


@router.get("/companies/{company_id}/wa/diagnostico")
async def wa_diagnostico(company_id: int, db: Session = Depends(get_db)):
    """Qué falta para que este canal funcione, dicho sin rodeos.

    Sin esto, "el bot no responde" es una adivinanza: puede ser el modo mal
    puesto, el bridge caído, el QR sin escanear, un token que Meta venció o el
    webhook que nunca se configuró. Cada una se arregla en un lugar distinto.
    """
    from ..config import (
        WHATSAPP_APP_SECRET, WHATSAPP_TOKEN, WHATSAPP_VERIFY_TOKEN,
    )

    company = _qr_company(company_id, db)
    perfil = channels.profile_for(company.wa_mode)
    pasos: list[dict] = []

    def paso(titulo: str, ok: bool, detalle: str, donde: str = ""):
        pasos.append({"paso": titulo, "ok": ok, "detalle": detalle, "donde": donde})

    if company.wa_mode == "none":
        paso("Canal elegido", False,
             "Esta empresa todavía no tiene canal: el bot solo responde en el "
             "simulador del panel. Elegí WhatsApp Web (QR) o Meta.",
             "Conexiones → elegir canal")
        return {"mode": "none", "listo": False, "canal": perfil.name, "pasos": pasos}

    if company.wa_mode == "qr":
        paso("Canal elegido", True, f"{perfil.name}.", "")
        try:
            info = await _bridge_call("GET", f"/sessions/{company_id}/status")
            bridge_ok = True
        except HTTPException:
            info = {}
            bridge_ok = False
        paso("Puente WhatsApp Web activo", bridge_ok,
             "El servicio del puente responde."
             if bridge_ok else
             "El puente no responde. Es un contenedor aparte: revisá que "
             "`bridge` esté levantado.",
             "servidor: docker compose up -d bridge")
        estado = info.get("status", "desconocido")
        conectado = estado == "connected"
        paso("Sesión de WhatsApp vinculada", conectado,
             f"Conectado como {info.get('phone') or 'número no informado'}."
             if conectado else
             "Falta escanear el QR desde el celular que tiene el WhatsApp del "
             "negocio: Dispositivos vinculados → Vincular dispositivo.",
             "Conexiones → Conectar / Generar QR")
        listo = bridge_ok and conectado
    else:
        paso("Canal elegido", True, f"{perfil.name}.", "")
        # El token es de la app de Meta, uno para toda la plataforma; el
        # phone_number_id es de cada empresa.
        paso("Token de la app cargado", bool(WHATSAPP_TOKEN),
             "Definido en el servidor."
             if WHATSAPP_TOKEN else
             "Falta WHATSAPP_TOKEN en el .env del servidor. Sin eso no se "
             "puede responder ningún mensaje.",
             "servidor: .env → WHATSAPP_TOKEN")
        paso("Token de verificación del webhook", bool(WHATSAPP_VERIFY_TOKEN),
             "Definido."
             if WHATSAPP_VERIFY_TOKEN else
             "Falta WHATSAPP_VERIFY_TOKEN. Meta lo usa una sola vez, al dar de "
             "alta el webhook: sin él la verificación falla.",
             "servidor: .env → WHATSAPP_VERIFY_TOKEN")
        paso("Firma de la app (app secret)", bool(WHATSAPP_APP_SECRET),
             "Definido: cada mensaje entrante se valida."
             if WHATSAPP_APP_SECRET else
             "Falta WHATSAPP_APP_SECRET. El webhook RECHAZA todo hasta que "
             "esté: sin firma no hay forma de saber que el mensaje lo mandó "
             "Meta y no cualquiera que conozca la URL.",
             "servidor: .env → WHATSAPP_APP_SECRET")
        tiene_pnid = bool(company.wa_phone_number_id)
        paso("Número asignado a esta empresa", tiene_pnid,
             f"phone_number_id {company.wa_phone_number_id}."
             if tiene_pnid else
             "Falta el phone_number_id. Es lo que enruta cada mensaje a la "
             "empresa correcta: sin él no se sabe de quién es la conversación.",
             "Conexiones → phone_number_id")
        listo = all(p["ok"] for p in pasos)
        pasos.append({
            "paso": "Webhook configurado en Meta", "ok": None,
            "detalle": "Esto no se puede verificar desde acá: se comprueba "
                       "mandando un mensaje real al número.",
            "donde": "developers.facebook.com → tu app → WhatsApp → Configuración",
        })

    return {
        "mode": company.wa_mode,
        "canal": perfil.name,
        "oficial": perfil.official,
        "advertencia": perfil.warning,
        "listo": listo,
        "pasos": pasos,
        # Lo que el canal permite de verdad. El QR NO manda plantillas ni
        # campañas: prometerlo es lo que termina con el número restringido.
        "puede_enviar_proactivo": perfil.can(channels.Capability.SEND_PROACTIVE),
        "puede_plantillas": perfil.can(channels.Capability.SEND_TEMPLATE),
    }
