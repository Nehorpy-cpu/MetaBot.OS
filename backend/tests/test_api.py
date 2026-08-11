import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["ADMIN_TOKEN"] = "test-token-secreto"
os.environ["SCHEDULER_ENABLED"] = "0"
# El webhook de Meta falla CERRADO sin este secreto. Configurarlo acá hace que
# las pruebas firmen sus cargas y ejerciten la validación de verdad, en vez de
# saltearla.
os.environ["WHATSAPP_APP_SECRET"] = "secreto-de-prueba"
os.environ["WHATSAPP_VERIFY_TOKEN"] = "verify-de-prueba"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import StaticPool, create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app import db as db_module  # noqa: E402
from app.db import Base  # noqa: E402

# Motor en memoria compartido entre conexiones para los tests
engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
db_module.engine = engine
db_module.SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

from app.main import app  # noqa: E402

Base.metadata.create_all(bind=engine)
# Todos los tests van autenticados por defecto (el token va en cada request).
client = TestClient(app, headers={"Authorization": "Bearer test-token-secreto"})


def _create_company(vertical="medical", name="Clínica Test"):
    resp = client.post("/api/companies", json={"name": name, "vertical": vertical})
    assert resp.status_code == 201
    return resp.json()


def test_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_health_is_public():
    """Health y webhooks no requieren token."""
    resp = client.get("/api/health", headers={"Authorization": ""})
    assert resp.status_code == 200


def test_api_requires_token():
    """Sin token, cualquier endpoint de datos responde 401 (cierra BOLA/IDOR)."""
    noauth = TestClient(app)
    assert noauth.get("/api/companies").status_code == 401
    assert noauth.post("/api/companies", json={"name": "X", "vertical": "medical"}).status_code == 401
    assert noauth.get("/api/companies/1/conversations").status_code == 401
    # con token correcto, pasa
    ok = noauth.get("/api/companies", headers={"Authorization": "Bearer test-token-secreto"})
    assert ok.status_code == 200


def test_api_rejects_wrong_token():
    noauth = TestClient(app, headers={"Authorization": "Bearer token-equivocado"})
    assert noauth.get("/api/companies").status_code == 401


SWARM_SLUGS = {"ceo", "quant", "guard", "creative", "visual", "cx", "optimizer"}


def test_create_medical_company_seeds_seven_agents():
    company = _create_company()
    assert company["niche"].startswith("Clínica")

    agents = client.get(f"/api/companies/{company['id']}/agents").json()
    assert len(agents) == 7
    assert {a["slug"] for a in agents} == SWARM_SLUGS
    # El system prompt NO debe exponerse en el listado público
    assert "system_prompt" not in agents[0]


def test_create_ecommerce_company():
    company = _create_company("ecommerce", "Tienda Test")
    agents = client.get(f"/api/companies/{company['id']}/agents").json()
    assert len(agents) == 7


def test_invalid_vertical_rejected():
    resp = client.post("/api/companies", json={"name": "X", "vertical": "banking"})
    assert resp.status_code == 422


def test_company_not_found():
    assert client.get("/api/companies/99999").status_code == 404
    assert client.get("/api/companies/99999/agents").status_code == 404


# --- Super-Configurator ---

def test_agent_update_prompt_and_temperature():
    company = _create_company()
    agents = client.get(f"/api/companies/{company['id']}/agents").json()
    ceo = next(a for a in agents if a["slug"] == "ceo")

    detail = client.get(f"/api/agents/{ceo['id']}").json()
    assert "voseo" in detail["system_prompt"]

    resp = client.patch(
        f"/api/agents/{ceo['id']}",
        json={"temperature": 0.7, "system_prompt": "Nuevo prompt de prueba"},
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["temperature"] == 0.7
    assert updated["system_prompt"] == "Nuevo prompt de prueba"


def test_agent_temperature_out_of_range_rejected():
    company = _create_company()
    agents = client.get(f"/api/companies/{company['id']}/agents").json()
    resp = client.patch(f"/api/agents/{agents[0]['id']}", json={"temperature": 5.0})
    assert resp.status_code == 422


# --- Módulo médico ---

def test_doctors_and_appointments_flow():
    company = _create_company()
    cid = company["id"]

    doc = client.post(
        f"/api/companies/{cid}/doctors",
        json={"name": "Dr. Test Pérez", "specialty": "Cardiología", "phone": "+595 981 000111"},
    ).json()

    appt = client.post(
        f"/api/companies/{cid}/appointments",
        json={
            "doctor_id": doc["id"],
            "patient_name": "Paciente Uno",
            "patient_phone": "+595 971 222333",
            "scheduled_at": "2026-08-10T09:00:00",
            "notes": "Control",
        },
    )
    assert appt.status_code == 201

    listed = client.get(f"/api/companies/{cid}/appointments", params={"doctor_id": doc["id"]}).json()
    assert len(listed) == 1
    assert listed[0]["patient_name"] == "Paciente Uno"

    resp = client.patch(
        f"/api/companies/{cid}/appointments/{listed[0]['id']}", json={"status": "confirmed"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmed"

    resp = client.patch(
        f"/api/companies/{cid}/appointments/{listed[0]['id']}", json={"status": "inventado"}
    )
    assert resp.status_code == 422


def test_daily_summary_only_includes_own_doctor_appointments():
    """Regresión del bug del prototipo: la agenda de un doctor no debe
    incluir pacientes de otros doctores."""
    company = _create_company()
    cid = company["id"]
    doc_a = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dra. A"}).json()
    doc_b = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dr. B"}).json()

    for doc, patient in ((doc_a, "Paciente De A"), (doc_b, "Paciente De B")):
        client.post(
            f"/api/companies/{cid}/appointments",
            json={
                "doctor_id": doc["id"],
                "patient_name": patient,
                "scheduled_at": "2026-08-10T10:00:00",
            },
        )

    summary = client.get(
        f"/api/companies/{cid}/doctors/{doc_a['id']}/daily-summary",
        params={"on_date": "2026-08-10"},
    ).json()
    assert summary["count"] == 1
    assert "Paciente De A" in summary["text"]
    assert "Paciente De B" not in summary["text"]


def test_appointment_requires_doctor_of_same_company():
    company_a = _create_company(name="Clínica A")
    company_b = _create_company(name="Clínica B")
    doc_b = client.post(f"/api/companies/{company_b['id']}/doctors", json={"name": "Dr. Ajeno"}).json()

    resp = client.post(
        f"/api/companies/{company_a['id']}/appointments",
        json={"doctor_id": doc_b["id"], "patient_name": "X", "scheduled_at": "2026-08-10T09:00:00"},
    )
    assert resp.status_code == 404


# --- Glosario jopara ---

def test_glossary_crud_and_duplicate_rejected():
    company = _create_company()
    cid = company["id"]
    resp = client.post(
        f"/api/companies/{cid}/glossary",
        json={"heard": "mbarete", "corrected": "mbarete", "meaning": "fuerte, con fuerza"},
    )
    assert resp.status_code == 201

    dup = client.post(
        f"/api/companies/{cid}/glossary",
        json={"heard": "mbarete", "corrected": "otra"},
    )
    assert dup.status_code == 409

    terms = client.get(f"/api/companies/{cid}/glossary").json()
    assert len(terms) == 1


# --- Dashboard ---

def test_dashboard_counts():
    company = _create_company()
    cid = company["id"]
    data = client.get(f"/api/companies/{cid}/dashboard").json()
    assert data["agents_total"] == 7
    assert data["agents_active"] == 7
    assert data["doctors"] == 0
    assert data["company"]["vertical"] == "medical"


# --- Webhook de Meta: firmar y drenar ---


def firmar_webhook(body: bytes) -> dict:
    """Cabeceras con la firma HMAC que Meta manda en cada POST."""
    import hashlib
    import hmac

    firma = hmac.new(b"secreto-de-prueba", body, hashlib.sha256).hexdigest()
    return {"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={firma}"}


def post_webhook(payload: dict):
    """POST al webhook con firma válida, como lo haría Meta."""
    import json as _json

    body = _json.dumps(payload).encode()
    return client.post("/api/webhooks/whatsapp", content=body, headers=firmar_webhook(body))


def drenar_cola() -> int:
    """Corre los trabajos pendientes.

    El webhook ENCOLA y responde 200 al toque —Meta reintenta si tarda—, así
    que las pruebas que verifican la respuesta del bot tienen que correr el
    worker a mano.
    """
    import asyncio

    from app import jobs

    return asyncio.run(jobs.process_due("worker-de-prueba", limit=50))
