"""Tests de la base de servicios y su integración al CX Bot."""
import json

from tests.test_api import _create_company, client

from app import chat as chat_engine


def _setup(cid):
    doc = client.post(
        f"/api/companies/{cid}/doctors", json={"name": "Dr. Eco Grafía", "specialty": "Imágenes"}
    ).json()
    svc = client.post(
        f"/api/companies/{cid}/services",
        json={
            "name": "Ecografía abdominal",
            "category": "Estudios",
            "price_gs": 250000,
            "duration_min": 40,
            "doctor_ids": [doc["id"]],
        },
    ).json()
    return doc, svc


def test_service_crud_with_doctors():
    company = _create_company(name="Sanatorio Servicios")
    cid = company["id"]
    doc, svc = _setup(cid)
    assert svc["doctors"][0]["name"] == "Dr. Eco Grafía"

    dup = client.post(f"/api/companies/{cid}/services", json={"name": "Ecografía abdominal"})
    assert dup.status_code == 409

    upd = client.patch(
        f"/api/companies/{cid}/services/{svc['id']}", json={"price_gs": 300000, "doctor_ids": []}
    ).json()
    assert upd["price_gs"] == 300000
    assert upd["doctors"] == []

    bad = client.post(
        f"/api/companies/{cid}/services",
        json={"name": "Rayos X", "doctor_ids": [99999]},
    )
    assert bad.status_code == 422

    assert client.delete(f"/api/companies/{cid}/services/{svc['id']}").status_code == 204
    assert client.get(f"/api/companies/{cid}/services").json() == []


def test_bot_lists_services_with_real_prices(monkeypatch):
    company = _create_company(name="Sanatorio Precios")
    cid = company["id"]
    _setup(cid)

    captured = {}

    async def fake_chat(messages, tools=None, **kwargs):
        captured.setdefault("system", messages[0]["content"])
        captured.setdefault("tools", [t["function"]["name"] for t in (tools or [])])
        if not any(m.get("role") == "tool" for m in messages):
            return {
                "content": None,
                "tool_calls": [
                    {"id": "c1", "function": {"name": "list_services", "arguments": json.dumps({"category": "Estudios"})}}
                ],
            }
        tool_result = json.loads(next(m for m in messages if m.get("role") == "tool")["content"])
        captured["tool_result"] = tool_result
        return {"content": f"La ecografía sale {tool_result['services'][0]['price']}"}

    monkeypatch.setattr(chat_engine, "chat_raw", fake_chat)
    resp = client.post(
        f"/api/companies/{cid}/chat",
        json={"contact_phone": "+595971414141", "text": "¿Cuánto sale la ecografía?"},
    )
    # El system prompt anuncia el servicio y prohíbe inventar precios
    assert "Ecografía abdominal" in captured["system"]
    assert "NUNCA inventes servicios" in captured["system"]
    assert "list_services" in captured["tools"]
    # La herramienta devolvió precio formateado y el profesional que atiende
    svc = captured["tool_result"]["services"][0]
    assert svc["price"] == "₲ 250.000"
    assert svc["attended_by"] == ["Dr. Eco Grafía"]
    assert "₲ 250.000" in resp.json()["reply"]


def test_service_price_zero_is_consultar():
    company = _create_company(name="Sanatorio Consultar")
    cid = company["id"]
    client.post(f"/api/companies/{cid}/services", json={"name": "Cirugía compleja"})
    from app.chat import _fmt_gs

    assert _fmt_gs(0) == "consultar"
    assert _fmt_gs(1500000) == "₲ 1.500.000"
