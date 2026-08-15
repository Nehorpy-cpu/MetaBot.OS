"""Planillas de honorarios: separar por aseguradora para poder cobrar.

En Paraguay el profesional no cobra atención por atención. Junta las del
período, las separa POR ASEGURADORA —cada una tiene su formato y su
circuito—, firma cada planilla y la entrega. Recién después cobra.

Tres reglas que este módulo sostiene:

1. **La planilla es un documento, no una consulta.** Los montos se congelan
   al armarla. Si mañana sube el precio de la ecografía o el convenio baja
   del 80% al 70%, lo firmado no se mueve.
2. **Una atención se cobra una sola vez.** Lo garantiza la base
   (`uq_fee_item_atencion`), no este código: rearmar una planilla o
   superponer dos períodos tiene que fallar, no facturar dos veces.
3. **Solo se liquida lo atendido.** Un turno confirmado al que el paciente
   no vino no es plata. Y lo que quedó sin marcar se INFORMA, porque si no
   el profesional cobra de menos y nadie se entera.
"""
from datetime import date, datetime, time

from sqlalchemy.orm import Session

from . import aranceles
from .models import (
    Appointment, Company, Doctor, FeeBatch, FeeBatchItem, Insurer, Service,
)
from .textos import formato_gs

# El único estado que significa "el profesional atendió a esta persona".
# `confirmed` es que el paciente dijo que venía, no que vino.
ESTADO_LIQUIDABLE = "attended"

PARTICULARES = "Particulares"

ESTADOS = ("borrador", "firmada", "entregada", "cobrada")


def _rango(desde: date, hasta: date) -> tuple[datetime, datetime]:
    """El período completo, incluyendo todo el último día.

    Con `<= hasta` a secas, una atención del día 31 a las 15:00 queda afuera
    porque se compara contra las 00:00 de ese día: el profesional pierde una
    jornada entera de cada planilla.
    """
    return datetime.combine(desde, time.min), datetime.combine(hasta, time.max)


def _atenciones(db: Session, company_id: int, doctor_id: int,
                desde: date, hasta: date) -> list[Appointment]:
    inicio, fin = _rango(desde, hasta)
    return (
        db.query(Appointment)
        .filter(
            Appointment.company_id == company_id,
            Appointment.doctor_id == doctor_id,
            Appointment.scheduled_at >= inicio,
            Appointment.scheduled_at <= fin,
        )
        .order_by(Appointment.scheduled_at)
        .all()
    )


def _ya_liquidadas(db: Session, company_id: int, ids: list[int]) -> set[int]:
    if not ids:
        return set()
    return {
        fila.appointment_id
        for fila in db.query(FeeBatchItem.appointment_id)
        .filter(
            FeeBatchItem.company_id == company_id,
            FeeBatchItem.appointment_id.in_(ids),
        )
        .all()
    }


def _calcular_item(db: Session, company_id: int, cita: Appointment,
                   servicios: dict[int, Service], convenios: dict[int, Insurer],
                   honorario_pct: int) -> dict:
    """Los montos de UNA atención, con la misma aritmética que usa el bot."""
    service = servicios.get(cita.service_id) if cita.service_id else None
    insurer = convenios.get(cita.insurer_id) if cita.insurer_id else None

    cobertura = (
        aranceles.cobertura_de(db, company_id, insurer, service)
        if insurer is not None else None
    )
    # Un estudio EXCLUIDO del convenio se abona particular: la aseguradora no
    # pone nada y el paciente paga todo en caja. Que la atención tenga
    # `insurer_id` solo dice por qué convenio vino la persona, no quién pagó.
    #
    # Tratándolo como cobertura del seguro, el profesional cobraba CERO por
    # una resonancia de 850.000 que el paciente ya había pagado, y el renglón
    # se le entregaba a la aseguradora que justamente no la cubre. No fallaba
    # nada: la planilla salía prolija, en cero, y se firmaba.
    excluido = bool(cobertura and cobertura.excluido)

    if insurer is not None and not excluido:
        montos = aranceles.repartir(service.price_gs if service else 0, cobertura)
        # Lo que el profesional le factura a la aseguradora es lo que la
        # aseguradora cubre. El copago lo cobra la clínica en caja: por eso
        # va aparte y no sumado acá.
        facturado = montos.paga_el_seguro_gs
        origen = cobertura.origen
    else:
        # Particular, o excluido —que económicamente es lo mismo—.
        montos = aranceles.repartir(service.price_gs if service else 0, None)
        facturado = montos.paga_el_paciente_gs
        origen = "excluido del convenio: se abona particular" if excluido else "particular"

    return {
        "appointment_id": cita.id,
        # En qué planilla cae. No es `cita.insurer_id`: un excluido va con los
        # particulares, que es de donde salió la plata.
        "grupo": None if excluido else cita.insurer_id,
        "atendido_at": cita.scheduled_at,
        "paciente": cita.patient_name,
        "servicio": service.name if service else "",
        "precio_lista_gs": montos.precio_lista_gs,
        "paga_el_paciente_gs": montos.paga_el_paciente_gs,
        "facturado_gs": facturado,
        "honorario_gs": aranceles.honorario_gs(facturado, honorario_pct),
        "origen_arancel": origen,
        # Sin servicio cargado no hay precio, y sin precio no hay honorario.
        # Se muestra en cero y se avisa, en vez de desaparecer del listado.
        "sin_arancel": service is None,
    }


def preview(db: Session, company: Company, doctor: Doctor,
            desde: date, hasta: date) -> dict:
    """Qué se va a liquidar, separado por aseguradora, sin guardar nada.

    Devuelve también lo que NO entra y por qué. Una planilla que simplemente
    omite en silencio los turnos sin marcar hace que el profesional cobre de
    menos creyendo que cobró todo.
    """
    citas = _atenciones(db, company.id, doctor.id, desde, hasta)
    liquidadas = _ya_liquidadas(db, company.id, [c.id for c in citas])

    atendidas = [c for c in citas if c.status == ESTADO_LIQUIDABLE]
    sin_marcar = [
        c for c in citas
        if c.status in ("pending", "confirmed")
    ]
    nuevas = [c for c in atendidas if c.id not in liquidadas]
    repetidas = [c for c in atendidas if c.id in liquidadas]

    servicios = {
        s.id: s for s in db.query(Service).filter(Service.company_id == company.id).all()
    }
    convenios = {
        i.id: i for i in db.query(Insurer).filter(Insurer.company_id == company.id).all()
    }

    grupos: dict[int | None, dict] = {}
    for cita in nuevas:
        item = _calcular_item(
            db, company.id, cita, servicios, convenios, doctor.honorario_pct
        )
        clave = item["grupo"]
        grupo = grupos.setdefault(clave, {
            "insurer_id": clave,
            "aseguradora": (
                f"{convenios[clave].name} {convenios[clave].plan}".strip()
                if clave in convenios else PARTICULARES
            ),
            "items": [],
            "total_facturado_gs": 0,
            "total_honorario_gs": 0,
        })
        grupo["items"].append(item)
        grupo["total_facturado_gs"] += item["facturado_gs"]
        grupo["total_honorario_gs"] += item["honorario_gs"]

    ordenados = sorted(
        grupos.values(),
        # Particulares al final: primero lo que hay que ir a cobrar afuera.
        key=lambda g: (g["insurer_id"] is None, g["aseguradora"]),
    )
    return {
        "doctor": doctor.name,
        "doctor_id": doctor.id,
        "honorario_pct": doctor.honorario_pct,
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "grupos": ordenados,
        "total_facturado_gs": sum(g["total_facturado_gs"] for g in ordenados),
        "total_honorario_gs": sum(g["total_honorario_gs"] for g in ordenados),
        "atenciones": len(nuevas),
        # Lo que queda afuera, dicho en voz alta.
        "sin_marcar_como_atendido": len(sin_marcar),
        "ya_liquidadas": len(repetidas),
        "sin_arancel": sum(
            1 for g in ordenados for i in g["items"] if i["sin_arancel"]
        ),
    }


def crear(db: Session, company: Company, doctor: Doctor, desde: date, hasta: date,
          user_id: int | None = None) -> list[FeeBatch]:
    """Arma las planillas del período: una por aseguradora.

    No hace commit: quien llama decide la transacción. Si la base rechaza un
    ítem por `uq_fee_item_atencion` —una atención que ya estaba en otra
    planilla— tiene que fallar TODO el armado, no quedar a medias.
    """
    datos = preview(db, company, doctor, desde, hasta)
    creadas: list[FeeBatch] = []
    for grupo in datos["grupos"]:
        planilla = FeeBatch(
            company_id=company.id,
            doctor_id=doctor.id,
            insurer_id=grupo["insurer_id"],
            insurer_nombre=grupo["aseguradora"],
            desde=desde,
            hasta=hasta,
            estado="borrador",
            honorario_pct=doctor.honorario_pct,
            total_facturado_gs=grupo["total_facturado_gs"],
            total_honorario_gs=grupo["total_honorario_gs"],
        )
        db.add(planilla)
        db.flush()
        for item in grupo["items"]:
            db.add(FeeBatchItem(
                company_id=company.id,
                batch_id=planilla.id,
                appointment_id=item["appointment_id"],
                atendido_at=item["atendido_at"],
                paciente=item["paciente"],
                servicio=item["servicio"],
                precio_lista_gs=item["precio_lista_gs"],
                facturado_gs=item["facturado_gs"],
                honorario_gs=item["honorario_gs"],
                origen_arancel=item["origen_arancel"],
            ))
        creadas.append(planilla)
    return creadas


def texto(company: Company, doctor: Doctor, planilla: FeeBatch,
          items: list[FeeBatchItem]) -> str:
    """La planilla lista para imprimir y firmar de puño.

    Se arma con los datos guardados, sin pasar por ningún modelo: un papel
    que se firma no puede tener una línea que la redactó un LLM.
    """
    ancho = 64
    lineas = [
        company.name.upper().center(ancho),
        "PLANILLA DE HONORARIOS PROFESIONALES".center(ancho),
        "=" * ancho,
        f"Profesional : {doctor.name}",
    ]
    if doctor.specialty:
        lineas.append(f"Especialidad: {doctor.specialty}")
    lineas += [
        f"Aseguradora : {planilla.insurer_nombre}",
        f"Período     : {planilla.desde.strftime('%d/%m/%Y')} al "
        f"{planilla.hasta.strftime('%d/%m/%Y')}",
        f"Atenciones  : {len(items)}",
        "-" * ancho,
    ]
    ajustados = 0
    for i in items:
        lineas.append(
            f"{i.atendido_at.strftime('%d/%m')} {i.paciente[:26]:26} "
            f"{formato_gs(i.honorario_gs):>14}"
        )
        if i.servicio:
            lineas.append(f"       {i.servicio[:52]}")
        if i.ajustado_a_mano:
            # Va en el papel que se firma: quien firma tiene que ver que ese
            # renglón no salió del cálculo, y cuánto decía antes.
            ajustados += 1
            detalle = f"       (*) ajustado a mano, calculado {formato_gs(i.facturado_calculado_gs)}"
            if i.ajuste_motivo:
                detalle += f" — {i.ajuste_motivo[:40]}"
            lineas.append(detalle)
    lineas += [
        "-" * ancho,
        f"{'Facturado a la aseguradora:':>44} {formato_gs(planilla.total_facturado_gs):>18}",
        f"{f'Honorario del profesional ({planilla.honorario_pct}%):':>44} "
        f"{formato_gs(planilla.total_honorario_gs):>18}",
    ]
    if ajustados:
        lineas.append(
            f"(*) {ajustados} renglón(es) con el monto ajustado a mano."
        )
    lineas += [
        "",
        "",
        " " * 16 + "_" * 32,
        " " * 16 + f"{doctor.name}",
        " " * 16 + "Firma y aclaración",
    ]
    return "\n".join(lineas)
