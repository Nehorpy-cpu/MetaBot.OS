"""Siembra empresas de salud FICTICIAS para probar los bots.

Nombres inventados, precios de referencia, aseguradoras inventadas: es un
banco de pruebas, no datos de nadie. Sirve para que el bot tenga con qué
trabajar desde el minuto uno en un sanatorio, una odontológica, una
veterinaria, un laboratorio y un centro de imágenes.

Idempotente: si la empresa ya existe por nombre, no la duplica.

Uso (dentro del contenedor del backend):
    python scripts/seed_salud_demo.py
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db as db_module  # noqa: E402
from app import industry_catalog, packs  # noqa: E402
from app.models import (  # noqa: E402
    Agent,
    Company,
    Doctor,
    DoctorService,
    Insurer,
    Service,
)
from app.templates import TEMPLATES  # noqa: E402

# Aseguradoras FICTICIAS. No se usan nombres reales: eso implicaría convenios
# comerciales que no existen.
ASEGURADORAS = [
    {"name": "Seguro Ñandutí", "plan": "Plan Oro", "coverage_pct": 80, "copay_gs": 20000},
    {"name": "Seguro Ñandutí", "plan": "Plan Básico", "coverage_pct": 50, "copay_gs": 35000},
    {"name": "Salud Guaraní", "plan": "Integral", "coverage_pct": 70, "copay_gs": 25000},
    {"name": "Prepaga Tapé", "plan": "Familiar", "coverage_pct": 60, "copay_gs": 30000},
]

EMPRESAS = [
    {
        "name": "Sanatorio Ykua Sati (demo)",
        "vertical": "hospital",
        "niche": "Sanatorio privado multiespecialidad con internación",
        "address": "Avda. Mcal. López 1234, Asunción",
        "doctores": [
            ("Dra. Marta Benítez", "Clínica médica", "Lun a Vie 07:00-13:00"),
            ("Dr. Ramón Ayala", "Cardiología", "Lun, Mié y Vie 14:00-19:00"),
            ("Dra. Lucía Ozorio", "Pediatría", "Lun a Sáb 08:00-12:00"),
            ("Dr. Aníbal Figueredo", "Traumatología", "Mar y Jue 08:00-14:00"),
            ("Dra. Celeste Villalba", "Ginecología y obstetricia", "Lun a Vie 14:00-18:00"),
            ("Dr. Hugo Cabral", "Cirugía general", "Mié y Vie 07:00-12:00"),
        ],
        "aseguradoras": ASEGURADORAS,
    },
    {
        "name": "Odontología Aramí (demo)",
        "vertical": "dental",
        "niche": "Clínica odontológica integral",
        "address": "Av. España 890, Asunción",
        "doctores": [
            ("Dra. Sofía Duarte", "Odontología general", "Lun a Vie 08:00-17:00"),
            ("Dr. Julio Meza", "Endodoncia", "Mar y Jue 09:00-18:00"),
            ("Dra. Nadia Rolón", "Ortodoncia", "Lun, Mié y Vie 14:00-19:00"),
            ("Dr. Pablo Cañete", "Cirugía maxilofacial", "Sáb 08:00-13:00"),
        ],
        "aseguradoras": ASEGURADORAS[:2],
    },
    {
        "name": "Veterinaria Mbarete (demo)",
        "vertical": "veterinary",
        "niche": "Clínica veterinaria de pequeños animales",
        "address": "Ruta Mcal. Estigarribia km 12, Luque",
        "doctores": [
            ("Dr. Fernando Giménez", "Clínica de pequeños animales", "Lun a Sáb 08:00-18:00"),
            ("Dra. Rocío Alderete", "Cirugía veterinaria", "Mar, Jue y Sáb 09:00-15:00"),
            ("Dr. Emilio Paredes", "Dermatología veterinaria", "Lun y Mié 14:00-19:00"),
        ],
        "aseguradoras": [],
    },
    {
        "name": "Laboratorio Tapé Porã (demo)",
        "vertical": "laboratory",
        "niche": "Laboratorio de análisis clínicos",
        "address": "Cerro Corá 456, Asunción",
        "doctores": [
            ("Lic. Andrea Sanabria", "Bioquímica", "Lun a Vie 06:30-11:00"),
            ("Lic. Diego Riveros", "Bioquímica", "Lun a Sáb 06:30-10:00"),
        ],
        "aseguradoras": ASEGURADORAS,
    },
    {
        "name": "Centro de Diagnóstico Kuarahy (demo)",
        "vertical": "imaging",
        "niche": "Diagnóstico por imágenes y estudios funcionales",
        "address": "Avda. Santa Teresa 2100, Asunción",
        "doctores": [
            ("Dr. Óscar Notario", "Radiología", "Lun a Vie 07:00-19:00"),
            ("Dra. Patricia Vera", "Ecografía y doppler", "Lun a Sáb 07:00-13:00"),
            ("Dr. Sergio Maidana", "Cardiología no invasiva", "Mar y Jue 14:00-18:00"),
        ],
        "aseguradoras": ASEGURADORAS[:3],
    },
]


def _sembrar_agentes(db, company: Company) -> int:
    """Enjambre del tenant. Las plantillas de salud salen de 'medical'."""
    plantilla = TEMPLATES.get(company.vertical) or TEMPLATES["medical"]
    n = 0
    for spec in plantilla["agents"]:
        if not db.query(Agent).filter(Agent.company_id == company.id, Agent.slug == spec["slug"]).first():
            db.add(Agent(company_id=company.id, **spec))
            n += 1
    return n


def _sembrar_servicios(db, company: Company) -> int:
    """Catálogo curado del rubro. Cada empresa después ajusta sus precios."""
    existentes = {
        s.name for s in db.query(Service).filter(Service.company_id == company.id).all()
    }
    n = 0
    for item in industry_catalog.para_vertical(company.vertical):
        if item["name"] in existentes:
            continue
        db.add(Service(
            company_id=company.id,
            name=item["name"][:200],
            category=item["category"][:100],
            specialty=item["specialty"][:100],
            price_gs=item["price_gs"],
            duration_min=item["duration_min"],
            prep=item["prep"],
            sample=item["sample"][:80],
            code="",  # lo carga el cliente con el nomenclador de su aseguradora
        ))
        existentes.add(item["name"])
        n += 1
    return n


def _vincular_doctores(db, company: Company) -> int:
    """Liga cada profesional con los servicios de SU especialidad.

    Sin esto el bot no sabe a quién ofrecer para cada estudio.
    """
    doctores = db.query(Doctor).filter(Doctor.company_id == company.id).all()
    servicios = db.query(Service).filter(Service.company_id == company.id).all()
    ya = {
        (l.doctor_id, l.service_id)
        for l in db.query(DoctorService)
        .join(Service, Service.id == DoctorService.service_id)
        .filter(Service.company_id == company.id)
        .all()
    }
    n = 0
    for doc in doctores:
        especialidad = (doc.specialty or "").lower()
        for srv in servicios:
            esp_srv = (srv.specialty or "").lower()
            if not esp_srv or not especialidad:
                continue
            if esp_srv in especialidad or especialidad in esp_srv:
                if (doc.id, srv.id) not in ya:
                    db.add(DoctorService(doctor_id=doc.id, service_id=srv.id))
                    ya.add((doc.id, srv.id))
                    n += 1
    return n


def sembrar() -> None:
    db = db_module.SessionLocal()
    try:
        for spec in EMPRESAS:
            company = db.query(Company).filter(Company.name == spec["name"]).first()
            creada = company is None
            if creada:
                company = Company(
                    name=spec["name"],
                    vertical=spec["vertical"],
                    niche=spec["niche"],
                    industry=spec["niche"],
                    address=spec["address"],
                    packs=",".join(packs.suggested_for(spec["vertical"])),
                )
                db.add(company)
                db.flush()

            n_agentes = _sembrar_agentes(db, company)

            existentes = {d.name for d in db.query(Doctor).filter(Doctor.company_id == company.id).all()}
            n_doc = 0
            for nombre, especialidad, horario in spec["doctores"]:
                if nombre not in existentes:
                    db.add(Doctor(company_id=company.id, name=nombre,
                                  specialty=especialidad, schedule=horario))
                    n_doc += 1
            db.flush()

            n_srv = _sembrar_servicios(db, company)
            db.flush()
            n_link = _vincular_doctores(db, company)

            n_seg = 0
            for a in spec["aseguradoras"]:
                existe = db.query(Insurer).filter(
                    Insurer.company_id == company.id,
                    Insurer.name == a["name"], Insurer.plan == a["plan"],
                ).first()
                if not existe:
                    db.add(Insurer(company_id=company.id, **a))
                    n_seg += 1

            db.commit()
            estado = "creada" if creada else "actualizada"
            print(
                f"[{company.id}] {company.name} ({company.vertical}) {estado}: "
                f"{n_agentes} agentes, {n_doc} profesionales, {n_srv} servicios, "
                f"{n_link} vínculos doctor-servicio, {n_seg} convenios"
            )
    finally:
        db.close()


if __name__ == "__main__":
    sembrar()
