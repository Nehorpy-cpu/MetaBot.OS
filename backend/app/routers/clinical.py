"""Convenios con aseguradoras y recetas médicas.

Lo que el panel necesita para que esto se pueda usar de verdad: hasta acá
existían el modelo y las herramientas del bot, pero no había forma de cargar
una receta ni un convenio salvo escribiendo en la base a mano.

Dos reglas que se aplican en el servidor, no en el formulario:
- El profesional de la receta tiene que ser de ESTA empresa. La clave foránea
  compuesta ya lo impide a nivel motor; acá se devuelve un 422 legible en vez
  de un error de base.
- Los recordatorios de toma exigen consentimiento explícito y que el número
  del paciente haya escrito a la clínica. Si no se cumple, la receta se
  guarda igual y se informa POR QUÉ no hay recordatorios.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import medication
from ..db import get_db
from ..models import (
    Company,
    Doctor,
    Insurer,
    Prescription,
    PrescriptionItem,
    Service,
    ServiceCoverage,
)

# Se llama "clinical" y no "health" a propósito: /api/health es la ruta
# PÚBLICA de estado del servidor, y un módulo con ese nombre invita a que
# alguien cuelgue ahí una ruta con datos de pacientes sin autenticación.
router = APIRouter(tags=["clinical"])


def _company(company_id: int, db: Session) -> Company:
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Empresa no encontrada")
    return company


# --- Convenios con aseguradoras ---


class InsurerIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    plan: str = Field(default="", max_length=80)
    coverage_pct: int = Field(default=0, ge=0, le=100)
    copay_gs: int = Field(default=0, ge=0)
    notes: str = ""


class InsurerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    plan: str | None = Field(default=None, max_length=80)
    coverage_pct: int | None = Field(default=None, ge=0, le=100)
    copay_gs: int | None = Field(default=None, ge=0)
    active: bool | None = None
    notes: str | None = None


@router.get("/companies/{company_id}/insurers")
def list_insurers(company_id: int, db: Session = Depends(get_db)):
    _company(company_id, db)
    filas = (
        db.query(Insurer)
        .filter(Insurer.company_id == company_id)
        .order_by(Insurer.name, Insurer.plan)
        .all()
    )
    return [
        {
            "id": i.id, "name": i.name, "plan": i.plan,
            "coverage_pct": i.coverage_pct, "copay_gs": i.copay_gs,
            "active": i.active, "notes": i.notes,
            "coberturas_especificas": db.query(ServiceCoverage)
            .filter(ServiceCoverage.insurer_id == i.id).count(),
        }
        for i in filas
    ]


@router.post("/companies/{company_id}/insurers", status_code=201)
def create_insurer(company_id: int, payload: InsurerIn, db: Session = Depends(get_db)):
    _company(company_id, db)
    repetido = (
        db.query(Insurer)
        .filter(
            Insurer.company_id == company_id,
            Insurer.name == payload.name,
            Insurer.plan == payload.plan,
        )
        .first()
    )
    if repetido:
        raise HTTPException(409, "Ya existe un convenio con esa aseguradora y ese plan")
    insurer = Insurer(company_id=company_id, **payload.model_dump())
    db.add(insurer)
    db.commit()
    db.refresh(insurer)
    return {"id": insurer.id, "name": insurer.name, "plan": insurer.plan}


@router.patch("/companies/{company_id}/insurers/{insurer_id}")
def update_insurer(company_id: int, insurer_id: int, payload: InsurerUpdate,
                   db: Session = Depends(get_db)):
    insurer = db.get(Insurer, insurer_id)
    if not insurer or insurer.company_id != company_id:
        raise HTTPException(404, "Convenio no encontrado")
    for campo, valor in payload.model_dump(exclude_unset=True).items():
        setattr(insurer, campo, valor)
    db.commit()
    return {"ok": True}


class CoverageIn(BaseModel):
    service_id: int
    coverage_pct: int = Field(default=0, ge=0, le=100)
    copay_gs: int = Field(default=0, ge=0)
    excluded: bool = False
    # Lo que la aseguradora paga por esta práctica según su nomenclador,
    # cargado a mano. Si está, gana sobre el porcentaje. 0 = no configurado.
    arancel_gs: int = Field(default=0, ge=0)


@router.put("/companies/{company_id}/insurers/{insurer_id}/coverage")
def set_coverage(company_id: int, insurer_id: int, payload: CoverageIn,
                 db: Session = Depends(get_db)):
    """Cobertura distinta a la del convenio para un estudio puntual."""
    insurer = db.get(Insurer, insurer_id)
    if not insurer or insurer.company_id != company_id:
        raise HTTPException(404, "Convenio no encontrado")
    service = db.get(Service, payload.service_id)
    if not service or service.company_id != company_id:
        raise HTTPException(422, "Ese servicio no es de esta empresa")

    fila = (
        db.query(ServiceCoverage)
        .filter(
            ServiceCoverage.insurer_id == insurer_id,
            ServiceCoverage.service_id == payload.service_id,
        )
        .first()
    )
    if not fila:
        fila = ServiceCoverage(
            company_id=company_id, insurer_id=insurer_id, service_id=payload.service_id
        )
        db.add(fila)
    fila.coverage_pct = payload.coverage_pct
    fila.copay_gs = payload.copay_gs
    fila.excluded = payload.excluded
    fila.arancel_gs = payload.arancel_gs
    db.commit()
    return {"ok": True}


@router.get("/companies/{company_id}/insurers/{insurer_id}/coverage")
def get_coverage(company_id: int, insurer_id: int, db: Session = Depends(get_db)):
    """Qué tiene cargado este convenio, práctica por práctica.

    Sin esto, la pantalla de convenios era de solo escritura: se podía cargar
    un arancel y no había forma de volver a verlo ni de corregirlo.
    """
    insurer = db.get(Insurer, insurer_id)
    if not insurer or insurer.company_id != company_id:
        raise HTTPException(404, "Convenio no encontrado")
    filas = (
        db.query(ServiceCoverage, Service)
        .join(Service, Service.id == ServiceCoverage.service_id)
        .filter(
            ServiceCoverage.company_id == company_id,
            ServiceCoverage.insurer_id == insurer_id,
        )
        .order_by(Service.name)
        .all()
    )
    return [
        {
            "service_id": s.id,
            "servicio": s.name,
            "precio_lista_gs": s.price_gs,
            "coverage_pct": c.coverage_pct,
            "copay_gs": c.copay_gs,
            "excluded": c.excluded,
            "arancel_gs": c.arancel_gs,
        }
        for c, s in filas
    ]


# --- Recetas ---


class ItemIn(BaseModel):
    medication: str = Field(min_length=1, max_length=200)
    dose: str = Field(min_length=1, max_length=120)
    route: str = Field(default="vía oral", max_length=60)
    frequency: str = Field(default="", max_length=120)
    # 0 = pauta a demanda ("si tenés dolor"). NO se convierte en horario fijo:
    # eso sería inventar una indicación que el profesional no dio.
    every_hours: int = Field(default=0, ge=0, le=24)
    duration_days: int = Field(default=0, ge=0, le=365)
    instructions: str = ""


class PrescriptionIn(BaseModel):
    doctor_id: int
    patient_name: str = Field(min_length=1, max_length=120)
    patient_phone: str = Field(min_length=6, max_length=30)
    diagnosis: str = ""
    indications: str = ""
    items: list[ItemIn] = Field(min_length=1)
    # Consentimiento del paciente para recibir recordatorios de toma. Apagado
    # por defecto: se activa cuando el paciente lo pide, no cuando la clínica
    # lo asume.
    reminders_enabled: bool = False
    consent_by: str = Field(default="", max_length=120)


def _serializar(receta: Prescription, db: Session) -> dict:
    doctor = db.get(Doctor, receta.doctor_id)
    items = (
        db.query(PrescriptionItem)
        .filter(PrescriptionItem.prescription_id == receta.id)
        .order_by(PrescriptionItem.id)
        .all()
    )
    return {
        "id": receta.id,
        "doctor": doctor.name if doctor else "",
        "doctor_id": receta.doctor_id,
        "patient_name": receta.patient_name,
        "patient_phone": receta.patient_phone,
        "diagnosis": receta.diagnosis,
        "indications": receta.indications,
        "status": receta.status,
        "reminders_enabled": receta.reminders_enabled,
        "version": receta.version,
        "issued_at": receta.issued_at.isoformat(),
        "items": [
            {
                "id": i.id, "medication": i.medication, "dose": i.dose,
                "route": i.route, "frequency": i.frequency,
                "every_hours": i.every_hours, "duration_days": i.duration_days,
                "instructions": i.instructions,
                "a_demanda": i.every_hours == 0,
            }
            for i in items
        ],
    }


@router.get("/companies/{company_id}/prescriptions")
def list_prescriptions(company_id: int, patient_phone: str | None = None,
                       db: Session = Depends(get_db)):
    _company(company_id, db)
    q = db.query(Prescription).filter(Prescription.company_id == company_id)
    if patient_phone:
        q = q.filter(Prescription.patient_phone == patient_phone)
    return [
        _serializar(r, db)
        for r in q.order_by(Prescription.issued_at.desc()).limit(100).all()
    ]


@router.post("/companies/{company_id}/prescriptions", status_code=201)
def create_prescription(company_id: int, payload: PrescriptionIn,
                        db: Session = Depends(get_db)):
    """Carga una receta y, si hay consentimiento, programa los recordatorios.

    La respuesta dice SIEMPRE si quedaron programados y, cuando no, por qué:
    que la clínica crea que el paciente va a recibir avisos que nunca van a
    salir es peor que no ofrecer la función.
    """
    _company(company_id, db)
    doctor = db.get(Doctor, payload.doctor_id)
    if not doctor or doctor.company_id != company_id:
        raise HTTPException(422, "Ese profesional no es de esta empresa")

    receta = Prescription(
        company_id=company_id,
        doctor_id=payload.doctor_id,
        patient_name=payload.patient_name,
        patient_phone=payload.patient_phone.strip(),
        diagnosis=payload.diagnosis,
        indications=payload.indications,
        reminders_enabled=payload.reminders_enabled,
        consent_by=payload.consent_by,
        consent_at=datetime.now(timezone.utc).replace(tzinfo=None)
        if payload.reminders_enabled else None,
    )
    db.add(receta)
    db.flush()
    for item in payload.items:
        db.add(PrescriptionItem(
            company_id=company_id, prescription_id=receta.id, **item.model_dump()
        ))
    db.commit()
    db.refresh(receta)

    recordatorios = medication.programar(db, receta)
    db.commit()
    return {**_serializar(receta, db), "recordatorios": recordatorios}


@router.patch("/companies/{company_id}/prescriptions/{prescription_id}")
def update_prescription(company_id: int, prescription_id: int,
                        payload: PrescriptionIn, db: Session = Depends(get_db)):
    """Edita la receta: da de baja las tomas viejas y reprograma.

    Sin la baja, el paciente recibiría la dosis NUEVA en los horarios VIEJOS.
    """
    receta = db.get(Prescription, prescription_id)
    if not receta or receta.company_id != company_id:
        raise HTTPException(404, "Receta no encontrada")
    doctor = db.get(Doctor, payload.doctor_id)
    if not doctor or doctor.company_id != company_id:
        raise HTTPException(422, "Ese profesional no es de esta empresa")

    canceladas = medication.cancelar(db, receta)
    receta.version += 1
    receta.doctor_id = payload.doctor_id
    receta.patient_name = payload.patient_name
    receta.patient_phone = payload.patient_phone.strip()
    receta.diagnosis = payload.diagnosis
    receta.indications = payload.indications
    if payload.reminders_enabled and not receta.reminders_enabled:
        receta.consent_at = datetime.now(timezone.utc).replace(tzinfo=None)
        receta.consent_by = payload.consent_by
    receta.reminders_enabled = payload.reminders_enabled

    db.query(PrescriptionItem).filter(
        PrescriptionItem.prescription_id == receta.id,
        PrescriptionItem.company_id == company_id,
    ).delete()
    for item in payload.items:
        db.add(PrescriptionItem(
            company_id=company_id, prescription_id=receta.id, **item.model_dump()
        ))
    db.commit()
    db.refresh(receta)

    recordatorios = medication.programar(db, receta)
    db.commit()
    return {
        **_serializar(receta, db),
        "tomas_canceladas": canceladas,
        "recordatorios": recordatorios,
    }


@router.post("/companies/{company_id}/prescriptions/{prescription_id}/cancel")
def cancel_prescription(company_id: int, prescription_id: int,
                        db: Session = Depends(get_db)):
    """Suspende el tratamiento: no salen más recordatorios."""
    receta = db.get(Prescription, prescription_id)
    if not receta or receta.company_id != company_id:
        raise HTTPException(404, "Receta no encontrada")
    canceladas = medication.cancelar(db, receta)
    receta.status = "cancelled"
    receta.reminders_enabled = False
    db.commit()
    return {"ok": True, "tomas_canceladas": canceladas}
