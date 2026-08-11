"""Disponibilidad real: el único lugar donde se decide si un turno existe.

Antes, la única forma de saber si un doctor atendía un martes a las 10 era
que el MODELO interpretara el texto libre de `Doctor.schedule`. Medido en
producción el 11-ago-2026: un paciente podía quedar agendado un domingo a las
23:00 con un profesional que atiende lunes a viernes de mañana, y el sistema
le mandaba el recordatorio T-24h de una cita que no existía en la realidad.

Dos decisiones de fondo:

**Un doctor sin horario cargado SIGUE recibiendo turnos.** Hay clínicas
operando con el horario en texto libre y bloquearlas les rompe el negocio;
inventarles una franja sería peor. Lo que cambia es que la cita queda como
PEDIDO (`verificacion="sin_verificar"`) y el bot deja de prometer: dice "lo
dejo pedido, recepción te confirma" en vez de "tenés turno a las 10".

**El texto libre no se parsea nunca acá.** Ese string sirve para mostrar. Si
se lo interpretara con una regex para decidir disponibilidad sería la misma
regla violada con otro disfraz, solo que con más pasos.
"""
import logging
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from .models import (
    Appointment,
    Company,
    Doctor,
    DoctorAbsence,
    DoctorSchedule,
    DoctorService,
    Service,
)

logger = logging.getLogger("metabot.agenda")

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
# En castellano solo sábado y domingo hacen plural; el resto son invariables.
# "No atiende los domingo" suena a traducción automática, y estos textos los
# lee el paciente tal cual.
DIAS_PLURAL = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábados", "domingos"]

# Piso y techo de la duración de un turno. El piso NO es cosmético: con
# duración 0 la cita ocupa un intervalo vacío, no solapa con nada y se pueden
# apilar infinitas a la misma hora con la bendición del verificador.
DURACION_MINIMA = 5
DURACION_MAXIMA = 480  # 8 horas
DURACION_POR_DEFECTO = 30

# Cuánta anticipación mínima. Un turno para dentro de 10 minutos no le sirve
# a nadie y hace fallar el recordatorio.
MINUTOS_DE_ANTICIPACION = 60


def duracion_de(db: Session, company_id: int, service_id: int | None) -> int:
    """Cuánto ocupa el turno. Acotado a propósito: `Service.duration_min` lo
    edita la clínica desde el panel y un 0 ahí rompería el control de solapes."""
    if not service_id:
        return DURACION_POR_DEFECTO
    servicio = (
        db.query(Service)
        .filter(Service.company_id == company_id, Service.id == service_id)
        .first()
    )
    if not servicio:
        return DURACION_POR_DEFECTO
    return max(DURACION_MINIMA, min(int(servicio.duration_min or 0), DURACION_MAXIMA))


def _franjas(db: Session, company_id: int, doctor_id: int | None,
             weekday: int, service_id: int | None) -> list[DoctorSchedule]:
    """Franjas que aplican a ese día. Si el profesional tiene alguna franja
    específica para el servicio, SOLO valen esas: así se representa al que
    atiende consulta toda la semana pero hace ecografías los martes."""
    todas = (
        db.query(DoctorSchedule)
        .filter(
            DoctorSchedule.company_id == company_id,
            DoctorSchedule.doctor_id == doctor_id,
            DoctorSchedule.weekday == weekday,
        )
        .order_by(DoctorSchedule.hora_inicio)
        .all()
    )
    if service_id:
        propias = [f for f in todas if f.service_id == service_id]
        if propias:
            return propias
        # ¿Tiene franjas de ese servicio en OTRO día? Entonces solo ahí se hace.
        hay_en_otro_dia = (
            db.query(DoctorSchedule.id)
            .filter(
                DoctorSchedule.company_id == company_id,
                DoctorSchedule.doctor_id == doctor_id,
                DoctorSchedule.service_id == service_id,
            )
            .first()
        )
        if hay_en_otro_dia:
            return []
    return [f for f in todas if f.service_id is None]


def _ausencia(db: Session, company_id: int, doctor_id: int,
              dia: date) -> DoctorAbsence | None:
    return (
        db.query(DoctorAbsence)
        .filter(
            DoctorAbsence.company_id == company_id,
            DoctorAbsence.desde <= dia,
            DoctorAbsence.hasta >= dia,
            (DoctorAbsence.doctor_id == doctor_id) | (DoctorAbsence.doctor_id.is_(None)),
        )
        .first()
    )


def _hhmm(minutos: int) -> str:
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def _texto_franjas(franjas: list[DoctorSchedule]) -> str:
    por_dia: dict[int, list[str]] = {}
    for f in franjas:
        por_dia.setdefault(f.weekday, []).append(
            f"{_hhmm(f.hora_inicio)} a {_hhmm(f.hora_fin)}"
        )
    return "; ".join(
        f"{DIAS[d]} de {' y '.join(rangos)}" for d, rangos in sorted(por_dia.items())
    )


def _choca(db: Session, company_id: int, doctor_id: int, inicio: datetime,
           fin: datetime, ignorar_cita_id: int | None) -> Appointment | None:
    """Solape real por intervalos. La ventana de búsqueda usa la duración
    máxima permitida y no un número elegido a dedo: con una ventana corta, una
    cita larga que empezó mucho antes no aparecía y el solape pasaba."""
    q = (
        db.query(Appointment)
        .filter(
            Appointment.company_id == company_id,
            Appointment.doctor_id == doctor_id,
            Appointment.status.notin_(["cancelled"]),
            Appointment.scheduled_at > inicio - timedelta(minutes=DURACION_MAXIMA),
            Appointment.scheduled_at < fin,
        )
    )
    if ignorar_cita_id:
        q = q.filter(Appointment.id != ignorar_cita_id)
    for otra in q.all():
        otra_fin = otra.scheduled_at + timedelta(
            minutes=max(int(otra.duration_min or DURACION_POR_DEFECTO), DURACION_MINIMA)
        )
        if otra.scheduled_at < fin and inicio < otra_fin:
            return otra
    return None


def verificar_turno(
    db: Session,
    company: Company,
    doctor: Doctor,
    cuando: datetime,
    service_id: int | None = None,
    ignorar_cita_id: int | None = None,
    ahora: datetime | None = None,
) -> dict:
    """¿Se puede agendar? Devuelve un veredicto, nunca una excepción.

    El campo `motivo` va derecho al modelo y de ahí al paciente, así que está
    escrito para que se pueda leer tal cual.
    """
    ahora = ahora or datetime.now()
    duracion = duracion_de(db, company.id, service_id)
    fin = cuando + timedelta(minutes=duracion)

    if cuando < ahora + timedelta(minutes=MINUTOS_DE_ANTICIPACION):
        return {
            "ok": False, "codigo": "muy_pronto",
            "motivo": (
                f"Ese horario ya pasó o es demasiado pronto (hoy es "
                f"{DIAS[ahora.weekday()]} {ahora.strftime('%d/%m/%Y %H:%M')}). "
                "Ofrecele el próximo horario disponible."
            ),
        }

    ausencia = _ausencia(db, company.id, doctor.id, cuando.date())
    if ausencia:
        vuelve = ausencia.hasta + timedelta(days=1)
        quien = "La institución no atiende" if ausencia.doctor_id is None else f"{doctor.name} no atiende"
        return {
            "ok": False, "codigo": "ausencia",
            "motivo": (
                f"{quien} el {cuando.strftime('%d/%m/%Y')}"
                + (f" ({ausencia.motivo})" if ausencia.motivo else "")
                + f". Vuelve a atender desde el {vuelve.strftime('%d/%m/%Y')}. "
                "Ofrecele otra fecha."
            ),
        }

    # Servicio habilitado para ese profesional. Solo si la clínica cargó la
    # relación: si no cargó ninguna, no se bloquea a nadie.
    if service_id:
        tiene_alguno = (
            db.query(DoctorService.id)
            .filter(DoctorService.company_id == company.id,
                    DoctorService.doctor_id == doctor.id)
            .first()
        )
        if tiene_alguno:
            habilitado = (
                db.query(DoctorService.id)
                .filter(DoctorService.company_id == company.id,
                        DoctorService.doctor_id == doctor.id,
                        DoctorService.service_id == service_id)
                .first()
            )
            if not habilitado:
                servicio = db.get(Service, service_id)
                return {
                    "ok": False, "codigo": "servicio_no_habilitado",
                    "motivo": (
                        f"{doctor.name} no realiza "
                        f"{servicio.name if servicio else 'ese estudio'}. "
                        "Ofrecele otro profesional o preguntale si quiere una consulta."
                    ),
                }

    estructurado = doctor.agenda_mode == "estructurado"
    if estructurado:
        franjas = _franjas(db, company.id, doctor.id, cuando.weekday(), service_id)
        if not franjas:
            todas = (
                db.query(DoctorSchedule)
                .filter(DoctorSchedule.company_id == company.id,
                        DoctorSchedule.doctor_id == doctor.id)
                .order_by(DoctorSchedule.weekday, DoctorSchedule.hora_inicio)
                .all()
            )
            if not todas:
                # Marcado como estructurado pero sin franjas: falla CERRADO.
                # Volver en silencio a "se agenda cualquier cosa" sería peor.
                return {
                    "ok": False, "codigo": "sin_franjas_cargadas",
                    "motivo": (
                        f"{doctor.name} no tiene horarios cargados en el sistema. "
                        "Decile al paciente que lo consultás y escalá a un humano."
                    ),
                }
            return {
                "ok": False, "codigo": "sin_franjas_ese_dia",
                "motivo": (
                    f"{doctor.name} no atiende los {DIAS_PLURAL[cuando.weekday()]}. "
                    f"Atiende {_texto_franjas(todas)}. Ofrecele uno de esos días."
                ),
            }

        minuto_inicio = cuando.hour * 60 + cuando.minute
        minuto_fin = minuto_inicio + duracion
        # El turno tiene que entrar ENTERO en UNA franja. No se suman franjas
        # contiguas: si el doctor corta a las 12 y vuelve a las 12, es porque
        # cambia de consultorio o de tipo de atención.
        entra = any(
            f.hora_inicio <= minuto_inicio and minuto_fin <= f.hora_fin for f in franjas
        )
        if not entra:
            return {
                "ok": False, "codigo": "fuera_de_franja",
                "motivo": (
                    f"{doctor.name} no atiende a las {cuando.strftime('%H:%M')} "
                    f"los {DIAS_PLURAL[cuando.weekday()]}"
                    + (f" (el turno dura {duracion} minutos)" if duracion != DURACION_POR_DEFECTO else "")
                    + f". Ese día atiende de "
                    + " y de ".join(f"{_hhmm(f.hora_inicio)} a {_hhmm(f.hora_fin)}" for f in franjas)
                    + ". Ofrecele un horario que entre."
                ),
            }
    else:
        # Sin horario propio, el horario de la INSTITUCIÓN acota pero no
        # habilita: sirve para descartar el domingo a las 23:00, no para
        # afirmar que ese profesional está disponible.
        de_la_clinica = _franjas(db, company.id, None, cuando.weekday(), None)
        hay_horario_clinica = (
            db.query(DoctorSchedule.id)
            .filter(DoctorSchedule.company_id == company.id,
                    DoctorSchedule.doctor_id.is_(None))
            .first()
        )
        if hay_horario_clinica:
            minuto_inicio = cuando.hour * 60 + cuando.minute
            minuto_fin = minuto_inicio + duracion
            if not any(f.hora_inicio <= minuto_inicio and minuto_fin <= f.hora_fin
                       for f in de_la_clinica):
                return {
                    "ok": False, "codigo": "fuera_horario_clinica",
                    "motivo": (
                        f"El centro no atiende los {DIAS_PLURAL[cuando.weekday()]} a las "
                        f"{cuando.strftime('%H:%M')}. Ofrecele otro horario."
                    ),
                }

    choque = _choca(db, company.id, doctor.id, cuando, fin, ignorar_cita_id)
    if choque:
        return {
            "ok": False, "codigo": "ocupado",
            "motivo": (
                f"Ese horario se superpone con otro turno "
                f"({choque.scheduled_at.strftime('%H:%M')}). Ofrecele otro."
            ),
            "alternativas": huecos_del_dia(
                db, company, doctor, cuando.date(), service_id, ahora=ahora
            )[:4],
        }

    return {
        "ok": True,
        "duracion_min": duracion,
        # Lo que separa "tenés turno" de "queda pedido". El bot lo usa para no
        # prometer lo que nadie declaró.
        "verificacion": "verificado" if estructurado else "sin_verificar",
    }


def huecos_del_dia(
    db: Session,
    company: Company,
    doctor: Doctor,
    dia: date,
    service_id: int | None = None,
    ahora: datetime | None = None,
    paso: int = 15,
    tope: int = 12,
) -> list[str]:
    """Horarios realmente libres, calculados en el servidor.

    Devuelve vacío si el profesional no tiene horario estructurado: no se
    inventan huecos de una franja que nadie declaró.
    """
    if doctor.agenda_mode != "estructurado":
        return []
    ahora = ahora or datetime.now()
    if _ausencia(db, company.id, doctor.id, dia):
        return []
    franjas = _franjas(db, company.id, doctor.id, dia.weekday(), service_id)
    if not franjas:
        return []
    duracion = duracion_de(db, company.id, service_id)

    libres: list[str] = []
    for f in franjas:
        minuto = f.hora_inicio
        # El turno tiene que ENTRAR ENTERO antes del cierre: una ecografía de
        # 45 minutos no se ofrece a las 14:30 si la franja termina a las 15:00.
        while minuto + duracion <= f.hora_fin and len(libres) < tope:
            inicio = datetime.combine(dia, datetime.min.time()) + timedelta(minutes=minuto)
            if inicio >= ahora + timedelta(minutes=MINUTOS_DE_ANTICIPACION):
                if not _choca(db, company.id, doctor.id, inicio,
                              inicio + timedelta(minutes=duracion), None):
                    libres.append(_hhmm(minuto))
            minuto += paso
    return libres
