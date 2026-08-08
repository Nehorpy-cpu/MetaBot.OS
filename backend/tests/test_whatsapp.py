"""Tests del webhook de WhatsApp, recordatorios e iCalendar (sin red)."""
import hashlib
import hmac
import json

from tests.test_api import _create_company, client

from app import chat as chat_engine
from app.routers import whatsapp_webhook
from app.routers import medical as medical_router


def _wa_payload(phone_number_id: str, wa_from: str, text: str, name: str = "Test User") -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": phone_number_id},
                            "contacts": [{"wa_id": wa_from, "profile": {"name": name}}],
                            "messages": [
                                {"from": wa_from, "type": "text", "text": {"body": text}}
                            ],
                        }
                    }
                ]
            }
        ]
    }


def test_webhook_verification_challenge(monkeypatch):
    monkeypatch.setattr(whatsapp_webhook, "WHATSAPP_VERIFY_TOKEN", "mi-token-secreto")
    resp = client.get(
        "/api/webhooks/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "mi-token-secreto",
            "hub.challenge": "12345",
        },
    )
    assert resp.status_code == 200
    assert resp.text == "12345"

    bad = client.get(
        "/api/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "otro", "hub.challenge": "x"},
    )
    assert bad.status_code == 403


def test_webhook_rejects_bad_signature(monkeypatch):
    monkeypatch.setattr(whatsapp_webhook, "WHATSAPP_APP_SECRET", "appsecret")
    body = json.dumps(_wa_payload("999", "595971000000", "hola")).encode()
    resp = client.post(
        "/api/webhooks/whatsapp",
        content=body,
        headers={"X-Hub-Signature-256": "sha256=firmafalsa", "Content-Type": "application/json"},
    )
    assert resp.status_code == 403


def test_webhook_routes_message_to_tenant_and_replies(monkeypatch):
    company = _create_company(name="Clínica WA")
    cid = company["id"]
    client.patch(f"/api/companies/{cid}", json={"wa_phone_number_id": "PNID-777"})

    async def fake_handle(db, company_obj, phone, text, contact_name="", channel="whatsapp"):
        assert company_obj.id == cid
        assert phone == "+595971234567"
        assert text == "Hola, quiero un turno"
        assert contact_name == "Juan Pérez"
        return {"conversation_id": 1, "reply": "¡Hola Juan!", "status": "open", "actions": []}

    sent = []

    async def fake_send(phone_number_id, to, text):
        sent.append({"pnid": phone_number_id, "to": to, "text": text})
        return {"sent": True}

    monkeypatch.setattr(whatsapp_webhook.chat_engine, "handle_incoming", fake_handle)
    monkeypatch.setattr(whatsapp_webhook.whatsapp, "send_text", fake_send)
    monkeypatch.setattr(whatsapp_webhook, "WHATSAPP_APP_SECRET", "secreto")

    body = json.dumps(_wa_payload("PNID-777", "595971234567", "Hola, quiero un turno", "Juan Pérez")).encode()
    sig = "sha256=" + hmac.new(b"secreto", body, hashlib.sha256).hexdigest()
    resp = client.post(
        "/api/webhooks/whatsapp",
        content=body,
        headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert sent == [{"pnid": "PNID-777", "to": "595971234567", "text": "¡Hola Juan!"}]


def test_webhook_unknown_tenant_ignored(monkeypatch):
    monkeypatch.setattr(whatsapp_webhook, "WHATSAPP_APP_SECRET", "")
    called = []

    async def fake_handle(*a, **k):
        called.append(1)
        return {}

    monkeypatch.setattr(whatsapp_webhook.chat_engine, "handle_incoming", fake_handle)
    body = json.dumps(_wa_payload("PNID-INEXISTENTE", "595970000000", "hola")).encode()
    resp = client.post("/api/webhooks/whatsapp", content=body, headers={"Content-Type": "application/json"})
    assert resp.status_code == 200  # Meta siempre recibe 200
    assert not called


def test_reminders_for_date():
    company = _create_company(name="Clínica Recordatorios")
    cid = company["id"]
    doc = client.post(
        f"/api/companies/{cid}/doctors", json={"name": "Dra. Recuerdo", "specialty": "Clínica"}
    ).json()
    client.post(
        f"/api/companies/{cid}/appointments",
        json={
            "doctor_id": doc["id"],
            "patient_name": "Paciente Recordado",
            "patient_phone": "+595971555666",
            "scheduled_at": "2030-03-20T10:30:00",
        },
    )
    # cita cancelada: no debe generar recordatorio
    appt2 = client.post(
        f"/api/companies/{cid}/appointments",
        json={
            "doctor_id": doc["id"],
            "patient_name": "Cancelado",
            "scheduled_at": "2030-03-20T11:00:00",
        },
    ).json()
    client.patch(f"/api/companies/{cid}/appointments/{appt2['id']}", json={"status": "cancelled"})

    data = client.get(f"/api/companies/{cid}/reminders", params={"on_date": "2030-03-20"}).json()
    assert data["count"] == 1
    r = data["reminders"][0]
    assert r["patient_name"] == "Paciente Recordado"
    assert "10:30" in r["text"]
    assert "Dra. Recuerdo" in r["text"]


def test_send_reminders_dry_run(monkeypatch):
    company = _create_company(name="Clínica Envíos")
    cid = company["id"]
    doc = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dr. Envío"}).json()
    client.post(
        f"/api/companies/{cid}/appointments",
        json={
            "doctor_id": doc["id"],
            "patient_name": "Con Tel",
            "patient_phone": "+595971777888",
            "scheduled_at": "2030-04-01T09:00:00",
        },
    )

    sent = []

    async def fake_send(pnid, to, text):
        sent.append(to)
        return {"sent": True}

    monkeypatch.setattr(medical_router.whatsapp, "send_text", fake_send)
    resp = client.post(f"/api/companies/{cid}/reminders/send", params={"on_date": "2030-04-01"})
    assert resp.status_code == 200
    assert sent == ["+595971777888"]


def test_doctor_calendar_ics():
    company = _create_company(name="Clínica ICS")
    cid = company["id"]
    doc = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dra. Cal"}).json()
    client.post(
        f"/api/companies/{cid}/appointments",
        json={
            "doctor_id": doc["id"],
            "patient_name": "Evento Uno",
            "scheduled_at": "2030-05-05T14:00:00",
            "notes": "Control",
        },
    )
    resp = client.get(f"/api/companies/{cid}/doctors/{doc['id']}/calendar.ics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/calendar")
    body = resp.text
    assert "BEGIN:VCALENDAR" in body
    assert "SUMMARY:Cita: Evento Uno — Control" in body
    assert "DTSTART;TZID=America/Asuncion:20300505T140000" in body
    assert body.strip().endswith("END:VCALENDAR")
