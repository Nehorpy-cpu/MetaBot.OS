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

from datetime import date, datetime, timezone

from .. import cfo, cfo_metricas, cfo_motor
from ..auth import Identity, audit, get_identity
from ..db import get_db
from ..models import (
    Company, FinanceIdentity, FinanceMetricState, Membership, User,
)
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


# ─── Métricas: la capa semántica ─────────────────────────────────────────
#
# Una métrica no se puede usar por existir. Tiene que estar aprobada para ESTA
# empresa, con versión y fecha de vigencia. Y no se puede aprobar si su fuente
# no está conectada: sería prometer un número que no va a llegar.


class AprobarMetrica(BaseModel):
    # La versión del catálogo que se está aprobando. Va explícita para que
    # aprobar sea un acto sobre una definición concreta y no sobre "lo que
    # diga el código hoy".
    version: int = Field(ge=1)
    vigente_desde: str | None = None
    notas: str = Field(default="", max_length=500)


@router.get("/metricas")
def listar_metricas(
    company_id: int,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Qué puede contestar el CFO de esta empresa, y qué no todavía."""
    _puede_administrar(db, company_id, identity)
    return cfo_motor.catalogo_para(db, _company(db, company_id))


@router.post("/metricas/{clave}/aprobar")
def aprobar_metrica(
    company_id: int,
    clave: str,
    payload: AprobarMetrica,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Aprueba una definición y la deja vigente.

    Queda ACTIVA en un solo paso a propósito: aprobar sin activar deja a la
    empresa con una métrica bendecida que igual no contesta, y a alguien
    preguntándose por qué.
    """
    _puede_administrar(db, company_id, identity)
    _company(db, company_id)

    metrica = cfo_metricas.CATALOGO.get(clave)
    if not metrica:
        raise HTTPException(404, "Esa métrica no existe en el catálogo")
    if payload.version != metrica.version:
        raise HTTPException(
            409,
            {
                "motivo": (
                    f"Estás aprobando la versión {payload.version} y el "
                    f"catálogo tiene la {metrica.version}. Revisá la "
                    "definición antes de aprobarla."
                ),
                "codigo": "version_desactualizada",
                "version_catalogo": metrica.version,
            },
        )

    faltan = cfo_metricas.faltantes(clave, cfo_motor.FUENTES_DISPONIBLES)
    if faltan:
        raise HTTPException(
            409,
            {
                "motivo": cfo_metricas.explicar_faltante(
                    clave, cfo_motor.FUENTES_DISPONIBLES
                ),
                "codigo": "fuente_no_conectada",
                "faltantes": faltan,
            },
        )

    desde = None
    if payload.vigente_desde:
        try:
            desde = date.fromisoformat(payload.vigente_desde)
        except ValueError:
            raise HTTPException(422, "Fecha inválida: se espera AAAA-MM-DD")

    fila = (
        db.query(FinanceMetricState)
        .filter(
            FinanceMetricState.company_id == company_id,
            FinanceMetricState.clave == clave,
        )
        .first()
    )
    if fila is None:
        fila = FinanceMetricState(company_id=company_id, clave=clave)
        db.add(fila)
    fila.version = payload.version
    fila.estado = "activa"
    fila.aprobada_por = identity.user_id
    fila.aprobada_at = datetime.now(timezone.utc).replace(tzinfo=None)
    fila.vigente_desde = desde
    fila.notas = payload.notas[:500]
    db.commit()

    audit(
        db, "cfo.metrica.aprobar", user_id=identity.user_id, company_id=company_id,
        detail={"clave": clave, "version": payload.version,
                "vigente_desde": payload.vigente_desde},
    )
    return {"clave": clave, "estado": "activa", "version": payload.version}


@router.post("/metricas/{clave}/deprecar")
def deprecar_metrica(
    company_id: int,
    clave: str,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Saca una métrica de circulación sin borrar su historia."""
    _puede_administrar(db, company_id, identity)
    fila = (
        db.query(FinanceMetricState)
        .filter(
            FinanceMetricState.company_id == company_id,
            FinanceMetricState.clave == clave,
        )
        .first()
    )
    if not fila:
        raise HTTPException(404, "Esa métrica no está definida en esta empresa")
    fila.estado = "deprecada"
    db.commit()
    audit(db, "cfo.metrica.deprecar", user_id=identity.user_id,
          company_id=company_id, detail={"clave": clave})
    return {"clave": clave, "estado": "deprecada"}


class ConsultaMetrica(BaseModel):
    desde: str
    hasta: str


@router.post("/metricas/{clave}/calcular")
def calcular_metrica(
    company_id: int,
    clave: str,
    payload: ConsultaMetrica,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Calcula una métrica. Es el mismo motor que va a usar el bot.

    Existe como endpoint para que la administración pueda comparar el número
    contra su reporte oficial ANTES de que se lo conteste a nadie por
    WhatsApp. Un CFO que se estrena en producción es un CFO sin probar.
    """
    _puede_administrar(db, company_id, identity)
    company = _company(db, company_id)
    try:
        desde = date.fromisoformat(payload.desde)
        hasta = date.fromisoformat(payload.hasta)
    except ValueError:
        raise HTTPException(422, "Fechas inválidas: se esperan AAAA-MM-DD")
    if desde > hasta:
        raise HTTPException(422, "El período empieza después de terminar")

    r = cfo_motor.calcular(db, company, clave, desde, hasta)
    return {
        "clave": r.clave,
        "nombre": r.nombre,
        "version": r.version,
        "desde": r.desde.isoformat(),
        "hasta": r.hasta.isoformat(),
        "valor": r.valor,
        "unidad": r.unidad,
        "calculable": r.calculable,
        "corte": r.corte.isoformat(),
        "fuentes": list(r.fuentes),
        "completitud": r.completitud,
        "advertencias": list(r.advertencias),
        "detalle": r.detalle,
    }
