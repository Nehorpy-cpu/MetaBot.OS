"""CFO — Fase 5: el informe privado.

El enlace es lo único que hay entre un tercero y los números de una empresa.
Todo lo de acá lo prueba desde el lado del que intenta abrirlo sin permiso.
"""
from datetime import date, datetime, timedelta

from tests.test_api import _create_company, client  # noqa: I001
from tests.test_tenancy import _login, _make_user

from app import cfo_reportes
from app.db import SessionLocal
from app.models import Appointment, Company, FinanceReport, FinanceReportToken, Service

FINANZAS = ["finance", "booking"]
PERIODO = {"desde": "2026-07-01", "hasta": "2026-07-31"}


def _empresa(nombre: str, con_datos=True):
    c = _create_company(name=nombre, packs=FINANZAS)
    cid = c["id"]
    client.post(f"/api/companies/{cid}/cfo/metricas/ventas_netas/aprobar",
                json={"version": 1})
    if con_datos:
        db = SessionLocal()
        try:
            s = Service(company_id=cid, name="Consulta", price_gs=180_000, active=True)
            db.add(s)
            db.commit()
            svc = s.id
        finally:
            db.close()
        doc = client.post(f"/api/companies/{cid}/doctors",
                          json={"name": "Dr. X"}).json()["id"]
        db = SessionLocal()
        try:
            db.add(Appointment(
                company_id=cid, doctor_id=doc, patient_name="Paciente",
                patient_phone="595981000000",
                scheduled_at=datetime(2026, 7, 10, 10, 0),
                service_id=svc, status="attended",
            ))
            db.commit()
        finally:
            db.close()
    return cid


def _crear(cid: int, **extra):
    cuerpo = {"metricas": ["ventas_netas"], **PERIODO, **extra}
    r = client.post(f"/api/companies/{cid}/cfo/informes", json=cuerpo)
    assert r.status_code == 201, r.text
    return r.json()


def _token_de(enlace: str) -> str:
    return enlace.rsplit("/r/", 1)[-1]


# ─── Lo que el dueño recibe ──────────────────────────────────────────────


def test_el_enlace_abre_el_informe_con_el_numero():
    cid = _empresa("Informe Camino Feliz")
    creado = _crear(cid)
    r = client.get(f"/r/{_token_de(creado['enlace'])}")
    assert r.status_code == 200
    assert "Informe Camino Feliz" in r.text
    assert "180.000" in r.text
    assert "Ventas netas" in r.text


def test_el_informe_dice_su_procedencia_y_sus_advertencias():
    """Un número sin fuente ni fecha no sirve para decidir, y una advertencia
    que llega después del número llega tarde."""
    cid = _empresa("Informe Procedencia")
    creado = _crear(cid)
    html = client.get(f"/r/{_token_de(creado['enlace'])}").text
    assert "Fuente:" in html
    assert "Completitud:" in html
    assert "Definición v1" in html
    assert "facturación contable" in html


def test_el_informe_no_carga_nada_de_afuera():
    """Un reporte financiero no tiene por qué pedirle nada a otro dominio:
    cada petición le cuenta a un tercero que alguien lo abrió."""
    cid = _empresa("Informe Sin Terceros")
    html = client.get(f"/r/{_token_de(_crear(cid)['enlace'])}").text
    assert "<script" not in html.lower()
    assert "http://" not in html and "https://" not in html
    assert "//fonts." not in html and "cdn" not in html.lower()


def test_los_encabezados_impiden_cache_indexado_e_iframe():
    cid = _empresa("Informe Encabezados")
    r = client.get(f"/r/{_token_de(_crear(cid)['enlace'])}")
    assert "no-store" in r.headers["cache-control"]
    assert "noindex" in r.headers["x-robots-tag"]
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
    csp = r.headers["content-security-policy"]
    assert "default-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "script-src" not in csp, "no hay ningún script permitido"


# ─── El lado del atacante ────────────────────────────────────────────────


def test_un_token_inventado_no_abre_nada():
    _empresa("Informe Token Inventado")
    for intento in ("x", "a" * 43, "../../etc/passwd", "1", "%2e%2e"):
        r = client.get(f"/r/{intento}")
        assert r.status_code == 404, f"'{intento}' devolvió {r.status_code}"


def test_el_token_no_se_guarda_en_claro():
    """Con acceso de lectura a un respaldo, alguien podría abrir los informes
    de todos los clientes."""
    cid = _empresa("Informe Hash")
    token = _token_de(_crear(cid)["enlace"])
    db = SessionLocal()
    try:
        filas = db.query(FinanceReportToken).filter(
            FinanceReportToken.company_id == cid).all()
        assert filas
        for f in filas:
            assert f.token_hash != token
            assert len(f.token_hash) == 64
            assert token not in f.token_hash
    finally:
        db.close()


def test_el_token_no_lleva_adentro_de_quien_es():
    """Un enlace interceptado no tiene por qué contar de qué empresa es."""
    cid = _empresa("Informe Opaco")
    creado = _crear(cid)
    token = _token_de(creado["enlace"])
    assert str(cid) not in token
    assert "Opaco" not in token
    assert "2026" not in token


def test_un_enlace_vencido_no_abre():
    cid = _empresa("Informe Vencido")
    token = _token_de(_crear(cid)["enlace"])
    db = SessionLocal()
    try:
        fila = db.query(FinanceReportToken).filter(
            FinanceReportToken.company_id == cid).first()
        fila.expira_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()
    assert client.get(f"/r/{token}").status_code == 404


def test_un_enlace_revocado_no_abre():
    """Para cuando llegó a quien no debía."""
    cid = _empresa("Informe Revocado")
    creado = _crear(cid)
    token = _token_de(creado["enlace"])
    assert client.get(f"/r/{token}").status_code == 200

    r = client.post(f"/api/companies/{cid}/cfo/informes/{creado['id']}/revocar")
    assert r.status_code == 200 and r.json()["revocados"] == 1
    assert client.get(f"/r/{token}").status_code == 404


def test_el_enlace_de_un_solo_uso_sirve_una_vez():
    """Reenviarlo por un grupo de WhatsApp deja de ser una filtración."""
    cid = _empresa("Informe Un Solo Uso")
    token = _token_de(_crear(cid, un_solo_uso=True)["enlace"])
    assert client.get(f"/r/{token}").status_code == 200
    assert client.get(f"/r/{token}").status_code == 404


def test_todos_los_rechazos_se_ven_iguales():
    """Decir "este enlace venció" le confirma a quien prueba tokens que
    acertó uno. Inventado, vencido y revocado devuelven lo mismo."""
    cid = _empresa("Informe Rechazos")
    vencido = _token_de(_crear(cid)["enlace"])
    db = SessionLocal()
    try:
        db.query(FinanceReportToken).filter(
            FinanceReportToken.company_id == cid
        ).first().expira_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()

    inventado = client.get("/r/" + "z" * 43)
    caduco = client.get(f"/r/{vencido}")
    assert inventado.status_code == caduco.status_code == 404
    assert inventado.text == caduco.text, "las respuestas se distinguen entre sí"


def test_el_html_escapa_lo_que_cargo_alguien():
    """El nombre de una empresa es texto que alguien escribió. Si trae
    `<script>`, tiene que verse, no ejecutarse."""
    c = _create_company(name="Empresa <script>alert(1)</script> SA", packs=FINANZAS)
    cid = c["id"]
    client.post(f"/api/companies/{cid}/cfo/metricas/ventas_netas/aprobar",
                json={"version": 1})
    html = client.get(f"/r/{_token_de(_crear(cid)['enlace'])}").text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


# ─── Aislamiento ─────────────────────────────────────────────────────────


def test_no_se_revoca_el_informe_de_otra_empresa():
    a = _empresa("Informe Cruce A")
    b = _empresa("Informe Cruce B")
    creado = _crear(a)
    r = client.post(f"/api/companies/{b}/cfo/informes/{creado['id']}/revocar")
    assert r.status_code == 404
    # Y sigue abriendo, o sea que no lo revocó igual.
    assert client.get(f"/r/{_token_de(creado['enlace'])}").status_code == 200


def test_el_listado_no_muestra_informes_ajenos():
    a = _empresa("Informe Listado A")
    b = _empresa("Informe Listado B")
    _crear(a)
    assert client.get(f"/api/companies/{b}/cfo/informes").json() == []
    assert len(client.get(f"/api/companies/{a}/cfo/informes").json()) == 1


def test_el_listado_no_devuelve_ningun_token():
    cid = _empresa("Informe Listado Sin Token")
    creado = _crear(cid)
    token = _token_de(creado["enlace"])
    filas = client.get(f"/api/companies/{cid}/cfo/informes").json()
    plano = str(filas)
    assert token not in plano
    # Ni el token ni una URL para abrirlo: el enlace se muestra UNA vez, al
    # crearlo. Después queda el hash y hay que emitir uno nuevo.
    assert "/r/" not in plano
    assert not any("enlace" == k for f in filas for k in f)


def test_un_operador_no_crea_ni_revoca_informes():
    cid = _empresa("Informe Permisos")
    _make_user("operador-informes@test.py", cid, role="operator")
    op = _login("operador-informes@test.py")
    assert op.post(f"/api/companies/{cid}/cfo/informes",
                   json={"metricas": ["ventas_netas"], **PERIODO}).status_code == 403
    assert op.get(f"/api/companies/{cid}/cfo/informes").status_code == 403


def test_sin_el_bloque_no_hay_informes():
    c = _create_company(name="Comercio Sin Informes")
    assert client.post(f"/api/companies/{c['id']}/cfo/informes",
                       json={"metricas": ["ventas_netas"], **PERIODO}).status_code == 402


# ─── El snapshot ─────────────────────────────────────────────────────────


def test_el_informe_no_se_mueve_cuando_cambian_los_datos():
    """El dueño reenvía el enlace a su contador tres días después y los dos
    tienen que ver el mismo número."""
    cid = _empresa("Informe Congelado")
    token = _token_de(_crear(cid)["enlace"])
    assert "180.000" in client.get(f"/r/{token}").text

    db = SessionLocal()
    try:
        db.query(Service).filter(Service.company_id == cid).first().price_gs = 999_000
        db.commit()
    finally:
        db.close()

    assert "180.000" in client.get(f"/r/{token}").text, "el informe se recalculó solo"


def test_una_metrica_no_calculable_se_muestra_como_tal():
    """Y no como cero ni en blanco."""
    cid = _empresa("Informe No Calculable")
    creado = _crear(cid, metricas=["ventas_netas", "flujo_de_caja"])
    html = client.get(f"/r/{_token_de(creado['enlace'])}").text
    assert "No se pudo calcular" in html
    assert "caja_y_bancos" in html


def test_las_aperturas_quedan_registradas():
    """Saber si el informe se abrió, y cuándo, es la mitad de poder decidir
    si hay que revocarlo."""
    cid = _empresa("Informe Aperturas")
    creado = _crear(cid)
    token = _token_de(creado["enlace"])
    client.get(f"/r/{token}")
    client.get(f"/r/{token}")
    fila = client.get(f"/api/companies/{cid}/cfo/informes").json()[0]
    assert fila["aperturas"] == 2
    assert fila["ultima_apertura"]
