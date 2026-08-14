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
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import honorarios, previsita
from ..auth import Identity, audit, get_identity, hash_password
from ..db import get_db
from ..models import (
    Appointment, Company, Doctor, FeeBatch, FeeBatchItem, Membership, Prescription,
    PrescriptionItem, User,
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


def _puede_dar_accesos(db: Session, company_id: int, identity: Identity) -> None:
    """Administrar los logins de los profesionales es de la empresa.

    En UNA función y usada por el alta Y por el listado: tenerlo escrito dos
    veces es cómo se llega a que uno lo chequee y el otro no.
    """
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
        raise HTTPException(403, "Solo el dueño de la empresa administra los accesos")


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
    _puede_dar_accesos(db, company_id, identity)

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
    """Qué profesionales tienen login. Sin claves ni hashes, obviamente.

    Exige el mismo permiso que crearlos. Sin este chequeo, cualquier médico
    —que el middleware deja entrar a todo lo que empiece con /portal— se
    llevaba el padrón interno de cuentas de la clínica: nombre y correo de
    cada colega. El POST sí lo pedía; el GET quedó abierto, que es el modo
    de falla clásico de mirar solo la escritura.
    """
    _puede_dar_accesos(db, company_id, identity)
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


# ─── Honorarios: preparar, firmar, entregar, cobrar ──────────────────────
#
# El circuito real de un profesional en Paraguay: junta las atenciones del
# período, las separa POR ASEGURADORA, firma cada planilla y la entrega.
# Recién después cobra. El sistema no "paga" nada: prepara el papel que se
# firma y deja registrado en qué punto del circuito está cada planilla.


def _planilla(db: Session, company_id: int, batch_id: int, doctor: Doctor) -> FeeBatch:
    """La planilla, si es de este profesional y de esta empresa."""
    planilla = db.get(FeeBatch, batch_id)
    if not planilla or planilla.company_id != company_id or planilla.doctor_id != doctor.id:
        raise HTTPException(404, "Planilla no encontrada")
    return planilla


def _items(db: Session, company_id: int, batch_id: int) -> list[FeeBatchItem]:
    return (
        db.query(FeeBatchItem)
        .filter(
            FeeBatchItem.company_id == company_id,
            FeeBatchItem.batch_id == batch_id,
        )
        .order_by(FeeBatchItem.atendido_at)
        .all()
    )


def _salida(planilla: FeeBatch, items: list[FeeBatchItem] | None = None) -> dict:
    datos = {
        "id": planilla.id,
        "aseguradora": planilla.insurer_nombre,
        "insurer_id": planilla.insurer_id,
        "desde": planilla.desde.isoformat(),
        "hasta": planilla.hasta.isoformat(),
        "estado": planilla.estado,
        "atenciones": len(items) if items is not None else None,
        "total_facturado_gs": planilla.total_facturado_gs,
        "total_honorario_gs": planilla.total_honorario_gs,
        "honorario_pct": planilla.honorario_pct,
        "firmada_at": planilla.firmada_at.isoformat() if planilla.firmada_at else None,
        "entregada_at": planilla.entregada_at.isoformat() if planilla.entregada_at else None,
        "cobrada_at": planilla.cobrada_at.isoformat() if planilla.cobrada_at else None,
        "notas": planilla.notas,
    }
    if items is not None:
        datos["items"] = [
            {
                "fecha": i.atendido_at.isoformat(),
                "paciente": i.paciente,
                "servicio": i.servicio,
                "precio_lista_gs": i.precio_lista_gs,
                "facturado_gs": i.facturado_gs,
                "honorario_gs": i.honorario_gs,
                "origen_arancel": i.origen_arancel,
            }
            for i in items
        ]
    return datos


def _periodo(desde: str, hasta: str) -> tuple[date, date]:
    try:
        d, h = date.fromisoformat(desde), date.fromisoformat(hasta)
    except ValueError:
        raise HTTPException(422, "Fechas inválidas: se esperan AAAA-MM-DD")
    if d > h:
        raise HTTPException(422, "El período empieza después de terminar")
    if (h - d).days > 366:
        # Un período de años no es una liquidación: es un error de tipeo que
        # arma una planilla imposible de revisar a mano.
        raise HTTPException(422, "El período no puede pasar de un año")
    return d, h


@router.get("/honorarios/preview")
def preview_honorarios(
    company_id: int,
    desde: str,
    hasta: str,
    doctor_id: int | None = None,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Qué se liquidaría en ese período, sin guardar nada.

    Incluye lo que NO entra y por qué. Una planilla que omite en silencio los
    turnos sin marcar hace que el profesional cobre de menos y lo firme.
    """
    doctor = _doctor_pedido(db, company_id, identity, doctor_id)
    d, h = _periodo(desde, hasta)
    return honorarios.preview(db, _company(db, company_id), doctor, d, h)


@router.post("/honorarios", status_code=201)
def armar_honorarios(
    company_id: int,
    desde: str,
    hasta: str,
    doctor_id: int | None = None,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Arma las planillas del período: una por aseguradora.

    Si alguna atención ya estaba en otra planilla, la base lo rechaza y NO se
    guarda nada: media liquidación es peor que ninguna.
    """
    company = _company(db, company_id)
    doctor = _doctor_pedido(db, company_id, identity, doctor_id)
    d, h = _periodo(desde, hasta)
    # `crear` va DENTRO del try: hace un flush por cada aseguradora, así que
    # con dos o más el choque contra `uq_fee_item_atencion` se levanta ahí
    # adentro y no en el commit. Envolviendo solo el commit, este except era
    # código muerto para toda planilla de más de un grupo, y dos clics en
    # "Armar" devolvían un 500 sin explicación en vez del 409 que dice qué
    # pasó.
    try:
        creadas = honorarios.crear(db, company, doctor, d, h, identity.user_id)
        if not creadas:
            db.rollback()
            raise HTTPException(
                409,
                {
                    "motivo": "No hay atenciones para liquidar en ese período.",
                    "codigo": "sin_atenciones",
                },
            )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409,
            {
                "motivo": (
                    "Alguna de esas atenciones ya está en otra planilla. "
                    "Revisá el período: una atención se cobra una sola vez."
                ),
                "codigo": "atencion_ya_liquidada",
            },
        )
    audit(
        db, "honorarios.armar", user_id=identity.user_id, company_id=company_id,
        detail={
            "doctor_id": doctor.id,
            "periodo": f"{d}..{h}",
            "planillas": [p.id for p in creadas],
            "total_honorario_gs": sum(p.total_honorario_gs for p in creadas),
        },
    )
    return [_salida(p, _items(db, company_id, p.id)) for p in creadas]


@router.get("/honorarios")
def listar_honorarios(
    company_id: int,
    estado: str = "",
    doctor_id: int | None = None,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    doctor = _doctor_pedido(db, company_id, identity, doctor_id)
    q = (
        db.query(FeeBatch)
        .filter(FeeBatch.company_id == company_id, FeeBatch.doctor_id == doctor.id)
    )
    if estado:
        q = q.filter(FeeBatch.estado == estado)
    return [_salida(p) for p in q.order_by(FeeBatch.desde.desc(), FeeBatch.id.desc()).all()]


@router.get("/honorarios/{batch_id}")
def ver_honorarios(
    company_id: int,
    batch_id: int,
    doctor_id: int | None = None,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    doctor = _doctor_pedido(db, company_id, identity, doctor_id)
    planilla = _planilla(db, company_id, batch_id, doctor)
    items = _items(db, company_id, batch_id)
    datos = _salida(planilla, items)
    # El papel que se imprime y se firma de puño. Se arma con lo guardado, sin
    # pasar por ningún modelo: una línea redactada por un LLM no puede entrar
    # en algo que alguien firma.
    datos["texto"] = honorarios.texto(
        _company(db, company_id), doctor, planilla, items
    )
    return datos


@router.delete("/honorarios/{batch_id}", status_code=204)
def borrar_honorarios(
    company_id: int,
    batch_id: int,
    doctor_id: int | None = None,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Descarta un borrador para rearmarlo. Lo firmado no se borra."""
    doctor = _doctor_pedido(db, company_id, identity, doctor_id)
    planilla = _planilla(db, company_id, batch_id, doctor)
    if planilla.estado != "borrador":
        raise HTTPException(
            409,
            {
                "motivo": (
                    f"Esta planilla ya está {planilla.estado}: es un documento, "
                    "no se borra."
                ),
                "codigo": "planilla_cerrada",
            },
        )
    # Los ítems se van con ella (ondelete CASCADE) y las atenciones quedan
    # libres para entrar en la planilla que se arme después.
    db.delete(planilla)
    db.commit()
    audit(db, "honorarios.borrar", user_id=identity.user_id, company_id=company_id,
          detail={"planilla": batch_id})
    return Response(status_code=204)


class AvancePlanilla(BaseModel):
    notas: str = Field(default="", max_length=500)


# El circuito es una escalera de un solo sentido: cada paso exige el anterior.
# Sin esto, "entregada" podría preceder a "firmada" y la planilla que llega a
# la aseguradora no tendría firma.
_ANTERIOR = {"firmada": "borrador", "entregada": "firmada", "cobrada": "entregada"}
_SELLO = {"firmada": "firmada_at", "entregada": "entregada_at", "cobrada": "cobrada_at"}


def _avanzar(db: Session, planilla: FeeBatch, a: str, user_id: int | None,
             notas: str = "") -> dict:
    if planilla.estado != _ANTERIOR[a]:
        raise HTTPException(
            409,
            {
                "motivo": (
                    f"Para marcarla {a} tiene que estar {_ANTERIOR[a]}, "
                    f"y está {planilla.estado}."
                ),
                "codigo": "estado_invalido",
                "estado_actual": planilla.estado,
            },
        )
    planilla.estado = a
    setattr(planilla, _SELLO[a], datetime.now(timezone.utc).replace(tzinfo=None))
    if a == "firmada":
        planilla.firmada_por = user_id
    if notas:
        planilla.notas = notas[:500]
    db.commit()
    db.refresh(planilla)
    return _salida(planilla)


@router.post("/honorarios/{batch_id}/firmar")
def firmar(
    company_id: int,
    batch_id: int,
    payload: AvancePlanilla | None = None,
    doctor_id: int | None = None,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """El profesional da por buena la planilla y la congela.

    Esto NO es una firma digital y no se le llama así en ninguna parte de la
    interfaz: no hay certificado ni valor legal. Es una constancia de que el
    profesional revisó y aceptó los montos. La firma de puño va en el papel
    que se imprime desde acá.
    """
    doctor = _doctor_pedido(db, company_id, identity, doctor_id)
    planilla = _planilla(db, company_id, batch_id, doctor)
    salida = _avanzar(db, planilla, "firmada", identity.user_id,
                      payload.notas if payload else "")
    audit(db, "honorarios.firmar", user_id=identity.user_id, company_id=company_id,
          detail={"planilla": batch_id, "total_gs": planilla.total_honorario_gs})
    return salida


@router.post("/honorarios/{batch_id}/entregar")
def entregar(
    company_id: int,
    batch_id: int,
    payload: AvancePlanilla | None = None,
    doctor_id: int | None = None,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Se entregó a la aseguradora (o a administración)."""
    doctor = _doctor_pedido(db, company_id, identity, doctor_id)
    planilla = _planilla(db, company_id, batch_id, doctor)
    return _avanzar(db, planilla, "entregada", identity.user_id,
                    payload.notas if payload else "")


# ─── El otro lado del mostrador: la clínica ──────────────────────────────
#
# Marcar una planilla como cobrada NO puede hacerlo el profesional: sería
# firmar que le pagaron a sí mismo. Lo hace quien administra la empresa.


def _puede_administrar(db: Session, company_id: int, identity: Identity) -> None:
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
    if not miembro or not role_has(miembro.role, Perm.OPERATE):
        raise HTTPException(403, "Solo la administración de la empresa hace esto")


@router.get("/honorarios-a-pagar")
def honorarios_a_pagar(
    company_id: int,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Lo que la clínica le debe a sus profesionales, entregado y sin cobrar.

    Es la vista de administración: todas las planillas de todos los
    profesionales, no las de uno. Por eso no pasa por `_doctor_pedido`.
    """
    _puede_administrar(db, company_id, identity)
    filas = (
        db.query(FeeBatch, Doctor)
        .join(Doctor, Doctor.id == FeeBatch.doctor_id)
        .filter(
            FeeBatch.company_id == company_id,
            FeeBatch.estado.in_(("firmada", "entregada")),
        )
        .order_by(FeeBatch.hasta.desc())
        .all()
    )
    return [{**_salida(p), "doctor": d.name, "doctor_id": d.id} for p, d in filas]


@router.post("/honorarios/{batch_id}/pagar")
def pagar(
    company_id: int,
    batch_id: int,
    payload: AvancePlanilla | None = None,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """La clínica registra que le pagó al profesional."""
    _puede_administrar(db, company_id, identity)
    planilla = db.get(FeeBatch, batch_id)
    if not planilla or planilla.company_id != company_id:
        raise HTTPException(404, "Planilla no encontrada")
    salida = _avanzar(db, planilla, "cobrada", identity.user_id,
                      payload.notas if payload else "")
    audit(db, "honorarios.pagar", user_id=identity.user_id, company_id=company_id,
          detail={"planilla": batch_id, "doctor_id": planilla.doctor_id,
                  "total_gs": planilla.total_honorario_gs})
    return salida
