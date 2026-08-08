import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

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
client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_create_medical_company_seeds_six_agents():
    resp = client.post("/companies", json={"name": "Clínica Test", "vertical": "medical"})
    assert resp.status_code == 201
    company = resp.json()
    assert company["niche"].startswith("Clínica")

    agents = client.get(f"/companies/{company['id']}/agents").json()
    assert len(agents) == 6
    assert {a["slug"] for a in agents} == {"ceo", "quant", "guard", "creative", "visual", "cx"}
    # El system prompt NO debe exponerse en la API pública
    assert "system_prompt" not in agents[0]


def test_create_ecommerce_company():
    resp = client.post("/companies", json={"name": "Tienda Test", "vertical": "ecommerce"})
    assert resp.status_code == 201
    agents = client.get(f"/companies/{resp.json()['id']}/agents").json()
    assert len(agents) == 6


def test_invalid_vertical_rejected():
    resp = client.post("/companies", json={"name": "X", "vertical": "banking"})
    assert resp.status_code == 422


def test_company_not_found():
    assert client.get("/companies/99999").status_code == 404
    assert client.get("/companies/99999/agents").status_code == 404
