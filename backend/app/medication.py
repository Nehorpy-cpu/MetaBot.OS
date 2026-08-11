"""Recordatorios de toma de medicación.

Una revisión adversarial (médico auditor + abogado de datos + operador de
canal) devolvió doce bloqueantes sobre la primera versión de esto. Los seis
que había que resolver antes de mandarle un solo mensaje a un paciente real
están resueltos acá, y cada uno está marcado con SU número:

  P1 camino de salida — el bridge ya tiene endpoint de envío; antes no
     existía forma de que el servidor mandara nada por QR.
  P2 identidad del paciente — no se manda a un teléfono tipeado a mano: el
     número tiene que haber escrito a la clínica. Un dígito mal no le manda
     la receta de nadie a un desconocido.
  P3 baja — "STOP" corta todo, y lo respeta el envío, no solo la intención.
  P4 horario silencioso — nada entre las 22:00 y las 07:00.
  P5 receta editada — las tomas llevan la versión de la receta; si cambia,
     las viejas se descartan solas.
  P6 dosis perdida — una toma que agota reintentos deja rastro visible en
     vez de dejar de avisar para siempre en silencio.

Y una regla que no es negociable: el texto sale de campos de la base. El bot
relata lo que el doctor cargó; no receta, no interpreta y no parafrasea.
"""
import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from . import jobs
from .config import TIMEZONE
from .models import (
    Conversation,
    Doctor,
    Prescription,
    PrescriptionItem,
)

logger = logging.getLogger("metabot.medication")

DOSE_KIND = "medication_dose"
# P4: franja en la que no se molesta a nadie. Una toma que cae acá se corre
# al inicio de la mañana; el paciente prefiere el aviso tarde a las 3 AM.
SILENCIO_DESDE = time(22, 0)
SILENCIO_HASTA = time(7, 0)
# Tope duro de avisos por medicamento. "Cada 4 horas por 30 días" son 180
# mensajes: eso no es un recordatorio, es hostigamiento.
MAX_TOMAS_POR_ITEM = 60


def _ahora_local() -> datetime:
    return datetime.now(ZoneInfo(TIMEZONE)).replace(tzinfo=None)


def _local_a_utc(local: datetime) -> datetime:
    return local.replace(tzinfo=ZoneInfo(TIMEZONE)).astimezone(timezone.utc).replace(tzinfo=None)


def en_silencio(momento_local: datetime) -> bool:
    """P4: ¿cae en la franja en la que no se manda nada?"""
    h = momento_local.time()
    return h >= SILENCIO_DESDE or h < SILENCIO_HASTA


def correr_fuera_del_silencio(momento_local: datetime) -> datetime:
    """Mueve una toma nocturna al comienzo de la mañana siguiente."""
    if not en_silencio(momento_local):
        return momento_local
    if momento_local.time() >= SILENCIO_DESDE:
        momento_local += timedelta(days=1)
    return momento_local.replace(
        hour=SILENCIO_HASTA.hour, minute=SILENCIO_HASTA.minute, second=0, microsecond=0
    )


def paciente_verificado(db: Session, company_id: int, telefono: str) -> Conversation | None:
    """P2: el número tiene que haber escrito a la clínica.

    Es la verificación más honesta que se puede hacer sin un flujo de código
    por SMS: ese número existe, es de alguien que se comunicó con este
    negocio, y podemos leer si pidió la baja. Un teléfono cargado a mano y
    nunca contactado NO califica: un dígito equivocado mandaría datos de
    salud a un desconocido.
    """
    return (
        db.query(Conversation)
        .filter(
            Conversation.company_id == company_id,
            Conversation.contact_phone == telefono,
        )
        .order_by(Conversation.id.desc())
        .first()
    )


def dedup_dosis(item_id: int, version: int, n: int) -> str:
    return f"{DOSE_KIND}:{item_id}:v{version}:{n}"


def programar(db: Session, receta: Prescription) -> dict:
    """Programa las tomas de una receta. Devuelve por qué no, si no puede."""
    if not receta.reminders_enabled:
        return {"programadas": 0, "motivo": "el paciente no pidió recordatorios"}
    if receta.status != "active":
        return {"programadas": 0, "motivo": f"la receta está {receta.status}"}

    conv = paciente_verificado(db, receta.company_id, receta.patient_phone)
    if not conv:
        # P2: no se manda a un número que nunca escribió.
        return {
            "programadas": 0,
            "motivo": (
                "el número no escribió nunca a la clínica: no se puede verificar "
                "que sea del paciente. Pedile que mande un mensaje al WhatsApp "
                "del centro y volvé a activar los recordatorios."
            ),
        }
    if conv.opted_out:
        return {"programadas": 0, "motivo": "el paciente pidió la baja de los avisos"}

    items = (
        db.query(PrescriptionItem)
        .filter(PrescriptionItem.prescription_id == receta.id)
        .order_by(PrescriptionItem.id)
        .all()
    )
    ahora = _ahora_local()
    total = omitidas_a_demanda = 0
    for item in items:
        if item.every_hours <= 0 or item.duration_days <= 0:
            # Pauta a demanda ("si tenés dolor"): convertirla en horario fijo
            # sería inventar una indicación que el doctor no dio.
            omitidas_a_demanda += 1
            continue
        tomas = min((item.duration_days * 24) // item.every_hours, MAX_TOMAS_POR_ITEM)
        momento = ahora + timedelta(hours=item.every_hours)
        for n in range(tomas):
            cuando = correr_fuera_del_silencio(momento)
            jobs.enqueue(
                db,
                company_id=receta.company_id,
                kind=DOSE_KIND,
                run_at=_local_a_utc(cuando),
                payload={
                    "prescription_id": receta.id,
                    "item_id": item.id,
                    "version": receta.version,
                    "n": n + 1,
                    "de": tomas,
                },
                # P5: la versión va en la clave. Si la receta se edita, las
                # tomas viejas ya no coinciden con la versión vigente.
                dedup_key=dedup_dosis(item.id, receta.version, n + 1),
                max_attempts=2,
            )
            total += 1
            momento += timedelta(hours=item.every_hours)
    return {
        "programadas": total,
        "a_demanda_omitidas": omitidas_a_demanda,
        "motivo": "" if total else "ningún medicamento tiene pauta horaria fija",
    }


def cancelar(db: Session, receta: Prescription) -> int:
    """P5: da de baja TODAS las tomas pendientes de esta receta.

    Se llama al cancelar el tratamiento y al editarlo. Sin esto, el paciente
    recibiría la dosis nueva en los horarios viejos.
    """
    items = db.query(PrescriptionItem).filter(
        PrescriptionItem.prescription_id == receta.id
    ).all()
    canceladas = 0
    for item in items:
        # Se barren todas las versiones, no solo la vigente: al editar, lo que
        # hay que apagar es justamente lo de la versión anterior.
        for v in range(1, receta.version + 1):
            for n in range(1, MAX_TOMAS_POR_ITEM + 1):
                if jobs.cancel(db, dedup_dosis(item.id, v, n)):
                    canceladas += 1
    return canceladas


def texto_dosis(receta: Prescription, item: PrescriptionItem, doctor, n: int, de: int) -> str:
    """Armado desde la base. Ningún modelo escribe una dosis."""
    partes = [
        f"⏰ Recordatorio de tu tratamiento — toma {n} de {de}",
        "",
        f"*{item.medication}*",
        f"Dosis: {item.dose}" + (f" ({item.route})" if item.route else ""),
    ]
    if item.instructions:
        partes.append(item.instructions)
    if doctor:
        partes.append(f"\nIndicado por {doctor.name}.")
    partes.extend([
        "",
        "Si algo te cae mal o tenés dudas, escribinos y te contacta el "
        "consultorio: por acá no podemos cambiar una indicación médica.",
        "Para dejar de recibir estos avisos respondé *STOP*.",
    ])
    return "\n".join(partes)


@jobs.handler(DOSE_KIND)
async def _enviar_dosis(db: Session, company_id: int, payload: dict) -> None:
    from . import outbound  # import tardío: outbound importa modelos

    receta = db.get(Prescription, payload.get("prescription_id"))
    item = db.get(PrescriptionItem, payload.get("item_id"))
    if not receta or not item or receta.company_id != company_id:
        logger.info("dosis %s: la receta ya no existe", payload)
        return
    # P5: la receta cambió después de programar esta toma.
    if payload.get("version") != receta.version:
        logger.info("dosis de la versión %s descartada (vigente: %s)",
                    payload.get("version"), receta.version)
        return
    if receta.status != "active" or not receta.reminders_enabled:
        return

    # P3: la baja se respeta en el ENVÍO, no solo al programar.
    conv = paciente_verificado(db, company_id, receta.patient_phone)
    if not conv or conv.opted_out:
        logger.info("dosis no enviada: paciente dado de baja o sin conversación")
        return
    # P4: si el reintento la trajo hasta la madrugada, no se manda.
    if en_silencio(_ahora_local()):
        logger.info("dosis no enviada: está en franja de silencio")
        return

    doctor = db.get(Doctor, receta.doctor_id)
    texto = texto_dosis(receta, item, doctor, payload.get("n", 1), payload.get("de", 1))
    resultado = await outbound.enviar(db, company_id, receta.patient_phone, texto)
    if resultado.get("error"):
        # Lanza para que la cola reintente con backoff. Al agotar intentos, el
        # trabajo queda en 'failed' con el error: P6, deja rastro visible en
        # vez de dejar de avisar para siempre en silencio.
        raise RuntimeError(resultado["error"])
