"""Pruebas de aislamiento entre tenants — obligatorias por release.

El principio: un usuario de la empresa A no puede ver ni tocar NADA de la
empresa B, aunque conozca su id. Y el aislamiento no depende de que cada
endpoint se acuerde de filtrar.
"""
from fastapi.testclient import TestClient

from tests.test_api import _create_company, app, client

from app.auth import hash_password
from app.db import SessionLocal
from app.models import Membership, User


def _make_user(email: str, company_id: int | None, role: str = "owner", platform: bool = False) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(
                email=email, password_hash=hash_password("clave-segura-123"),
                is_platform_admin=platform,
            )
            db.add(user)
            db.flush()
        if company_id:
            db.add(Membership(user_id=user.id, company_id=company_id, role=role))
        db.commit()
    finally:
        db.close()


def _login(email: str) -> TestClient:
    """Cliente autenticado como ese usuario (sin token de plataforma).

    base_url https porque la cookie de sesión es Secure: sobre http el
    cliente no la reenviaría (igual que un navegador real).
    """
    c = TestClient(app, base_url="https://testserver")
    resp = c.post("/api/auth/login", json={"email": email, "password": "clave-segura-123"})
    assert resp.status_code == 200, resp.text
    return c


def test_user_only_sees_own_company():
    a = _create_company(name="Empresa Aislada A")
    b = _create_company(name="Empresa Aislada B")
    _make_user("dueno-a@test.py", a["id"])

    ca = _login("dueno-a@test.py")
    visible = ca.get("/api/companies").json()
    ids = [c["id"] for c in visible]
    assert a["id"] in ids
    assert b["id"] not in ids  # jamás enumera tenants ajenos


def test_user_cannot_touch_other_tenant_data():
    a = _create_company(name="Tenant A Datos")
    b = _create_company(name="Tenant B Datos")
    _make_user("op-a@test.py", a["id"])
    # Datos sensibles en B
    doc = client.post(f"/api/companies/{b['id']}/doctors", json={"name": "Dr. Secreto"}).json()
    client.post(
        f"/api/companies/{b['id']}/appointments",
        json={"doctor_id": doc["id"], "patient_name": "Paciente Privado",
              "patient_phone": "+595971000000", "scheduled_at": "2030-01-01T10:00:00"},
    )

    ca = _login("op-a@test.py")
    # Lectura de datos ajenos: bloqueada en todos los módulos
    for path in (
        f"/api/companies/{b['id']}",
        f"/api/companies/{b['id']}/doctors",
        f"/api/companies/{b['id']}/appointments",
        f"/api/companies/{b['id']}/conversations",
        f"/api/companies/{b['id']}/agents",
        f"/api/companies/{b['id']}/products",
        f"/api/companies/{b['id']}/services",
        f"/api/companies/{b['id']}/reports",
        f"/api/companies/{b['id']}/dashboard",
    ):
        assert ca.get(path).status_code == 404, f"FUGA en {path}"

    # Escritura sobre el tenant ajeno: bloqueada
    assert ca.post(f"/api/companies/{b['id']}/doctors", json={"name": "Intruso"}).status_code == 404
    assert ca.patch(f"/api/companies/{b['id']}", json={"name": "Hackeada"}).status_code == 404
    assert ca.post(
        f"/api/companies/{b['id']}/chat",
        json={"contact_phone": "+595971111111", "text": "hola"},
    ).status_code == 404

    # Sobre su propia empresa sí puede
    assert ca.get(f"/api/companies/{a['id']}/doctors").status_code == 200


def test_new_endpoints_are_protected_by_construction():
    """El aislamiento está en el middleware, no en cada endpoint: cualquier
    ruta /api/companies/{id}/... queda cubierta aunque sea nueva."""
    a = _create_company(name="Cobertura A")
    b = _create_company(name="Cobertura B")
    _make_user("cobertura@test.py", a["id"])
    ca = _login("cobertura@test.py")
    # Ruta inexistente de otro tenant: corta en el middleware (404), sin llegar al router
    assert ca.get(f"/api/companies/{b['id']}/modulo-que-no-existe-todavia").status_code == 404


def test_platform_admin_sees_everything():
    a = _create_company(name="Plataforma A")
    b = _create_company(name="Plataforma B")
    _make_user("operador@test.py", None, platform=True)
    cp = _login("operador@test.py")
    ids = [c["id"] for c in cp.get("/api/companies").json()]
    assert a["id"] in ids and b["id"] in ids
    assert cp.get(f"/api/companies/{b['id']}/doctors").status_code == 200


def test_login_rejects_bad_password_and_unknown_email():
    _create_company(name="Empresa Login")
    _make_user("login@test.py", None)
    c = TestClient(app, base_url="https://testserver")
    assert c.post("/api/auth/login", json={"email": "login@test.py", "password": "incorrecta"}).status_code == 401
    assert c.post("/api/auth/login", json={"email": "no-existe@test.py", "password": "x"}).status_code == 401


def test_logout_revokes_session():
    company = _create_company(name="Empresa Logout")
    _make_user("logout@test.py", company["id"])
    c = _login("logout@test.py")
    assert c.get("/api/companies").status_code == 200
    c.post("/api/auth/logout")
    assert c.get("/api/companies").status_code == 401


def test_password_hashing_roundtrip():
    from app.auth import hash_password as h, verify_password as v

    stored = h("mi-clave-larga-123")
    assert stored.startswith("scrypt$")
    assert "mi-clave-larga-123" not in stored  # nunca en claro
    assert v("mi-clave-larga-123", stored)
    assert not v("otra-clave", stored)


def test_me_reports_memberships():
    company = _create_company(name="Empresa Me")
    _make_user("me@test.py", company["id"], role="admin")
    c = _login("me@test.py")
    data = c.get("/api/auth/me").json()
    assert data["user"]["email"] == "me@test.py"
    assert data["is_platform_admin"] is False
    assert data["memberships"][0]["company_id"] == company["id"]
    assert data["memberships"][0]["role"] == "admin"
