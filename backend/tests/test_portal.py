"""Portal del Profesional (bloque 4).

Lo que este bloque vende es una frase: "cada médico ve SUS pacientes". Si eso
falla, no falla una función — falla el producto, y encima con datos clínicos
de gente real. Todo lo de acá prueba esa frase desde el lado del atacante.
"""
from datetime import datetime, timedelta

# `tests.test_api` va PRIMERO: es quien deja el entorno de prueba armado
# (base en memoria, ADMIN_TOKEN, scheduler apagado) antes de que se importe
# nada de `app`. Al revés, `app.config` ya se leyó sin token y todo el módulo
# contesta 401 sin que se entienda por qué.
from tests.test_api import _create_company, client  # noqa: I001
from tests.test_tenancy import _login

from app.db import SessionLocal
from app.models import Appointment, Prescription, PrescriptionItem

PORTAL = ["booking", "healthcare", "practitioner"]


def _pronto(dias=1, hora=9):
    return (datetime.now() + timedelta(days=dias)).replace(
        hour=hora, minute=0, second=0, microsecond=0)


def _doctor(cid: int, nombre: str, tel="595981000111"):
    r = client.post(f"/api/companies/{cid}/doctors",
                    json={"name": nombre, "phone": tel, "specialty": "Clínica Médica"})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _cita(cid: int, doctor_id: int, paciente: str, telefono: str, cuando=None):
    db = SessionLocal()
    try:
        cita = Appointment(
            company_id=cid, doctor_id=doctor_id, patient_name=paciente,
            patient_phone=telefono, scheduled_at=cuando or _pronto(),
            status="confirmed",
        )
        db.add(cita)
        db.commit()
        return cita.id
    finally:
        db.close()


def _receta(cid: int, doctor_id: int, paciente: str, telefono: str, dx: str,
            cuando=None):
    db = SessionLocal()
    try:
        receta = Prescription(
            company_id=cid, doctor_id=doctor_id, patient_name=paciente,
            patient_phone=telefono, diagnosis=dx,
            issued_at=cuando or datetime.utcnow(),
        )
        db.add(receta)
        db.flush()
        db.add(PrescriptionItem(
            company_id=cid, prescription_id=receta.id,
            medication="Amoxicilina 500mg", dose="1 comprimido", every_hours=8,
            duration_days=7,
        ))
        db.commit()
        return receta.id
    finally:
        db.close()


def _acceso(cid: int, doctor_id: int, email: str):
    """Le crea el login al profesional y devuelve un cliente ya autenticado."""
    r = client.post(f"/api/companies/{cid}/portal/accesos",
                    json={"doctor_id": doctor_id, "email": email})
    assert r.status_code == 201, r.text
    clave = r.json()["clave_temporal"]
    assert clave, "el acceso nuevo tiene que traer una clave temporal"

    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app, base_url="https://testserver")
    entrada = c.post("/api/auth/login", json={"email": email, "password": clave})
    assert entrada.status_code == 200, entrada.text
    return c


# ─── Lo que el bloque promete ────────────────────────────────────────────


def test_el_profesional_ve_solo_sus_pacientes():
    """LA promesa del bloque. Dos médicos en la misma clínica, y el portal de
    cada uno muestra únicamente lo suyo."""
    c = _create_company(name="Sanatorio Dos Médicos", packs=PORTAL)
    cid = c["id"]
    ana = _doctor(cid, "Dra. Ana Rojas")
    beto = _doctor(cid, "Dr. Beto Cáceres")
    _cita(cid, ana["id"], "Paciente De Ana", "595981111111")
    _cita(cid, beto["id"], "Paciente De Beto", "595982222222")

    portal_ana = _acceso(cid, ana["id"], "ana.portal@test.py")
    pacientes = portal_ana.get(f"/api/companies/{cid}/portal/pacientes").json()
    nombres = [p["nombre"] for p in pacientes]
    assert "Paciente De Ana" in nombres
    assert "Paciente De Beto" not in nombres, "vio al paciente del colega"


def test_no_puede_leer_las_recetas_del_colega():
    """La receta lleva el diagnóstico. Filtrar por empresa —como hace el panel
    de la recepción— acá sería mostrarle a un médico el diagnóstico que puso
    otro."""
    c = _create_company(name="Sanatorio Recetas Ajenas", packs=PORTAL)
    cid = c["id"]
    ana = _doctor(cid, "Dra. Ana Recetas")
    beto = _doctor(cid, "Dr. Beto Recetas")
    # El MISMO paciente, atendido por los dos.
    _cita(cid, ana["id"], "Carlos Vera", "595983333333")
    _receta(cid, ana["id"], "Carlos Vera", "595983333333", "Faringitis")
    _receta(cid, beto["id"], "Carlos Vera", "595983333333", "Lumbalgia")

    portal_ana = _acceso(cid, ana["id"], "ana.recetas@test.py")
    ficha = portal_ana.get(
        f"/api/companies/{cid}/portal/pacientes/ficha",
        params={"telefono": "595983333333", "nombre": "Carlos Vera"},
    ).json()
    diagnosticos = [r["diagnostico"] for r in ficha["recetas"]]
    assert "Faringitis" in diagnosticos
    assert "Lumbalgia" not in diagnosticos, "leyó el diagnóstico del otro médico"
    # Y la receta trae la medicación completa: es para lo que sirve la ficha.
    assert ficha["recetas"][0]["medicacion"][0]["nombre"] == "Amoxicilina 500mg"


def test_no_puede_hacerse_pasar_por_otro_medico():
    """El id del doctor sale de la membresía, NUNCA del request. Si viniera
    por querystring, cambiar un número sería leerle los pacientes al colega."""
    c = _create_company(name="Sanatorio Suplantación", packs=PORTAL)
    cid = c["id"]
    ana = _doctor(cid, "Dra. Ana Suplantada")
    beto = _doctor(cid, "Dr. Beto Suplantador")
    _cita(cid, ana["id"], "Paciente Reservado", "595984444444")

    portal_beto = _acceso(cid, beto["id"], "beto.suplanta@test.py")
    r = portal_beto.get(f"/api/companies/{cid}/portal/pacientes",
                        params={"doctor_id": ana["id"]})
    assert r.status_code == 200
    assert r.json() == [], "el doctor_id del request le cambió la identidad"


def test_el_profesional_no_entra_al_panel_de_la_clinica():
    """Es un médico, no un operador. Nada del panel le corresponde: ni la
    agenda completa, ni las recetas de todos, ni el catálogo."""
    c = _create_company(name="Sanatorio Encerrado", packs=PORTAL)
    cid = c["id"]
    doc = _doctor(cid, "Dr. Encerrado")
    portal = _acceso(cid, doc["id"], "encerrado@test.py")

    for ruta in ("/doctors", "/appointments", "/prescriptions", "/services",
                 "/conversations", "/dashboard", "/registry/search?q=x"):
        r = portal.get(f"/api/companies/{cid}{ruta}")
        assert r.status_code == 403, f"{ruta} le contestó {r.status_code}"
        assert r.json()["detail"]["codigo"] == "solo_portal"


def test_el_profesional_no_ve_otra_empresa():
    """El encierro en /portal no reemplaza al aislamiento por tenant."""
    a = _create_company(name="Sanatorio Portal A", packs=PORTAL)
    b = _create_company(name="Sanatorio Portal B", packs=PORTAL)
    doc_a = _doctor(a["id"], "Dr. De la A")
    _doctor(b["id"], "Dr. De la B")
    portal_a = _acceso(a["id"], doc_a["id"], "dela.a@test.py")

    r = portal_a.get(f"/api/companies/{b['id']}/portal/pacientes")
    assert r.status_code == 404, r.text


def test_el_portal_es_del_bloque_4():
    """Si la clínica no compró el Portal del Profesional, no hay portal."""
    c = _create_company(name="Clínica Sin Portal Propio")
    r = client.get(f"/api/companies/{c['id']}/portal/pacientes")
    assert r.status_code == 402
    assert r.json()["detail"]["bloque"] == "practitioner"


def test_el_resumen_del_dia_son_los_post_it():
    """La pantalla principal del médico: sus pacientes de hoy, uno por
    tarjeta, con si es la primera vez y qué se le recetó la última."""
    c = _create_company(name="Sanatorio Post It", packs=PORTAL)
    cid = c["id"]
    doc = _doctor(cid, "Dra. Post It")
    hoy = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
    # El paciente ya vino el mes pasado y se fue con una receta. Eso es
    # justamente lo que el post-it tiene que recordarle al médico hoy.
    antes = hoy - timedelta(days=30)
    _cita(cid, doc["id"], "Marco Garcete", "595985555555", antes)
    _receta(cid, doc["id"], "Marco Garcete", "595985555555", "Bronquitis", antes)
    _cita(cid, doc["id"], "Marco Garcete", "595985555555", hoy)

    portal = _acceso(cid, doc["id"], "postit@test.py")
    datos = portal.get(f"/api/companies/{cid}/portal/agenda",
                       params={"dia": hoy.date().isoformat()}).json()
    assert datos["total"] == 1
    ficha = datos["pacientes"][0]
    assert ficha["paciente"] == "Marco Garcete"
    assert ficha["primera_vez"] is False
    assert ficha["ultima_receta"]["diagnostico"] == "Bronquitis"


def test_un_acceso_no_le_cambia_la_clave_a_un_usuario_existente():
    """Si crear el acceso reseteara la clave, sabiendo el email de cualquiera
    se le tomaría la cuenta."""
    from app.auth import hash_password
    from app.models import User

    c = _create_company(name="Sanatorio Email Repetido", packs=PORTAL)
    cid = c["id"]
    doc = _doctor(cid, "Dr. Email Repetido")

    db = SessionLocal()
    try:
        db.add(User(email="yaexiste@test.py", password_hash=hash_password("clave-segura-123"),
                    full_name="Ya Existe"))
        db.commit()
    finally:
        db.close()

    r = client.post(f"/api/companies/{cid}/portal/accesos",
                    json={"doctor_id": doc["id"], "email": "yaexiste@test.py"})
    assert r.status_code == 201, r.text
    assert r.json()["clave_temporal"] == "", "le devolvió una clave nueva"
    # Y la de antes sigue sirviendo.
    entra = _login("yaexiste@test.py")
    assert entra.get(f"/api/companies/{cid}/portal/me").status_code == 200


def test_un_doctor_no_puede_tener_dos_accesos():
    c = _create_company(name="Sanatorio Doble Acceso", packs=PORTAL)
    cid = c["id"]
    doc = _doctor(cid, "Dr. Doble")
    _acceso(cid, doc["id"], "doble.uno@test.py")
    r = client.post(f"/api/companies/{cid}/portal/accesos",
                    json={"doctor_id": doc["id"], "email": "doble.dos@test.py"})
    assert r.status_code == 409, r.text
