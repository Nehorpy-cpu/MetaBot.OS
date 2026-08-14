"""Portal del Profesional (bloque 4).

Cada médico entra con su propio usuario y ve SUS pacientes: el resumen del
día como un post-it, y la ficha completa de cada uno con lo que le recetó.

Dos reglas gobiernan todo este archivo:

1. **El doctor sale de la membresía, nunca del request.** Si el id del
   profesional viniera por querystring, cualquier médico podría escribir el
   número del colega de al lado y leerle los pacientes. Sale de
   `Membership.doctor_id`, que es un dato del servidor.
2. **Recetas propias.** `list_prescriptions` del panel filtra por empresa, que
   está bien para la recepcionista y mal para acá: un médico no tiene por qué
   ver lo que recetó otro. Todas las consultas de este archivo llevan
   `doctor_id` además de `company_id`.
"""
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import previsita
from ..auth import Identity, audit, get_identity, hash_password
from ..db import get_db
from ..models import (
    Appointment, Company, Doctor, Membership, Prescription, PrescriptionItem, User,
)
from ..permissions import Perm, Role, role_has

router = APIRouter(prefix="/companies/{company_id}/portal", tags=["portal"])


# ─── Quién está preguntando ──────────────────────────────────────────────


def _mi_doctor(db: Session, company_id: int, identity: Identity) -> Doctor:
    """El profesional dueño de esta sesión.

    El operador de la plataforma no tiene un doctor propio: para que pueda
    revisar el portal sin inventarse una identidad médica, se le exige que
    diga cuál con `?doctor_id=`, y eso se resuelve en `_doctor_pedido`.
    """
    miembro = (
        db.query(Membership)
        .filter(
            Membership.user_id == identity.user_id,
            Membership.company_id == company_id,
            Membership.status == "active",
        )
        .first()
    )
    if not miembro or not miembro.doctor_id:
        if identity.is_platform:
            # El operador de la plataforma no ES un médico. Que el mensaje lo
            # diga: si no, parece que se rompió algo del vínculo.
            raise HTTPException(
                403,
                "Sos el operador de la plataforma, no un profesional: "
                "indicá de quién querés ver el portal con ?doctor_id=",
            )
        raise HTTPException(
            403, "Tu usuario no está vinculado a ningún profesional de esta empresa."
        )
    doctor = db.get(Doctor, miembro.doctor_id)
    # El doctor puede haber sido borrado con la membresía todavía apuntándolo.
    if not doctor or doctor.company_id != company_id:
        raise HTTPException(404, "El profesional vinculado ya no existe.")
    return doctor


def _doctor_pedido(
    db: Session, company_id: int, identity: Identity, doctor_id: int | None
) -> Doctor:
    """El doctor de la sesión, o el pedido si quien mira es la plataforma."""
    if identity.is_platform and doctor_id:
        doctor = db.get(Doctor, doctor_id)
        if not doctor or doctor.company_id != company_id:
            raise HTTPException(404, "Profesional no encontrado")
        return doctor
    return _mi_doctor(db, company_id, identity)


def _company(db: Session, company_id: int) -> Company:
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Empresa no encontrada")
    return company


# ─── El día del profesional ──────────────────────────────────────────────


@router.get("/me")
def quien_soy(
    company_id: int,
    doctor_id: int | None = None,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    doctor = _doctor_pedido(db, company_id, identity, doctor_id)
    return {
        "doctor_id": doctor.id,
        "nombre": doctor.name,
        "especialidad": doctor.specialty,
        "empresa": _company(db, company_id).name,
    }


@router.get("/agenda")
def mi_agenda(
    company_id: int,
    dia: str = Query(default="", description="AAAA-MM-DD; vacío = hoy"),
    doctor_id: int | None = None,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Los post-it del día: un paciente por tarjeta, con lo justo.

    Es el mismo resumen que se le manda por WhatsApp la noche anterior. Se
    arma con la misma función a propósito: si acá se armara aparte, el día que
    cambie una regla —por ejemplo la de no cruzar historiales entre personas
    que comparten teléfono— habría que acordarse de cambiarla en dos lados.
    """
    doctor = _doctor_pedido(db, company_id, identity, doctor_id)
    try:
        cuando = date.fromisoformat(dia) if dia else date.today()
    except ValueError:
        raise HTTPException(422, "Fecha inválida: se espera AAAA-MM-DD")
    return previsita.armar(db, _company(db, company_id), doctor, cuando)


# ─── La ficha del paciente ───────────────────────────────────────────────


@router.get("/pacientes")
def mis_pacientes(
    company_id: int,
    q: str = Query(default="", max_length=120),
    doctor_id: int | None = None,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Los pacientes que pasaron por este profesional. Solo los suyos."""
    doctor = _doctor_pedido(db, company_id, identity, doctor_id)
    consulta = (
        db.query(Appointment)
        .filter(
            Appointment.company_id == company_id,
            Appointment.doctor_id == doctor.id,
        )
    )
    if q.strip():
        consulta = consulta.filter(Appointment.patient_name.ilike(f"%{q.strip()}%"))

    # Se agrupa en Python y no con DISTINCT porque hace falta quedarse con la
    # visita MÁS RECIENTE de cada persona y contar cuántas hubo.
    vistos: dict[str, dict] = {}
    for cita in consulta.order_by(Appointment.scheduled_at.desc()).limit(500).all():
        clave = previsita._clave_de_nombre(cita.patient_name) or cita.patient_phone
        if clave not in vistos:
            vistos[clave] = {
                "nombre": cita.patient_name,
                "telefono": cita.patient_phone,
                "ultima_visita": cita.scheduled_at.isoformat(),
                "visitas": 0,
            }
        vistos[clave]["visitas"] += 1
    return sorted(vistos.values(), key=lambda p: p["ultima_visita"], reverse=True)


@router.get("/pacientes/ficha")
def ficha_del_paciente(
    company_id: int,
    telefono: str = Query(max_length=30),
    nombre: str = Query(default="", max_length=120),
    doctor_id: int | None = None,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Todo lo que este profesional tiene de este paciente.

    El teléfono NO alcanza para identificar a una persona: en Paraguay es
    normal que una familia entera use el mismo número. Por eso el historial se
    cruza con el nombre igual que en el resumen pre-visita, y si con ese
    número hay registros a nombre de otra persona se avisa en vez de mezclar
    dos historias clínicas en una.
    """
    doctor = _doctor_pedido(db, company_id, identity, doctor_id)

    visitas = (
        db.query(Appointment)
        .filter(
            Appointment.company_id == company_id,
            Appointment.doctor_id == doctor.id,
            previsita._filtro_de_telefono(Appointment.patient_phone, previsita._telefono(telefono)),
        )
        .order_by(Appointment.scheduled_at.desc())
        .limit(100)
        .all()
    )
    mias = [v for v in visitas if not nombre or previsita._mismo_paciente(v.patient_name, nombre)]
    otra_persona = len(mias) < len(visitas)

    recetas = (
        db.query(Prescription)
        .filter(
            Prescription.company_id == company_id,
            Prescription.doctor_id == doctor.id,   # ← solo lo que recetó ÉL
            previsita._filtro_de_telefono(Prescription.patient_phone, previsita._telefono(telefono)),
        )
        .order_by(Prescription.issued_at.desc())
        .limit(50)
        .all()
    )
    recetas_mias = [
        r for r in recetas if not nombre or previsita._mismo_paciente(r.patient_name, nombre)
    ]
    otra_persona = otra_persona or len(recetas_mias) < len(recetas)

    # Los medicamentos van en su propia tabla y no hay relación cargada: se
    # traen todos de una, no una consulta por receta.
    ids = [r.id for r in recetas_mias]
    items: dict[int, list] = {}
    if ids:
        for it in (
            db.query(PrescriptionItem)
            .filter(
                PrescriptionItem.company_id == company_id,
                PrescriptionItem.prescription_id.in_(ids),
            )
            .order_by(PrescriptionItem.id)
            .all()
        ):
            items.setdefault(it.prescription_id, []).append(it)

    return {
        "paciente": nombre or (mias[0].patient_name if mias else ""),
        "telefono": telefono,
        "numero_compartido": otra_persona,
        "visitas": [
            {
                "fecha": v.scheduled_at.isoformat(),
                "estado": v.status,
                "motivo": v.notes or "",
            }
            for v in mias
        ],
        "recetas": [
            {
                "id": r.id,
                "fecha": r.issued_at.date().isoformat(),
                "diagnostico": r.diagnosis,
                "indicaciones": r.indications,
                "estado": r.status,
                "medicacion": [
                    {
                        "nombre": m.medication,
                        "dosis": m.dose,
                        "via": m.route,
                        "frecuencia": m.frequency,
                        "cada_horas": m.every_hours,
                        "dias": m.duration_days,
                        "indicaciones": m.instructions,
                    }
                    for m in items.get(r.id, [])
                ],
            }
            for r in recetas_mias
        ],
    }


# ─── Alta de accesos (lo hace la clínica, no el médico) ──────────────────


class AccesoNuevo(BaseModel):
    doctor_id: int
    email: str = Field(min_length=5, max_length=320)


@router.post("/accesos", status_code=201)
def crear_acceso(
    company_id: int,
    payload: AccesoNuevo,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Le da un login propio a un profesional de la clínica.

    Lo hace quien administra la empresa, nunca el profesional. La clave
    temporal se devuelve UNA sola vez —después solo queda su hash— y se
    genera en el servidor: una clave que elige un tercero es una clave que
    ese tercero conoce.
    """
    if not identity.is_platform:
        miembro = (
            db.query(Membership)
            .filter(
                Membership.user_id == identity.user_id,
                Membership.company_id == company_id,
                Membership.status == "active",
            )
            .first()
        )
        if not miembro or not role_has(miembro.role, Perm.MANAGE_MEMBERS):
            raise HTTPException(403, "Solo el dueño de la empresa da accesos")

    doctor = db.get(Doctor, payload.doctor_id)
    if not doctor or doctor.company_id != company_id:
        raise HTTPException(404, "Profesional no encontrado")

    email = payload.email.strip().lower()
    if "@" not in email:
        raise HTTPException(422, "Email inválido")

    ya = (
        db.query(Membership)
        .filter(Membership.company_id == company_id, Membership.doctor_id == doctor.id)
        .first()
    )
    if ya:
        raise HTTPException(409, f"{doctor.name} ya tiene un acceso creado.")

    import secrets

    clave = secrets.token_urlsafe(9)
    user = db.query(User).filter(User.email == email).first()
    if user:
        # Un usuario que ya existe NO cambia de clave por esto: sería una
        # forma de resetearle la contraseña a cualquiera sabiendo su email.
        clave = ""
    else:
        user = User(email=email, password_hash=hash_password(clave), full_name=doctor.name)
        db.add(user)
        db.flush()

    if (
        db.query(Membership)
        .filter(Membership.user_id == user.id, Membership.company_id == company_id)
        .first()
    ):
        raise HTTPException(409, "Ese email ya es miembro de esta empresa.")

    db.add(
        Membership(
            user_id=user.id,
            company_id=company_id,
            role=Role.PROFESSIONAL.value,
            doctor_id=doctor.id,
        )
    )
    db.commit()
    audit(
        db, "portal.acceso", user_id=identity.user_id, company_id=company_id,
        detail={"doctor_id": doctor.id, "email": email},
    )
    return {
        "email": email,
        "doctor": doctor.name,
        # Vacía si el usuario ya existía: entra con la que ya tenía.
        "clave_temporal": clave,
        "aviso": "Esta clave se muestra una sola vez. Pasásela al profesional.",
    }


@router.get("/accesos")
def listar_accesos(
    company_id: int,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Qué profesionales tienen login. Sin claves ni hashes, obviamente."""
    filas = (
        db.query(Membership, User, Doctor)
        .join(User, User.id == Membership.user_id)
        .join(Doctor, Doctor.id == Membership.doctor_id)
        .filter(
            Membership.company_id == company_id,
            Membership.role == Role.PROFESSIONAL.value,
        )
        .all()
    )
    return [
        {
            "doctor_id": d.id,
            "doctor": d.name,
            "email": u.email,
            "activo": m.status == "active" and u.status == "active",
        }
        for m, u, d in filas
    ]
