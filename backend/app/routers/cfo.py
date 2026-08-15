"""CFO de Finanzas: administración del bloque.

Fase 1: quién puede preguntar. Las métricas, los conectores y los reportes
llegan en las fases siguientes; sus rutas ya están reservadas en el mapa de
bloques de `packs.py` para que nazcan gateadas y no haya que acordarse.

Todo lo de acá lo hace quien administra la empresa, nunca el dueño desde
WhatsApp: dar de alta un número autorizado es exactamente la operación que un
atacante querría hacer.
"""
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from datetime import date, datetime, timezone

import json

from .. import (
    cfo, cfo_conectores, cfo_csv, cfo_fuentes_externas, cfo_memoria,
    cfo_metricas, cfo_motor, cfo_reportes, cfo_secretos, consumo,
)
from ..auth import Identity, audit, get_identity
from ..db import get_db
from ..config import CFO_REPORT_BASE_URL
from ..models import (
    Company, FinanceConnector, FinanceIdentity, FinanceMemory,
    FinanceMetricState, FinanceRecord, FinanceReport, FinanceReportToken,
    Membership, User,
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

    faltan = cfo_metricas.faltantes(clave, cfo_motor.fuentes_de(db, company_id))
    if faltan:
        raise HTTPException(
            409,
            {
                "motivo": cfo_metricas.explicar_faltante(
                    clave, cfo_motor.fuentes_de(db, company_id)
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


# ─── Informes privados ───────────────────────────────────────────────────


class InformeIn(BaseModel):
    metricas: list[str] = Field(min_length=1, max_length=15)
    desde: str
    hasta: str
    titulo: str = Field(default="", max_length=200)
    # Para lo más sensible: el enlace sirve una sola vez, así que reenviarlo
    # por un grupo de WhatsApp deja de ser una filtración.
    un_solo_uso: bool = False
    horas_de_vigencia: int = Field(default=24, ge=1, le=720)


@router.post("/informes", status_code=201)
def crear_informe(
    company_id: int,
    payload: InformeIn,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Calcula, congela y devuelve el enlace. El token se muestra UNA vez."""
    _puede_administrar(db, company_id, identity)
    company = _company(db, company_id)
    try:
        desde = date.fromisoformat(payload.desde)
        hasta = date.fromisoformat(payload.hasta)
    except ValueError:
        raise HTTPException(422, "Fechas inválidas: se esperan AAAA-MM-DD")
    if desde > hasta:
        raise HTTPException(422, "El período empieza después de terminar")

    desconocidas = [m for m in payload.metricas if m not in cfo_metricas.CATALOGO]
    if desconocidas:
        raise HTTPException(422, f"Métricas que no existen: {desconocidas}")

    # Antes de calcular nada: sin base configurada el enlace saldría relativo
    # (`/r/xxx`), el dueño lo pegaría en un WhatsApp y no iría a ningún lado.
    # Y sobre http el token viaja en claro. Es un error de despliegue, y tiene
    # que sonar acá, no en el teléfono del cliente.
    # El tope de informes del plan. Cada informe es un cálculo y un enlace
    # que hay que servir: no es gratis emitirlos.
    if not consumo.alcanza_informes(db, company):
        raise HTTPException(
            402,
            {"motivo": consumo.aviso_de_tope(company, "informes"),
             "codigo": "tope_del_plan"},
        )

    if not CFO_REPORT_BASE_URL.startswith("https://"):
        raise HTTPException(
            503,
            "CFO_REPORT_BASE_URL no está configurado con una URL https. "
            "Sin eso el enlace del informe no se puede abrir ni enviar.",
        )

    informe = cfo_reportes.armar(
        db, company, payload.metricas, desde, hasta,
        pedido_por=cfo.solo_digitos(""), titulo=payload.titulo,
    )
    token = cfo_reportes.emitir_token(
        db, informe, horas=payload.horas_de_vigencia,
        un_solo_uso=payload.un_solo_uso,
    )
    audit(
        db, "cfo.informe.crear", user_id=identity.user_id, company_id=company_id,
        detail={"informe": informe.id, "metricas": payload.metricas,
                "un_solo_uso": payload.un_solo_uso},
    )
    return {
        "id": informe.id,
        "titulo": informe.titulo,
        # El enlace completo, una sola vez. Después queda el hash y no hay
        # forma de recuperarlo: se emite uno nuevo.
        "enlace": f"{CFO_REPORT_BASE_URL}/r/{token}",
        "vence_en_horas": payload.horas_de_vigencia,
        "un_solo_uso": payload.un_solo_uso,
        "aviso": "Este enlace se muestra una sola vez y da acceso a los datos.",
    }


def _vigente(llave: FinanceReportToken) -> bool:
    """Un enlace vigente es el que todavía abriría el informe."""
    if llave.revocado_at is not None:
        return False
    if llave.expira_at <= datetime.now(timezone.utc).replace(tzinfo=None):
        return False
    return not (llave.un_solo_uso and llave.aperturas >= 1)


@router.get("/informes")
def listar_informes(
    company_id: int,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Qué informes existen y cuántas veces se abrieron. Sin los tokens."""
    _puede_administrar(db, company_id, identity)
    filas = (
        db.query(FinanceReport)
        .filter(FinanceReport.company_id == company_id)
        .order_by(FinanceReport.created_at.desc())
        .limit(100)
        .all()
    )
    salida = []
    for r in filas:
        llaves = (
            db.query(FinanceReportToken)
            .filter(
                FinanceReportToken.company_id == company_id,
                FinanceReportToken.report_id == r.id,
            )
            .all()
        )
        salida.append({
            "id": r.id,
            "titulo": r.titulo,
            "desde": r.desde.isoformat(),
            "hasta": r.hasta.isoformat(),
            "creado": r.created_at.isoformat(),
            # Un enlace de un solo uso ya gastado no está vigente, aunque no
            # esté revocado ni vencido. Decirle al dueño que le quedan enlaces
            # vivos cuando no le queda ninguno es peor que no decirle nada.
            "enlaces_vigentes": sum(1 for k in llaves if _vigente(k)),
            "aperturas": sum(k.aperturas for k in llaves),
            "ultima_apertura": max(
                (k.ultima_apertura_at.isoformat() for k in llaves if k.ultima_apertura_at),
                default=None,
            ),
        })
    return salida


@router.post("/informes/{informe_id}/revocar")
def revocar_informe(
    company_id: int,
    informe_id: int,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Mata todos los enlaces de ese informe. Para cuando llegó a quien no debía."""
    _puede_administrar(db, company_id, identity)
    informe = db.get(FinanceReport, informe_id)
    if not informe or informe.company_id != company_id:
        raise HTTPException(404, "Informe no encontrado")
    cuantos = cfo_reportes.revocar(db, company_id, informe_id)
    audit(
        db, "cfo.informe.revocar", user_id=identity.user_id, company_id=company_id,
        detail={"informe": informe_id, "enlaces": cuantos},
    )
    return {"revocados": cuantos}


# ─── Conectores ──────────────────────────────────────────────────────────


class ConectorIn(BaseModel):
    fuente: str = Field(min_length=2, max_length=30)
    tipo: str = Field(default="csv", max_length=20)
    nombre: str = Field(min_length=1, max_length=120)
    # Para rest/postgres. El csv no lleva nada de esto.
    config: dict = Field(default_factory=dict)
    # El token o la contraseña del sistema del cliente. Entra una vez, se
    # cifra y NO vuelve a salir por la API.
    credencial: str = Field(default="", max_length=2000)


class ConectorUpdate(BaseModel):
    activo: bool | None = None
    nombre: str | None = Field(default=None, min_length=1, max_length=120)


def _conector(db: Session, company_id: int, conector_id: int) -> FinanceConnector:
    fila = db.get(FinanceConnector, conector_id)
    if not fila or fila.company_id != company_id:
        raise HTTPException(404, "Conector no encontrado")
    return fila


@router.get("/conectores")
def listar_conectores(
    company_id: int,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    _puede_administrar(db, company_id, identity)
    _company(db, company_id)
    return [
        {**cfo_conectores.estado(db, c),
         "config": cfo_fuentes_externas.resumen_config(c)}
        for c in cfo_conectores.conectores(db, company_id, solo_activos=False)
    ]


@router.post("/conectores", status_code=201)
def crear_conector(
    company_id: int,
    payload: ConectorIn,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Declara de dónde van a venir los datos de una fuente.

    Nace SIN habilitar la fuente: recién cuando trae filas, el motor la
    considera disponible. Un conector vacío que habilitara el cálculo haría
    que el CFO conteste ₲ 0 con cara de certeza.
    """
    _puede_administrar(db, company_id, identity)
    _company(db, company_id)

    if payload.fuente not in cfo_csv.fuentes_validas():
        raise HTTPException(
            422,
            {
                "motivo": "Fuente desconocida. Válidas: "
                          + ", ".join(cfo_csv.fuentes_validas()) + ".",
                "codigo": "fuente_desconocida",
            },
        )
    if payload.tipo not in cfo_conectores.TIPOS:
        raise HTTPException(422, {"motivo": "Tipo de conector desconocido.",
                                  "codigo": "tipo_desconocido"})

    config_json = "{}"
    cifrada = ""
    if payload.tipo != "csv":
        # La configuración se valida ANTES de guardar nada. Un conector con
        # una URL que apunta a una red interna no se guarda "para arreglarlo
        # después": no se guarda.
        validador = cfo_fuentes_externas.VALIDADORES[payload.tipo]
        try:
            config_json = json.dumps(validador(payload.config))
        except cfo_fuentes_externas.FuenteInvalida as exc:
            raise HTTPException(422, {"motivo": str(exc),
                                      "codigo": "config_invalida"})
        if payload.credencial:
            try:
                cifrada = cfo_secretos.cifrar(payload.credencial)
            except cfo_secretos.SinLlave as exc:
                # Error de despliegue, no del usuario. Ruidoso al crear y no
                # silencioso al sincronizar: un servidor a medias no puede
                # terminar guardando credenciales en claro "por ahora".
                raise HTTPException(503, {"motivo": str(exc),
                                          "codigo": "sin_llave_de_cifrado"})

    fila = FinanceConnector(
        company_id=company_id, fuente=payload.fuente, tipo=payload.tipo,
        nombre=payload.nombre.strip(), config=config_json,
        secreto_cifrado=cifrada,
    )
    db.add(fila)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, {"motivo": "Ya hay un conector con ese nombre.",
                                  "codigo": "nombre_repetido"})
    db.refresh(fila)
    audit(db, "cfo.conector.alta", user_id=identity.user_id, company_id=company_id,
          detail={"conector": fila.id, "fuente": payload.fuente, "tipo": payload.tipo})
    # La MISMA forma que devuelve el listado: el panel usa esta respuesta para
    # pintar la fila recién creada, y con dos formas distintas le queda a
    # medias hasta que recarga.
    return {**cfo_conectores.estado(db, fila),
            "config": cfo_fuentes_externas.resumen_config(fila)}


@router.patch("/conectores/{conector_id}")
def editar_conector(
    company_id: int,
    conector_id: int,
    payload: ConectorUpdate,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    _puede_administrar(db, company_id, identity)
    fila = _conector(db, company_id, conector_id)
    datos = payload.model_dump(exclude_unset=True)
    for campo, valor in datos.items():
        setattr(fila, campo, valor)
    db.commit()
    db.refresh(fila)
    # Apagar un conector cambia qué puede contestar el CFO: queda escrito.
    if "activo" in datos:
        audit(db, "cfo.conector.cambio", user_id=identity.user_id,
              company_id=company_id,
              detail={"conector": conector_id, "activo": datos["activo"]})
    return {**cfo_conectores.estado(db, fila),
            "config": cfo_fuentes_externas.resumen_config(fila)}


@router.delete("/conectores/{conector_id}", status_code=204)
def borrar_conector(
    company_id: int,
    conector_id: int,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Borra el conector Y sus datos.

    Lo ya calculado no se mueve: los informes son snapshots. Es a propósito
    —el dueño mandó ese número a su contador— y por eso borrar acá no
    reescribe la historia.
    """
    _puede_administrar(db, company_id, identity)
    fila = _conector(db, company_id, conector_id)
    borradas = (
        db.query(FinanceRecord)
        .filter(FinanceRecord.company_id == company_id,
                FinanceRecord.connector_id == conector_id)
        .delete(synchronize_session=False)
    )
    db.delete(fila)
    db.commit()
    audit(db, "cfo.conector.baja", user_id=identity.user_id, company_id=company_id,
          detail={"conector": conector_id, "registros_borrados": borradas})
    return Response(status_code=204)


@router.post("/conectores/{conector_id}/cargar")
async def cargar_planilla(
    company_id: int,
    conector_id: int,
    archivo: UploadFile = File(...),
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Sube la exportación del sistema del cliente.

    Si alguna fila no se entiende no se carga NINGUNA, y se devuelven los
    renglones con problema. Cargar 98 de 100 da un total que se ve bien,
    cierra mal, y nadie sabe por qué.
    """
    _puede_administrar(db, company_id, identity)
    fila = _conector(db, company_id, conector_id)
    if fila.tipo != "csv":
        raise HTTPException(422, {"motivo": "Ese conector no es de planilla.",
                                  "codigo": "tipo_incorrecto"})

    datos = await archivo.read()
    try:
        resumen = cfo_csv.cargar(db, fila, datos)
    except cfo_csv.PlanillaInvalida as exc:
        cfo_conectores.anotar_sync(db, fila, 0, error=exc.motivo)
        raise HTTPException(
            422,
            {"motivo": exc.motivo, "renglones": exc.renglones,
             "codigo": "planilla_invalida"},
        )

    cfo_conectores.anotar_sync(db, fila, resumen["nuevas"])
    audit(db, "cfo.conector.carga", user_id=identity.user_id, company_id=company_id,
          detail={"conector": conector_id, **resumen})
    return {**resumen, "conector": cfo_conectores.estado(db, fila)}


@router.get("/fuentes")
def listar_fuentes(
    company_id: int,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Qué fuentes tiene esta empresa y de cuándo son sus datos.

    Es la vista honesta del producto: se ve de un vistazo qué puede contestar
    el CFO, en vez de descubrirlo cuando el dueño pregunta.
    """
    _puede_administrar(db, company_id, identity)
    _company(db, company_id)
    disponibles = cfo_conectores.fuentes_disponibles(db, company_id)
    salida = []
    for f in cfo_metricas.Fuente:
        corte = cfo_conectores.corte_de(db, company_id, f)
        salida.append({
            "fuente": f.value,
            "disponible": f in disponibles,
            "corte": corte.isoformat() if corte else None,
            "interna": f == cfo_metricas.Fuente.INTERNA,
        })
    return salida


# ─── Memoria ─────────────────────────────────────────────────────────────
#
# Existen porque el dueño tiene derecho a ver qué sabe de él este sistema y a
# borrarlo. Memoria financiera que no se puede mirar ni borrar es un pasivo:
# el día que cambia de contador, o echa a alguien, tiene que poder decir
# "olvidate de eso" y que se olvide de verdad.


class MemoriaIn(BaseModel):
    tipo: str = Field(pattern="^(preferencia|contexto|vocabulario)$")
    clave: str = Field(min_length=1, max_length=60)
    valor: str = Field(min_length=1, max_length=300)
    phone: str = Field(default="", max_length=30)


@router.get("/memoria")
def listar_memoria(
    company_id: int,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Todo lo recordado, incluso lo vencido: para poder auditarlo hay que
    verlo, y lo vencido explica por qué el bot dejó de saber algo."""
    _puede_administrar(db, company_id, identity)
    _company(db, company_id)
    filas = (
        db.query(FinanceMemory)
        .filter(FinanceMemory.company_id == company_id)
        .order_by(FinanceMemory.updated_at.desc())
        .all()
    )
    return [cfo_memoria.salida(f) for f in filas]


@router.post("/memoria", status_code=201)
def crear_memoria(
    company_id: int,
    payload: MemoriaIn,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Cargar contexto desde el panel, sin esperar a que salga en un chat."""
    _puede_administrar(db, company_id, identity)
    _company(db, company_id)
    try:
        fila = cfo_memoria.recordar(
            db, company_id, payload.tipo, payload.clave, payload.valor,
            phone=cfo.solo_digitos(payload.phone) if payload.phone else "",
            fuente="panel",
        )
    except cfo_memoria.MemoriaRechazada as exc:
        raise HTTPException(422, {"motivo": str(exc), "codigo": "memoria_rechazada"})
    audit(db, "cfo.memoria.alta", user_id=identity.user_id, company_id=company_id,
          detail={"clave": fila.clave, "tipo": fila.tipo})
    return cfo_memoria.salida(fila)


@router.delete("/memoria/{memoria_id}", status_code=204)
def borrar_memoria(
    company_id: int,
    memoria_id: int,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    _puede_administrar(db, company_id, identity)
    cuantas = cfo_memoria.olvidar(db, company_id, memoria_id=memoria_id)
    if not cuantas:
        raise HTTPException(404, "Esa memoria no existe")
    audit(db, "cfo.memoria.baja", user_id=identity.user_id, company_id=company_id,
          detail={"memoria": memoria_id})
    return Response(status_code=204)


@router.delete("/memoria", status_code=200)
def borrar_toda_la_memoria(
    company_id: int,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """El botón de "borrá todo lo que sabés de mí". Tiene que existir."""
    _puede_administrar(db, company_id, identity)
    _company(db, company_id)
    cuantas = cfo_memoria.olvidar_todo(db, company_id)
    audit(db, "cfo.memoria.baja_total", user_id=identity.user_id,
          company_id=company_id, detail={"borradas": cuantas})
    return {"borradas": cuantas}


@router.post("/conectores/{conector_id}/sincronizar")
async def sincronizar_conector(
    company_id: int,
    conector_id: int,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Sale a buscar los datos ahora. Para REST y PostgreSQL.

    El resultado queda anotado en el conector aunque falle: un conector que
    falla en silencio es peor que uno roto, porque el dueño sigue creyendo que
    sus números están al día.
    """
    _puede_administrar(db, company_id, identity)
    fila = _conector(db, company_id, conector_id)
    if fila.tipo == "csv":
        raise HTTPException(422, {"motivo": "Un conector de planilla se carga "
                                            "subiendo el archivo.",
                                  "codigo": "tipo_incorrecto"})
    try:
        resumen = await cfo_fuentes_externas.sincronizar(db, fila)
    except (cfo_fuentes_externas.FalloDeSincronizacion,
            cfo_fuentes_externas.FuenteInvalida,
            cfo_secretos.SinLlave) as exc:
        cfo_conectores.anotar_sync(db, fila, 0, error=str(exc))
        raise HTTPException(422, {"motivo": str(exc),
                                  "codigo": "sincronizacion_fallida"})

    cfo_conectores.anotar_sync(db, fila, resumen["nuevas"])
    audit(db, "cfo.conector.sync", user_id=identity.user_id, company_id=company_id,
          detail={"conector": conector_id, **resumen})
    return {**resumen, "conector": cfo_conectores.estado(db, fila)}
