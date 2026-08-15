"""Planes, consumo y la clave de OpenAI de cada empresa.

Tres cosas que van juntas porque son la misma conversación con el cliente:
qué contrató, cuánto lleva usado, y con la clave de quién se le está
atendiendo.

Quién puede qué:

- **Cualquiera de la empresa** ve su plan y su consumo. Ocultarle a un cliente
  lo que consume es cómo se llega a una discusión por la factura.
- **Quien administra la empresa** pide tener su propia clave. Pedir no es
  cargar.
- **Solo el admin de la plataforma** cambia el plan y carga la clave. Un
  cliente que se cambia solo al plan más grande no es un cliente, es un
  regalo; y una credencial de un tercero no se carga sola.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import cfo_secretos, consumo, planes
from ..auth import Identity, audit, get_identity
from ..db import get_db
from ..models import Company, Membership

router = APIRouter(tags=["planes"])


def _company(db: Session, company_id: int) -> Company:
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Empresa no encontrada")
    return company


def _es_miembro(db: Session, company_id: int, identity: Identity) -> None:
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
    if not miembro:
        raise HTTPException(404, "Empresa no encontrada")


def _solo_plataforma(identity: Identity) -> None:
    if not identity.is_platform:
        raise HTTPException(
            403,
            {
                "motivo": "Esto lo hace el administrador de la plataforma.",
                "codigo": "solo_plataforma",
            },
        )


@router.get("/planes")
def catalogo_de_planes():
    """Lo que vendemos. No depende de la empresa: es el catálogo comercial."""
    return planes.catalogo()


@router.get("/companies/{company_id}/consumo")
def consumo_de_la_empresa(
    company_id: int,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Cuánto lleva usado este mes y qué le queda.

    Lo ve cualquiera de la empresa, no solo quien administra: ocultarle a un
    cliente lo que consume es cómo se llega a una discusión por la factura.
    """
    _es_miembro(db, company_id, identity)
    return consumo.resumen(db, _company(db, company_id))


class PlanIn(BaseModel):
    plan: str = Field(min_length=2, max_length=30)


@router.put("/companies/{company_id}/plan")
def cambiar_plan(
    company_id: int,
    payload: PlanIn,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Cambia el plan. Solo la plataforma.

    Un cliente que se cambia solo al plan más grande no es un cliente, es un
    regalo.
    """
    _solo_plataforma(identity)
    company = _company(db, company_id)
    if payload.plan not in planes.PLANES:
        raise HTTPException(
            422,
            {"motivo": f"Plan desconocido. Válidos: "
                       f"{', '.join(planes.PLANES)}.",
             "codigo": "plan_desconocido"},
        )
    antes = company.plan
    company.plan = payload.plan
    db.commit()
    audit(db, "plan.cambio", user_id=identity.user_id, company_id=company_id,
          detail={"antes": antes, "despues": payload.plan})
    return consumo.resumen(db, company)


@router.post("/companies/{company_id}/clave-openai/solicitar")
def solicitar_clave(
    company_id: int,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """El cliente pide tener su propia clave. Pedir no es cargar.

    Queda la fecha del pedido; el alta la hace el admin de la plataforma
    después de que el cliente le pase la credencial por un canal seguro. Que
    la escriba el cliente en un formulario nuestro sería enseñarle a pegar su
    credencial de OpenAI en cualquier lado.
    """
    _es_miembro(db, company_id, identity)
    company = _company(db, company_id)
    if company.openai_key_cifrada:
        return {"ya_tiene": True, "solicitada": None}
    company.openai_key_solicitada_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    audit(db, "clave_openai.solicitud", user_id=identity.user_id,
          company_id=company_id, detail={})
    return {
        "ya_tiene": False,
        "solicitada": company.openai_key_solicitada_at.isoformat(),
        "aviso": (
            "Pedido registrado. El equipo de MetaBot te va a contactar para "
            "cargarla. No la escribas por chat ni por correo."
        ),
    }


@router.get("/clave-openai/solicitudes")
def solicitudes_pendientes(
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Qué empresas pidieron su propia clave y todavía no la tienen."""
    _solo_plataforma(identity)
    filas = (
        db.query(Company)
        .filter(
            Company.openai_key_solicitada_at.isnot(None),
            Company.openai_key_cifrada == "",
        )
        .order_by(Company.openai_key_solicitada_at)
        .all()
    )
    return [
        {
            "company_id": c.id,
            "nombre": c.name,
            "plan": c.plan,
            "solicitada": c.openai_key_solicitada_at.isoformat(),
            # El consumo de la empresa que pide: es el dato con el que se
            # decide si le conviene tener la suya.
            "consumo": consumo.resumen(db, c)["consumo_de_ia"],
        }
        for c in filas
    ]


class ClaveIn(BaseModel):
    clave: str = Field(min_length=20, max_length=300)


@router.put("/companies/{company_id}/clave-openai")
def cargar_clave(
    company_id: int,
    payload: ClaveIn,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Carga la clave de OpenAI de una empresa. Solo la plataforma.

    Se guarda cifrada y no vuelve a salir. Desde acá, el consumo de esa
    empresa se lo factura OpenAI a ella.
    """
    _solo_plataforma(identity)
    company = _company(db, company_id)
    clave = payload.clave.strip()
    if not clave.startswith("sk-"):
        raise HTTPException(
            422,
            {"motivo": "Eso no tiene el formato de una clave de OpenAI.",
             "codigo": "clave_invalida"},
        )
    try:
        company.openai_key_cifrada = cfo_secretos.cifrar(clave)
    except cfo_secretos.SinLlave as exc:
        raise HTTPException(503, {"motivo": str(exc),
                                  "codigo": "sin_llave_de_cifrado"})
    company.openai_key_solicitada_at = None
    db.commit()
    # En el detalle NO va la clave, ni truncada, ni su largo.
    audit(db, "clave_openai.alta", user_id=identity.user_id,
          company_id=company_id, detail={})
    return {"ok": True, "clave_en_uso": "propia"}


@router.delete("/companies/{company_id}/clave-openai", status_code=200)
def quitar_clave(
    company_id: int,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Saca la clave propia. El consumo vuelve a pagarlo la plataforma."""
    _solo_plataforma(identity)
    company = _company(db, company_id)
    company.openai_key_cifrada = ""
    db.commit()
    audit(db, "clave_openai.baja", user_id=identity.user_id,
          company_id=company_id, detail={})
    return {"ok": True, "clave_en_uso": "plataforma"}
