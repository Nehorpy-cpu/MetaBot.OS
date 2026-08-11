"""Padrón de especialistas certificados y verificación de profesionales.

Lo que estas pruebas defienden: que una fecha del padrón nunca se adivine.
El archivo del CPM trae dos formatos en la misma fila, y el vencimiento es
justo el dato que dice si un médico sigue certificado.
"""
from datetime import date

from tests.test_api import _create_company, client

from app import registry
from app.db import SessionLocal
from app.models import Doctor, MedicalRegistry


CSV_DEMO = """\
"N","Apellido y Nombre","Especialidad","Acta N","Libro","Folio","Cert N","Fecha Acreditacion","Se Acredita","Fecha Sociedad","Vencimiento"
"1","Alexis Roberto Báez Martínez","Neurocirugía","623","4","129","7678","12/02/2025","CERTIFICACION","11/22/2024","11/22/2029"
"2","Echagüe Lezcano, Carmen Elisa","Pediatría General","619","4","129","7666","17/10/2024","CERTIFICACION","10/17/2024","10/17/2019"
"3","Alexis Roberto Báez Martínez","Medicina Interna","624","4","129","7679","03/01/2025","CERTIFICACION","1/3/2025","1/3/2031"
"""


def _cargar_padron(tmp_path) -> dict:
    ruta = tmp_path / "padron.csv"
    ruta.write_text(CSV_DEMO, encoding="utf-8")
    db = SessionLocal()
    try:
        db.query(MedicalRegistry).delete()
        db.commit()
        return registry.importar_csv(db, ruta)
    finally:
        db.close()


# --- El punto crítico: las dos fechas ---


def test_las_dos_columnas_de_fecha_tienen_formatos_distintos(tmp_path):
    """Medido sobre el archivo real: 'Fecha Acreditacion' es dd/mm/aaaa y
    'Vencimiento' es mm/dd/aaaa. Parsearlas igual dejaría ~1.593 vencimientos
    mal en silencio."""
    _cargar_padron(tmp_path)
    db = SessionLocal()
    try:
        m = db.query(MedicalRegistry).filter(MedicalRegistry.cert_number == "7678").one()
        # "12/02/2025" en la columna de acreditación es 12 de FEBRERO
        assert m.accredited_at == date(2025, 2, 12)
        # "11/22/2029" en vencimiento es 22 de NOVIEMBRE (no existe el mes 22)
        assert m.expires_at == date(2029, 11, 22)
    finally:
        db.close()


def test_una_fecha_que_no_encaja_se_descarta_no_se_adivina(tmp_path):
    """Un dato ausente es mejor que uno inventado en un padrón médico."""
    ruta = tmp_path / "roto.csv"
    ruta.write_text(
        CSV_DEMO.replace('"11/22/2029"', '"no-es-una-fecha"'), encoding="utf-8"
    )
    db = SessionLocal()
    try:
        db.query(MedicalRegistry).delete()
        db.commit()
        r = registry.importar_csv(db, ruta)
        assert r["sin_vencimiento"] == 1
        m = db.query(MedicalRegistry).filter(MedicalRegistry.cert_number == "7678").one()
        assert m.expires_at is None
    finally:
        db.close()


# --- Comparación de nombres ---


def test_el_nombre_se_encuentra_en_cualquier_orden_y_sin_tildes():
    """El padrón mezcla 'Nombre Apellido' con 'Apellido, Nombre', y las
    clínicas escriben 'Dr. Baez'."""
    a = registry.clave_de_nombre("Echagüe Lezcano, Carmen Elisa")
    b = registry.clave_de_nombre("Carmen Elisa Echague Lezcano")
    c = registry.clave_de_nombre("Dra. Carmen Elisa Echagüe Lezcano")
    assert a == b == c


# --- Verificación ---


def _doctor(cid: int, nombre: str, especialidad: str = "") -> Doctor:
    db = SessionLocal()
    try:
        doc = Doctor(company_id=cid, name=nombre, specialty=especialidad)
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return doc
    finally:
        db.close()


def test_profesional_con_certificacion_vigente(tmp_path):
    _cargar_padron(tmp_path)
    company = _create_company(name="Sanatorio Verificación")
    doc = _doctor(company["id"], "Dr. Alexis Roberto Báez Martínez", "Neurocirugía")

    db = SessionLocal()
    try:
        d = db.get(Doctor, doc.id)
        r = registry.verificar(db, d, hoy=date(2026, 8, 11))
        db.commit()
        assert r["verification"] == "verified"
        assert r["cert_number"] == "7678"
        assert r["cert_specialty"] == "Neurocirugía"
        # Está certificado en dos especialidades: se informan las otras.
        assert "Medicina Interna" in r["otras_especialidades"]
    finally:
        db.close()


def test_certificacion_vencida_se_marca_distinto_de_no_encontrado(tmp_path):
    """No es lo mismo 'venció' que 'no figura': una clínica tiene que poder
    distinguir a quién renovarle de a quién no darle de alta."""
    _cargar_padron(tmp_path)
    company = _create_company(name="Sanatorio Vencida")
    doc = _doctor(company["id"], "Carmen Elisa Echagüe Lezcano", "Pediatría General")

    db = SessionLocal()
    try:
        d = db.get(Doctor, doc.id)
        r = registry.verificar(db, d, hoy=date(2026, 8, 11))
        db.commit()
        assert r["verification"] == "expired"      # venció en 2019
        assert r["cert_number"] == "7666"
    finally:
        db.close()


def test_quien_no_figura_queda_como_no_encontrado_no_como_invalido(tmp_path):
    """El padrón del CPM es de médicos especialistas: una licenciada en
    bioquímica o un veterinario no figuran, y eso no los vuelve truchos."""
    _cargar_padron(tmp_path)
    company = _create_company(name="Laboratorio No Figura")
    doc = _doctor(company["id"], "Lic. Andrea Sanabria", "Bioquímica")

    db = SessionLocal()
    try:
        d = db.get(Doctor, doc.id)
        r = registry.verificar(db, d, hoy=date(2026, 8, 11))
        db.commit()
        assert r["verification"] == "not_found"
        assert d.cert_number == ""
    finally:
        db.close()


def test_se_prefiere_la_especialidad_que_declaro_la_clinica(tmp_path):
    """Báez está certificado en Neurocirugía y Medicina Interna. Si la clínica
    lo carga como internista, se verifica contra ESA."""
    _cargar_padron(tmp_path)
    company = _create_company(name="Sanatorio Dos Especialidades")
    doc = _doctor(company["id"], "Alexis Roberto Baez Martinez", "Medicina Interna")

    db = SessionLocal()
    try:
        d = db.get(Doctor, doc.id)
        r = registry.verificar(db, d, hoy=date(2026, 8, 11))
        db.commit()
        assert r["cert_specialty"] == "Medicina Interna"
        assert r["cert_number"] == "7679"
    finally:
        db.close()


def test_el_padron_no_es_de_ninguna_empresa(tmp_path):
    """Es tabla de referencia de la plataforma: si tuviera company_id, cada
    tenant tendría que importar 4.772 filas por su cuenta."""
    _cargar_padron(tmp_path)
    assert not hasattr(MedicalRegistry, "company_id")


def test_verificar_toda_una_empresa_de_una(tmp_path):
    _cargar_padron(tmp_path)
    company = _create_company(name="Sanatorio Lote")
    _doctor(company["id"], "Alexis Roberto Báez Martínez", "Neurocirugía")
    _doctor(company["id"], "Carmen Elisa Echagüe Lezcano", "Pediatría General")
    _doctor(company["id"], "Dr. Nadie Inexistente", "Cardiología")

    db = SessionLocal()
    try:
        r = registry.verificar_empresa(db, company["id"])
        assert r["total"] == 3
        assert r["por_estado"] == {"verified": 1, "expired": 1, "not_found": 1}
    finally:
        db.close()
