"""Tests de los fixes de la auditoría: SSRF, solapamiento de citas, timezone."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from tests.test_api import _create_company, client

from app import chat as chat_engine
from app.netguard import BlockedURLError, assert_public_url


# --- SSRF ---

@pytest.mark.parametrize("url", [
    "http://localhost:8000/api/companies",
    "http://127.0.0.1:3001/sessions/1/status",
    "http://169.254.169.254/latest/meta-data/",
    "http://192.168.1.1/",
    "http://10.0.0.5:8000/",
    "http://[::1]/",
    "file:///etc/passwd",
    "ftp://internal/",
])
def test_ssrf_blocks_internal_targets(url):
    with pytest.raises(BlockedURLError):
        assert_public_url(url)


def test_ssrf_allows_public_host():
    # No debe lanzar (resuelve a IP pública)
    assert_public_url("https://example.com")


def test_catalog_import_rejects_internal_url():
    company = _create_company("ecommerce", "Tienda SSRF")
    resp = client.post(
        f"/api/companies/{company['id']}/catalog/import",
        json={"website": "http://localhost:3001/sessions/1/status"},
    )
    assert resp.status_code in (422, 502)  # bloqueado, nunca 200


# --- Solapamiento de citas ---

def test_booking_rejects_overlap_not_only_exact(monkeypatch):
    """Regresión de auditoría: una cita a las 10:15 debe chocar con una de
    las 10:00 (solape de 30 min), no solo por igualdad exacta."""
    company = _create_company(name="Clínica Solape")
    cid = company["id"]
    doc = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dr. Solape"}).json()
    client.post(
        f"/api/companies/{cid}/appointments",
        json={"doctor_id": doc["id"], "patient_name": "Primero", "scheduled_at": "2030-10-01T10:00:00"},
    )

    async def book_at(dt):
        return {"content": None, "tool_calls": [{
            "id": "c1",
            "function": {"name": "book_appointment", "arguments": json.dumps({
                "doctor_id": doc["id"], "patient_name": "Segundo", "datetime_iso": dt,
            })},
        }]}

    async def fake_chat(messages, **kwargs):
        # Primera vuelta: intenta agendar. Segunda (ya con el resultado de la
        # herramienta): responde en texto.
        if not any(m.get("role") == "tool" for m in messages):
            return await book_at("2030-10-01T10:15")
        return {"content": "Ese horario se solapa con otra cita, ¿querés otro?"}

    monkeypatch.setattr(chat_engine, "chat_raw", fake_chat)
    resp = client.post(
        f"/api/companies/{cid}/chat", json={"contact_phone": "+595971000123", "text": "A las 10:15"}
    )
    result = resp.json()["actions"][0]["result"]
    assert "superpone" in result.get("error", "")
    # No se creó la segunda cita
    appts = client.get(f"/api/companies/{cid}/appointments", params={"doctor_id": doc["id"]}).json()
    assert len(appts) == 1


# --- Timezone de stats ---

def test_stats_window_uses_utc():
    """La ventana de stats debe basarse en UTC (no en hora local), para no
    quedar corrida por el offset de Asunción."""
    company = _create_company(name="Clínica TZ")
    cid = company["id"]
    doc = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dr. TZ"}).json()
    # Cita creada ahora → debe contar en la ventana de 7 días
    client.post(
        f"/api/companies/{cid}/appointments",
        json={"doctor_id": doc["id"], "patient_name": "Reciente",
              "scheduled_at": (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")},
    )
    stats = client.get(f"/api/companies/{cid}/stats").json()
    assert stats["appointments"]["total"] == 1
