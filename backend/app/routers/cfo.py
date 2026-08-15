"""CFO de Finanzas: administración del bloque.

Fase 1: quién puede preguntar. Las métricas, los conectores y los reportes
llegan en las fases siguientes; sus rutas ya están reservadas en el mapa de
bloques de `packs.py` para que nazcan gateadas y no haya que acordarse.

Todo lo de acá lo hace quien administra la empresa, nunca el dueño desde
WhatsApp: dar de alta un número autorizado es exactamente la operación que un
atacante querría hacer.
"""
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import cfo
from ..auth import Identity, audit, get_identity
from ..db import get_db
from ..models import Company, FinanceIdentity, Membership, User
from ..permissions import Perm, role_has

router = APIRouter(prefix="/companies/{company_id}/cfo", tags=["cfo"])


def _puede_administrar(db: Session, company_id: int, identity: Identity) -> None:
    """Dar de alta un número que puede consultar saldos es administración."""
    if identity.is_platform:
        return
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
        raise HTTPException(
            403, "Solo quien administra la empresa autoriza números del CFO"
        )


def _company(db: Session, company_id: int) -> Company:
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Empresa no encontrada")
    return company


def _salida(i: FinanceIdentity) -> dict:
    return {
        "id": i.id,
        "phone": i.phone,
        "nombre": i.nombre,
        "user_id": i.user_id,
        "sensibilidad_max": i.sensibilidad_max,
        # Si tiene PIN, no CUÁL es. El hash tampoco sale de la base.
        "tiene_pin": bool(i.pin_hash),
        "pin_bloqueado": bool(i.pin_bloqueado_hasta),
        "activo": i.activo,
        "ultimo_uso_at": i.ultimo_uso_at.isoformat() if i.ultimo_uso_at else None,
    }


class IdentidadIn(BaseModel):
    phone: str = Field(min_length=6, max_length=30)
    nombre: str = Field(default="", max_length=200)
    sensibilidad_max: str = Field(default="baja", pattern="^(baja|media|alta)$")
    user_id: int | None = None


class IdentidadUpdate(BaseModel):
    nombre: str | None = Field(default=None, max_length=200)
    sensibilidad_max: str | None = Field(default=None, pattern="^(baja|media|alta)$")
    activo: bool | None = None


class PinIn(BaseModel):
    pin: str = Field(min_length=4, max_length=12)


@router.get("/identidades")
def listar_identidades(
    company_id: int,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Qué números pueden consultar las finanzas de esta empresa."""
    _puede_administrar(db, company_id, identity)
    _company(db, company_id)
    filas = (
        db.query(FinanceIdentity)
        .filter(FinanceIdentity.company_id == company_id)
        .order_by(FinanceIdentity.nombre, FinanceIdentity.phone)
        .all()
    )
    return [_salida(i) for i in filas]


@router.post("/identidades", status_code=201)
def crear_identidad(
    company_id: int,
    payload: IdentidadIn,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Autoriza un número. Nace SIN PIN y por lo tanto sin acceso a lo sensible."""
    _puede_administrar(db, company_id, identity)
    _company(db, company_id)

    digitos = cfo.solo_digitos(payload.phone)
    if len(digitos) < 6:
        raise HTTPException(422, "Ese teléfono no tiene dígitos suficientes")

    if payload.user_id is not None:
        # Un usuario del panel de OTRA empresa no se puede vincular acá: sería
        # atarle a este número una identidad que no le corresponde.
        usuario = db.get(User, payload.user_id)
        miembro = (
            db.query(Membership)
            .filter(
                Membership.user_id == payload.user_id,
                Membership.company_id == company_id,
                Membership.status == "active",
            )
            .first()
        )
        if not usuario or not miembro:
            raise HTTPException(422, "Ese usuario no es miembro de esta empresa")

    fila = FinanceIdentity(
        company_id=company_id,
        phone=digitos,
        nombre=payload.nombre.strip(),
        sensibilidad_max=payload.sensibilidad_max,
        user_id=payload.user_id,
    )
    db.add(fila)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409,
            {
                "motivo": "Ese número ya está autorizado en esta empresa.",
                "codigo": "numero_repetido",
            },
        )
    db.refresh(fila)
    audit(
        db, "cfo.identidad.alta", user_id=identity.user_id, company_id=company_id,
        detail={"phone": digitos, "sensibilidad": payload.sensibilidad_max},
    )
    return _salida(fila)


def _identidad(db: Session, company_id: int, identidad_id: int) -> FinanceIdentity:
    fila = db.get(FinanceIdentity, identidad_id)
    if not fila or fila.company_id != company_id:
        raise HTTPException(404, "Identidad no encontrada")
    return fila


@router.patch("/identidades/{identidad_id}")
def editar_identidad(
    company_id: int,
    identidad_id: int,
    payload: IdentidadUpdate,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    _puede_administrar(db, company_id, identity)
    fila = _identidad(db, company_id, identidad_id)
    datos = payload.model_dump(exclude_unset=True)
    antes = {"sensibilidad_max": fila.sensibilidad_max, "activo": fila.activo}
    for campo, valor in datos.items():
        setattr(fila, campo, valor)
    db.commit()
    db.refresh(fila)
    # Subirle el techo a un número es un cambio de permisos: queda escrito.
    if "sensibilidad_max" in datos or "activo" in datos:
        audit(
            db, "cfo.identidad.cambio", user_id=identity.user_id, company_id=company_id,
            detail={"identidad": identidad_id, "antes": antes, "despues": datos},
        )
    return _salida(fila)


@router.put("/identidades/{identidad_id}/pin")
def poner_pin(
    company_id: int,
    identidad_id: int,
    payload: PinIn,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Configura el PIN. Se guarda hasheado y no vuelve a salir de la base."""
    _puede_administrar(db, company_id, identity)
    fila = _identidad(db, company_id, identidad_id)
    try:
        cfo.guardar_pin(db, fila, payload.pin)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    # El PIN NO va en el detalle de auditoría. Ni truncado.
    audit(
        db, "cfo.identidad.pin", user_id=identity.user_id, company_id=company_id,
        detail={"identidad": identidad_id},
    )
    return {"ok": True, "tiene_pin": True}


@router.delete("/identidades/{identidad_id}", status_code=204)
def quitar_identidad(
    company_id: int,
    identidad_id: int,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    _puede_administrar(db, company_id, identity)
    fila = _identidad(db, company_id, identidad_id)
    db.delete(fila)
    db.commit()
    audit(
        db, "cfo.identidad.baja", user_id=identity.user_id, company_id=company_id,
        detail={"identidad": identidad_id, "phone": fila.phone},
    )
    return Response(status_code=204)


@router.get("/riesgos")
def catalogo_de_riesgos(
    company_id: int,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Qué nivel tiene cada métrica, para que la administración lo vea.

    Es de solo lectura a propósito: la clasificación vive en código y cambia
    por commit, no desde un panel. Un saldo bancario que amanece en riesgo
    bajo sin que nadie sepa quién lo movió es exactamente lo que hay que
    evitar.
    """
    _puede_administrar(db, company_id, identity)
    _company(db, company_id)
    por_nivel: dict[str, list[str]] = {"baja": [], "media": [], "alta": []}
    for metrica, riesgo in sorted(cfo.RIESGO_POR_METRICA.items()):
        por_nivel[riesgo.value].append(metrica)
    return {
        "niveles": por_nivel,
        "nota": (
            "Una métrica que no figure acá se trata como de riesgo ALTO: "
            "una consulta nueva sin clasificar no puede nacer siendo pública."
        ),
    }
