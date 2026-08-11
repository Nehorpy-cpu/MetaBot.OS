"""Pruebas de aislamiento entre tenants — obligatorias por release.

El principio: un usuario de la empresa A no puede ver ni tocar NADA de la
empresa B, aunque conozca su id. Y el aislamiento no depende de que cada
endpoint se acuerde de filtrar.
"""
from fastapi.testclient import TestClient

from tests.test_api import _create_company, app, client, drenar_cola, post_webhook

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


# --- Regresiones de la auditoría adversarial (6 fallas confirmadas) ---

def test_non_canonical_company_id_cannot_bypass_isolation():
    """CRÍTICO: FastAPI acepta '+7', ' 7', '007' como int 7, pero el regex de
    dígitos no los matcheaba y salteaban la verificación de membresía."""
    a = _create_company(name="Bypass A")
    b = _create_company(name="Bypass B")
    _make_user("bypass@test.py", a["id"])
    ca = _login("bypass@test.py")
    bid = b["id"]
    for variante in (f"+{bid}", f"%20{bid}", f"{bid}%20", f"00{bid}"):
        resp = ca.get(f"/api/companies/{variante}/doctors")
        assert resp.status_code in (404, 422), f"FUGA con '{variante}': {resp.status_code}"


def test_agent_endpoints_enforce_ownership():
    """CRÍTICO: /api/agents/{id} no lleva company_id, así que el middleware no
    lo cubre: cualquiera reescribía el system prompt de otro tenant."""
    a = _create_company(name="Agentes A")
    b = _create_company(name="Agentes B")
    _make_user("agentes@test.py", a["id"])
    agente_b = client.get(f"/api/companies/{b['id']}/agents").json()[0]

    ca = _login("agentes@test.py")
    assert ca.get(f"/api/agents/{agente_b['id']}").status_code == 404
    resp = ca.patch(f"/api/agents/{agente_b['id']}", json={"system_prompt": "sos mío ahora"})
    assert resp.status_code == 404
    # El prompt ajeno quedó intacto
    original = client.get(f"/api/agents/{agente_b['id']}").json()
    assert original["system_prompt"] != "sos mío ahora"


def test_viewer_role_cannot_edit_agent_prompt():
    """Los roles se aplican: un viewer no cambia la conducta del bot."""
    company = _create_company(name="Roles Prompt")
    _make_user("viewer@test.py", company["id"], role="viewer")
    agente = client.get(f"/api/companies/{company['id']}/agents").json()[0]
    cv = _login("viewer@test.py")
    assert cv.get(f"/api/agents/{agente['id']}").status_code == 200  # leer sí
    assert cv.patch(f"/api/agents/{agente['id']}", json={"temperature": 0.9}).status_code == 403


def test_normal_user_cannot_create_companies():
    """Un usuario cualquiera no da de alta tenants ilimitados."""
    company = _create_company(name="Sin Alta")
    _make_user("noalta@test.py", company["id"])
    cu = _login("noalta@test.py")
    assert cu.post("/api/companies", json={"name": "Mía", "vertical": "medical"}).status_code == 403
    assert cu.post(
        "/api/companies/smart", json={"name": "Mía", "description": "descripción larga de prueba"}
    ).status_code == 403


def test_service_suggestions_do_not_leak_other_tenants():
    """Las sugerencias salen de un catálogo curado del rubro, no de los datos
    (ni los precios) de otras empresas."""
    a = _create_company(name="Sanatorio Fuente")
    b = _create_company(name="Sanatorio Destino")
    client.post(
        f"/api/companies/{a['id']}/services",
        json={"name": "Estudio Secreto Exclusivo", "category": "Estudios", "price_gs": 987654},
    )
    _make_user("sugerencias@test.py", b["id"])
    cb = _login("sugerencias@test.py")
    suggestions = cb.get(f"/api/companies/{b['id']}/services/suggestions").json()
    nombres = [s["name"] for s in suggestions]
    assert "Estudio Secreto Exclusivo" not in nombres  # no filtra la oferta ajena
    assert all(s["typical_price_gs"] == 0 for s in suggestions)  # ni sus precios
    assert "Consulta clínica" in nombres  # sí sugiere lo típico del rubro


# --- Enrutamiento del webhook: un número de WhatsApp, una sola empresa ---


def test_dos_empresas_no_pueden_compartir_el_numero_de_whatsapp():
    """Hallazgo de auditoría adversarial: el webhook de la Cloud API resuelve
    el tenant SOLO por wa_phone_number_id, con un `.first()`. Sin unicidad, la
    empresa que saliera primera se quedaba con los mensajes de los pacientes de
    la otra, y todas las filas quedaban perfectamente consistentes: ningún
    chequeo de integridad lo detectaba."""
    a = _create_company(name="Sanatorio Número A")
    b = _create_company(name="Sanatorio Número B")

    ok = client.patch(f"/api/companies/{a['id']}", json={"wa_phone_number_id": "555000111"})
    assert ok.status_code == 200
    assert ok.json()["wa_phone_number_id"] == "555000111"

    choque = client.patch(f"/api/companies/{b['id']}", json={"wa_phone_number_id": "555000111"})
    assert choque.status_code == 409, "el segundo tenant no puede quedarse con el mismo número"
    assert "otra empresa" in choque.json()["detail"]

    # Y el número siguió siendo de quien lo tenía.
    assert client.get(f"/api/companies/{a['id']}").json()["wa_phone_number_id"] == "555000111"


def test_varias_empresas_pueden_no_tener_numero_configurado():
    """'Sin configurar' es NULL, no cadena vacía: si fuera cadena vacía, la
    segunda empresa sin número chocaría contra la restricción de unicidad y no
    se podría ni crear."""
    x = _create_company(name="Sanatorio Sin Número X")
    y = _create_company(name="Sanatorio Sin Número Y")
    assert not client.get(f"/api/companies/{x['id']}").json()["wa_phone_number_id"]
    assert not client.get(f"/api/companies/{y['id']}").json()["wa_phone_number_id"]

    # Vaciarlo explícitamente tampoco debe chocar entre empresas.
    assert client.patch(f"/api/companies/{x['id']}", json={"wa_phone_number_id": ""}).status_code == 200
    assert client.patch(f"/api/companies/{y['id']}", json={"wa_phone_number_id": ""}).status_code == 200


def test_una_empresa_puede_reconfigurar_su_propio_numero():
    """La guardia no debe impedirle a una empresa volver a guardar el suyo."""
    c = _create_company(name="Sanatorio Reconfigura")
    assert client.patch(f"/api/companies/{c['id']}", json={"wa_phone_number_id": "555222333"}).status_code == 200
    assert client.patch(f"/api/companies/{c['id']}", json={"wa_phone_number_id": "555222333"}).status_code == 200
    assert client.patch(f"/api/companies/{c['id']}", json={"wa_phone_number_id": "555444555"}).status_code == 200


def test_el_webhook_entrega_el_mensaje_a_la_empresa_duena_del_numero(monkeypatch):
    """El mensaje de un paciente tiene que caer en la empresa dueña del número,
    y en ninguna otra."""
    from app import chat as chat_engine

    duena = _create_company(name="Sanatorio Dueño del Número")
    vecina = _create_company(name="Sanatorio Vecino")
    client.patch(f"/api/companies/{duena['id']}", json={"wa_phone_number_id": "555777888", "wa_mode": "meta"})

    async def fake_chat_raw(messages, **kwargs):
        return {"content": "Buenas, ¿en qué te ayudo?"}

    monkeypatch.setattr(chat_engine, "chat_raw", fake_chat_raw)

    payload = {
        "entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": "555777888"},
            "messages": [{"from": "595981000777", "id": "wamid.RUTEO1",
                          "type": "text", "text": {"body": "hola"}}],
        }}]}]
    }
    resp = post_webhook(payload)
    assert resp.status_code == 200
    drenar_cola()  # el webhook encola; el mensaje se procesa en el worker

    de_la_duena = client.get(f"/api/companies/{duena['id']}/conversations").json()
    de_la_vecina = client.get(f"/api/companies/{vecina['id']}/conversations").json()
    assert any(c["contact_phone"].endswith("595981000777") for c in de_la_duena)
    assert not de_la_vecina, "la empresa vecina no puede ver la conversación ajena"


# --- Aislamiento a nivel motor: claves foráneas compuestas ---


def test_la_base_rechaza_ligar_doctor_de_una_empresa_con_servicio_de_otra():
    """Principio innegociable #1: el aislamiento vive en la CAPA DE DATOS, no
    en la disciplina del programador. Esta prueba no pasa por la API: escribe
    directo contra la base para que quien responda sea el motor."""
    from sqlalchemy.exc import IntegrityError

    from app.db import SessionLocal
    from app.models import Doctor, DoctorService, Service

    a = _create_company(name="Sanatorio FK Origen")
    b = _create_company(name="Sanatorio FK Ajeno")

    db = SessionLocal()
    try:
        doc_a = Doctor(company_id=a["id"], name="Dra. Propia")
        srv_b = Service(company_id=b["id"], name="Estudio Ajeno", price_gs=100000)
        db.add_all([doc_a, srv_b])
        db.commit()

        # El vínculo legítimo (todo de la misma empresa) sí entra.
        srv_a = Service(company_id=a["id"], name="Estudio Propio", price_gs=100000)
        db.add(srv_a)
        db.commit()
        db.add(DoctorService(company_id=a["id"], doctor_id=doc_a.id, service_id=srv_a.id))
        db.commit()

        # El cruce entre empresas lo rechaza el motor, no un `if`.
        db.add(DoctorService(company_id=a["id"], doctor_id=doc_a.id, service_id=srv_b.id))
        try:
            db.commit()
            raise AssertionError(
                "la base aceptó ligar un doctor con el servicio de otra empresa"
            )
        except IntegrityError:
            db.rollback()
    finally:
        db.close()
