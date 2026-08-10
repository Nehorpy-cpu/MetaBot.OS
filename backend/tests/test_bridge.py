"""Tests de la integración con el bridge Baileys (sin red ni WhatsApp)."""
from tests.test_api import _create_company, client

from app.routers import bridge as bridge_router


def test_bridge_incoming_requires_secret(monkeypatch):
    monkeypatch.setattr(bridge_router, "BRIDGE_SECRET", "super-secreto")
    resp = client.post(
        "/api/webhooks/bridge",
        json={"company_id": 1, "from": "+595971000000", "text": "hola"},
        headers={"X-Bridge-Secret": "equivocado"},
    )
    assert resp.status_code == 403


def test_bridge_incoming_replies_for_qr_company(monkeypatch):
    company = _create_company(name="PyME QR")
    cid = company["id"]
    client.patch(f"/api/companies/{cid}", json={"wa_mode": "qr"})

    async def fake_handle(db, company_obj, phone, text, contact_name="", channel="whatsapp", external_id=""):
        assert company_obj.id == cid
        assert phone == "+595971999888"
        assert contact_name == "Doña Rosa"
        return {"conversation_id": 5, "reply": "¡Hola Doña Rosa!", "status": "open", "actions": []}

    monkeypatch.setattr(bridge_router.chat_engine, "handle_incoming", fake_handle)
    monkeypatch.setattr(bridge_router, "BRIDGE_SECRET", "s3cr3t0")

    resp = client.post(
        "/api/webhooks/bridge",
        json={"company_id": cid, "from": "+595971999888", "name": "Doña Rosa", "text": "Precio?"},
        headers={"X-Bridge-Secret": "s3cr3t0"},
    )
    assert resp.status_code == 200
    assert resp.json()["reply"] == "¡Hola Doña Rosa!"


def test_bridge_incoming_rejected_if_mode_not_qr(monkeypatch):
    monkeypatch.setattr(bridge_router, "BRIDGE_SECRET", "")
    company = _create_company(name="Empresa Meta")
    resp = client.post(
        "/api/webhooks/bridge",
        json={"company_id": company["id"], "from": "+595971000001", "text": "hola"},
    )
    assert resp.status_code == 409


def test_wa_mode_validation():
    company = _create_company(name="Empresa Modo")
    cid = company["id"]
    ok = client.patch(f"/api/companies/{cid}", json={"wa_mode": "qr"})
    assert ok.status_code == 200
    assert ok.json()["wa_mode"] == "qr"
    bad = client.patch(f"/api/companies/{cid}", json={"wa_mode": "paloma-mensajera"})
    assert bad.status_code == 422


def test_wa_status_without_bridge_running(monkeypatch):
    """Si el bridge está caído, el panel recibe 502 con instrucción clara."""
    company = _create_company(name="Empresa SinBridge")
    cid = company["id"]
    client.patch(f"/api/companies/{cid}", json={"wa_mode": "qr"})
    monkeypatch.setattr(bridge_router, "BRIDGE_URL", "http://localhost:59999")
    resp = client.get(f"/api/companies/{cid}/wa/status")
    assert resp.status_code == 502
    assert "npm start" in resp.json()["detail"]


def test_wa_status_mode_none():
    company = _create_company(name="Empresa Sin Canal")
    resp = client.get(f"/api/companies/{company['id']}/wa/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "none"
    assert data["status"] == "n/a"
    # El estado del canal informa siempre qué puede hacer (capabilities)
    assert data["capabilities"] == ["can_reply", "can_send_media"]
    assert data["official"] is True
