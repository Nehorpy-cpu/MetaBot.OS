"""Suite obligatoria de resiliencia de canal (lecciones de Credipower).

Cada release debe pasar: duplicación de mensajes de WhatsApp, replay de
webhook, dos workers sobre la misma sesión, reserva simultánea del mismo
horario.
"""
import hashlib
import hmac
import json

from tests.test_api import _create_company, client, drenar_cola, post_webhook

from app import chat as chat_engine
from app import sessions
from app.db import SessionLocal
from app.models import AgentRun, Message
from app.routers import whatsapp_webhook


def _mock_reply(monkeypatch, texto="¡Hola! ¿En qué te ayudo?"):
    llamadas = {"n": 0}

    async def fake_chat(messages, **kwargs):
        llamadas["n"] += 1
        return {"content": texto}

    monkeypatch.setattr(chat_engine, "chat_raw", fake_chat)
    return llamadas


# --- Duplicación de mensajes de WhatsApp ---

def test_same_whatsapp_message_is_processed_once(monkeypatch):
    """WhatsApp reentrega mensajes al reconectar: el bot no debe responder
    dos veces ni cobrar dos llamadas al modelo."""
    company = _create_company(name="Dedup Empresa")
    cid = company["id"]
    llamadas = _mock_reply(monkeypatch)

    payload = {"contact_phone": "+595971010101", "text": "Hola", "external_id": "wamid.ABC123"}
    primera = client.post(f"/api/companies/{cid}/chat", json=payload).json()
    segunda = client.post(f"/api/companies/{cid}/chat", json=payload).json()

    assert primera["reply"] == "¡Hola! ¿En qué te ayudo?"
    assert segunda.get("duplicate") is True
    assert segunda["reply"] == primera["reply"]  # devuelve la respuesta previa
    assert llamadas["n"] == 1, "el modelo se llamó dos veces por una reentrega"

    db = SessionLocal()
    try:
        entrantes = (
            db.query(Message)
            .filter(Message.company_id == cid, Message.direction == "in")
            .count()
        )
    finally:
        db.close()
    assert entrantes == 1  # el mensaje se guardó una sola vez


def test_dedup_is_per_company(monkeypatch):
    """Dos empresas pueden recibir mensajes con el mismo id sin pisarse."""
    a = _create_company(name="Dedup A")
    b = _create_company(name="Dedup B")
    _mock_reply(monkeypatch)
    payload = {"contact_phone": "+595971020202", "text": "Hola", "external_id": "wamid.MISMO"}
    ra = client.post(f"/api/companies/{a['id']}/chat", json=payload).json()
    rb = client.post(f"/api/companies/{b['id']}/chat", json=payload).json()
    assert not ra.get("duplicate") and not rb.get("duplicate")


def test_booking_not_duplicated_on_message_redelivery(monkeypatch):
    """El caso caro: una reentrega no puede generar una segunda cita."""
    company = _create_company(name="Dedup Citas")
    cid = company["id"]
    doc = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dra. Única"}).json()

    async def fake_chat(messages, **kwargs):
        if not any(m.get("role") == "tool" for m in messages):
            return {"content": None, "tool_calls": [{
                "id": "c1",
                "function": {"name": "book_appointment", "arguments": json.dumps({
                    "doctor_id": doc["id"], "patient_name": "Ana",
                    "datetime_iso": "2030-11-11T10:00",
                })},
            }]}
        return {"content": "¡Listo Ana!"}

    monkeypatch.setattr(chat_engine, "chat_raw", fake_chat)
    payload = {"contact_phone": "+595971030303", "text": "Confirmo", "external_id": "wamid.CITA"}
    client.post(f"/api/companies/{cid}/chat", json=payload)
    client.post(f"/api/companies/{cid}/chat", json=payload)  # reentrega

    citas = client.get(f"/api/companies/{cid}/appointments", params={"doctor_id": doc["id"]}).json()
    assert len(citas) == 1, "la reentrega duplicó la cita"


# --- Replay de webhook de Meta ---

def test_meta_webhook_replay_does_not_duplicate(monkeypatch):
    """Meta reenvía el webhook si no recibe 200 a tiempo."""
    company = _create_company(name="Replay Meta")
    cid = company["id"]
    client.patch(f"/api/companies/{cid}", json={"wa_mode": "meta", "wa_phone_number_id": "PN-REPLAY"})
    _mock_reply(monkeypatch)

    enviados = []

    async def fake_send(pnid, to, text):
        enviados.append(text)
        return {"sent": True}

    from app import whatsapp as whatsapp_mod

    monkeypatch.setattr(whatsapp_mod, "send_text", fake_send)

    payload = {"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": "PN-REPLAY"},
        "contacts": [{"wa_id": "595971040404", "profile": {"name": "Luis"}}],
        "messages": [{"id": "wamid.REPLAY1", "from": "595971040404",
                      "type": "text", "text": {"body": "Hola"}}],
    }}]}]}

    # Meta reenvía el webhook cuando no recibe el 200 a tiempo. La reentrega
    # tiene que morir en el dedup de la cola: si no, el cliente recibe dos
    # respuestas y, peor, se le agenda dos veces.
    post_webhook(payload)
    post_webhook(payload)  # replay
    drenar_cola()

    assert len(enviados) == 1, "el replay del webhook mandó una segunda respuesta"


# --- Dos workers sobre la misma sesión ---

def test_second_worker_cannot_take_live_session():
    """Dos procesos usando la misma sesión de WhatsApp la corrompen."""
    company = _create_company(name="Lease Empresa")
    cid = company["id"]
    db = SessionLocal()
    try:
        assert sessions.acquire(db, cid, "worker-1") is True
        assert sessions.acquire(db, cid, "worker-2") is False  # el 1 está vivo
        assert sessions.acquire(db, cid, "worker-1") is True   # renueva el suyo

        # El dueño late; el intruso no puede
        assert sessions.heartbeat(db, cid, "worker-1", status="connected") is True
        assert sessions.heartbeat(db, cid, "worker-2") is False

        # Si el dueño libera, otro worker puede tomarla
        sessions.release(db, cid, "worker-1")
        assert sessions.acquire(db, cid, "worker-2") is True
    finally:
        db.close()


def test_expired_lease_can_be_taken_over():
    """Si el worker muere, el lease vence y otro puede tomar la sesión."""
    from datetime import datetime, timedelta, timezone

    from app.models import ChannelSession

    company = _create_company(name="Lease Vencido")
    cid = company["id"]
    db = SessionLocal()
    try:
        sessions.acquire(db, cid, "worker-muerto")
        s = db.query(ChannelSession).filter(ChannelSession.company_id == cid).first()
        s.lease_until = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)
        db.commit()
        assert sessions.acquire(db, cid, "worker-nuevo") is True
    finally:
        db.close()


# --- Métricas por ejecución ---

def test_agent_run_is_recorded(monkeypatch):
    """Cada respuesta deja su métrica: sin esto 'el bot mejoró' es opinión."""
    company = _create_company(name="Métricas Empresa")
    cid = company["id"]
    _mock_reply(monkeypatch, "Respuesta medida")
    client.post(f"/api/companies/{cid}/chat",
                json={"contact_phone": "+595971050505", "text": "¿Precio?"})

    db = SessionLocal()
    try:
        run = db.query(AgentRun).filter(AgentRun.company_id == cid).first()
    finally:
        db.close()
    assert run is not None
    assert run.agent_slug == "cx"
    assert run.question == "¿Precio?"
    assert run.answer == "Respuesta medida"
    assert run.latency_ms >= 0
    assert run.escalated is False
    assert run.booked is False


def test_agent_run_marks_escalation_and_booking(monkeypatch):
    company = _create_company(name="Métricas Acciones")
    cid = company["id"]

    async def fake_chat(messages, **kwargs):
        if not any(m.get("role") == "tool" for m in messages):
            return {"content": None, "tool_calls": [{
                "id": "c1",
                "function": {"name": "escalate_to_human", "arguments": '{"reason": "urgencia"}'},
            }]}
        return {"content": "Ya aviso al equipo."}

    monkeypatch.setattr(chat_engine, "chat_raw", fake_chat)
    client.post(f"/api/companies/{cid}/chat",
                json={"contact_phone": "+595971060606", "text": "Necesito un humano"})

    db = SessionLocal()
    try:
        run = db.query(AgentRun).filter(AgentRun.company_id == cid).order_by(AgentRun.id.desc()).first()
    finally:
        db.close()
    assert run.escalated is True
    assert "escalate_to_human" in run.tools_used
