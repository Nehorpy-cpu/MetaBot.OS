"""Base de servicios/estudios del negocio, vinculados a los profesionales
que los atienden. Aplica a cualquier rubro (sanatorio, odontología, estética,
o servicios de cualquier empresa)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Appointment, Company, Doctor, DoctorService, Service
from .. import industry_catalog
from ..packs import industry_services

router = APIRouter(tags=["services"])


class ServiceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(default="", max_length=100)
    description: str = ""
    price_gs: int = Field(default=0, ge=0)
    duration_min: int = Field(default=30, ge=5, le=480)
    doctor_ids: list[int] = []


class ServiceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = None
    description: str | None = None
    price_gs: int | None = Field(default=None, ge=0)
    duration_min: int | None = Field(default=None, ge=5, le=480)
    active: bool | None = None
    doctor_ids: list[int] | None = None


def _company(company_id: int, db: Session) -> Company:
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Empresa no encontrada")
    return company


def _validate_doctors(company_id: int, doctor_ids: list[int], db: Session):
    for did in doctor_ids:
        doctor = db.get(Doctor, did)
        if not doctor or doctor.company_id != company_id:
            raise HTTPException(422, f"Doctor {did} no pertenece a esta empresa")


def _set_doctors(service: Service, doctor_ids: list[int], db: Session):
    db.query(DoctorService).filter(
        DoctorService.service_id == service.id,
        DoctorService.company_id == service.company_id,
    ).delete()
    for did in doctor_ids:
        # company_id sale del SERVICIO, que ya está atado al tenant: con la
        # clave foránea compuesta, un doctor de otra empresa hace fallar el
        # INSERT en el motor, no en un `if`.
        db.add(DoctorService(company_id=service.company_id, doctor_id=did, service_id=service.id))


def _serialize(service: Service, db: Session) -> dict:
    links = db.query(DoctorService).filter(
        DoctorService.service_id == service.id,
        DoctorService.company_id == service.company_id,
    ).all()
    doctors = []
    for link in links:
        doctor = db.get(Doctor, link.doctor_id)
        if doctor and doctor.company_id == service.company_id:
            doctors.append({"id": doctor.id, "name": doctor.name})
    return {
        "id": service.id,
        "name": service.name,
        "category": service.category,
        "description": service.description,
        "price_gs": service.price_gs,
        "duration_min": service.duration_min,
        "active": service.active,
        "doctors": doctors,
    }


@router.post("/companies/{company_id}/services", status_code=201)
def create_service(company_id: int, payload: ServiceIn, db: Session = Depends(get_db)):
    _company(company_id, db)
    _validate_doctors(company_id, payload.doctor_ids, db)
    exists = (
        db.query(Service)
        .filter(Service.company_id == company_id, Service.name == payload.name)
        .first()
    )
    if exists:
        raise HTTPException(409, "Ya existe un servicio con ese nombre")
    service = Service(company_id=company_id, **payload.model_dump(exclude={"doctor_ids"}))
    db.add(service)
    db.flush()
    _set_doctors(service, payload.doctor_ids, db)
    db.commit()
    return _serialize(service, db)


@router.get("/companies/{company_id}/services")
def list_services(company_id: int, db: Session = Depends(get_db)):
    _company(company_id, db)
    services = (
        db.query(Service).filter(Service.company_id == company_id).order_by(Service.category, Service.name).all()
    )
    return [_serialize(s, db) for s in services]


@router.patch("/companies/{company_id}/services/{service_id}")
def update_service(company_id: int, service_id: int, payload: ServiceUpdate, db: Session = Depends(get_db)):
    service = db.get(Service, service_id)
    if not service or service.company_id != company_id:
        raise HTTPException(404, "Servicio no encontrado")
    data = payload.model_dump(exclude_unset=True)
    doctor_ids = data.pop("doctor_ids", None)
    for field, value in data.items():
        setattr(service, field, value)
    if doctor_ids is not None:
        _validate_doctors(company_id, doctor_ids, db)
        _set_doctors(service, doctor_ids, db)
    db.commit()
    return _serialize(service, db)


@router.get("/companies/{company_id}/services/suggestions")
def suggest_services(company_id: int, db: Session = Depends(get_db)):
    """Servicios típicos del rubro que esta empresa aún no tiene cargados.

    Sale de un catálogo curado por rubro (conocimiento público del sector),
    NO de los datos de otras empresas: sugerir a partir de lo que cargó otro
    tenant filtraría su oferta y sus precios. Sin precio sugerido, por lo
    mismo: cada negocio pone el suyo.
    """
    company = _company(company_id, db)
    own = {
        s.name.lower()
        for s in db.query(Service).filter(Service.company_id == company_id).all()
    }
    # El catálogo curado por rubro: 434 estudios con su PREPARACIÓN PREVIA,
    # que es el dato que evita que el paciente viaje en ayunas al vicio.
    # Antes esto salía de packs.industry_services, que tiene 6 ítems para
    # "medical": el catálogo estaba escrito y solo lo usaba el sembrador de
    # las empresas de prueba.
    curados = industry_catalog.para_vertical(company.vertical)
    if not curados:
        # Rubros sin catálogo curado (comercio, gastronomía): la lista corta
        # genérica sigue sirviendo.
        curados = industry_services(company.vertical)
    return [
        # El precio va en 0 a propósito: los del catálogo son de referencia
        # para tener con qué probar, no cotizaciones. Cada negocio pone el suyo.
        {**item, "typical_price_gs": 0, "price_gs": 0}
        for item in curados
        if item["name"].lower() not in own
    ]


@router.delete("/companies/{company_id}/services/{service_id}", status_code=204)
def delete_service(company_id: int, service_id: int, db: Session = Depends(get_db)):
    service = db.get(Service, service_id)
    if not service or service.company_id != company_id:
        raise HTTPException(404, "Servicio no encontrado")

    # Un servicio con atenciones cargadas NO se borra: se desactiva.
    #
    # `Appointment.service_id` no tiene clave foránea —se guarda suelto—, así
    # que borrarlo dejaba las citas apuntando a la nada. Nada fallaba: la
    # liquidación del mes pasado simplemente no encontraba el precio y le
    # facturaba ₲ 0 al profesional por una ecografía que sí cobró la clínica.
    # Desactivarlo saca el servicio del catálogo y del bot igual, y conserva
    # el precio de lo ya atendido.
    usado = (
        db.query(Appointment)
        .filter(
            Appointment.company_id == company_id,
            Appointment.service_id == service_id,
        )
        .count()
    )
    if usado:
        raise HTTPException(
            409,
            {
                "motivo": (
                    f"Este servicio ya tiene {usado} turno(s) cargados. Borrarlo "
                    "les sacaría el precio y el profesional cobraría de menos. "
                    "Desactivalo: sale del catálogo y del bot igual."
                ),
                "codigo": "servicio_en_uso",
                "turnos": usado,
            },
        )

    db.query(DoctorService).filter(DoctorService.service_id == service_id).delete()
    db.delete(service)
    db.commit()
