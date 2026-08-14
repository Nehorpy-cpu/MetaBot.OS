"""Resumen que recibe el PROFESIONAL antes de atender, no el paciente.

Lo que existía era una lista de citas: hora, nombre y teléfono. Eso le dice al
doctor a quién va a ver, no lo que necesita saber antes de que entre: si el
paciente ya vino, qué se le recetó la vez pasada, y qué se le va a hacer hoy.

Tres decisiones que importan:

**Se arma desde la base, sin pasar por ningún modelo.** Es información
clínica: un resumen "mejorado" por un LLM es un resumen que puede afirmar algo
que el doctor nunca escribió. Igual que las recetas, esto se relata, no se
genera.

**Va al profesional que atiende, y a nadie más.** Cada resumen contiene solo
sus propios pacientes del día. El historial sale de la misma institución —una
receta de otro colega del centro es dato clínico legítimo y va con su nombre—
pero nunca cruza de empresa.

**El paciente se identifica por su teléfono.** Es el mismo criterio que usa
todo el producto. Tiene un límite real y conviene tenerlo escrito: dos
personas que comparten un celular comparten historial. Por eso el resumen dice
"con este número" y no "este paciente".
"""
import logging
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from .config import TIMEZONE

from .models import (
    Appointment,
    Company,
    Doctor,
    Prescription,
    PrescriptionItem,
    Service,
)

logger = logging.getLogger("metabot.previsita")

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

# Cuánto historial se mira hacia atrás. Más que esto es arqueología: si el
# paciente vino hace tres años, lo que importa es que hace tres años que no
# viene, no el detalle de esa consulta.
MESES_DE_HISTORIAL = 24


def _telefono(valor: str) -> str:
    """Forma canónica de un número paraguayo, para comparar.

    No alcanza con quitar los no-dígitos: el mismo celular se guarda como
    "595981111222" (el wa_id que manda Meta cuando escribe por WhatsApp) y
    como "0981 111-222" (lo que tipea recepción en el panel). Sin sacar el
    prefijo, esas dos filas son personas distintas para el sistema y el
    historial se parte al medio.
    """
    d = "".join(c for c in (valor or "") if c.isdigit())
    if d.startswith("00"):
        d = d[2:]
    if d.startswith("595"):
        d = d[3:]
    elif d.startswith("0"):
        d = d[1:]
    return d


def _a_utc(local_ingenuo: datetime) -> datetime:
    """Hora de la agenda (Paraguay) → UTC, para comparar contra `issued_at`.

    La agenda se guarda en hora local —es lo que el paciente dice y lo que el
    panel muestra— y las recetas en UTC. Mezclar los dos relojes es un error
    silencioso: no falla nada, simplemente falta una receta.
    """
    return (
        local_ingenuo.replace(tzinfo=ZoneInfo(TIMEZONE))
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )


def _clave_de_nombre(nombre: str) -> str:
    """Nombre comparable: sin tildes, minúsculas, palabras ordenadas."""
    limpio = unicodedata.normalize("NFD", (nombre or "").lower())
    limpio = "".join(c for c in limpio if unicodedata.category(c) != "Mn")
    limpio = re.sub(r"\b(dr|dra|lic|sr|sra|srta|don|dona)\.?\b", " ", limpio)
    return " ".join(sorted(w for w in re.split(r"[^a-z0-9]+", limpio) if len(w) > 1))


def _mismo_paciente(a: str, b: str) -> bool:
    """¿Los dos registros son de la misma persona?

    El teléfono NO alcanza como identidad. En Paraguay una madre agenda con su
    celular para ella y para el hijo, y recepción carga su propio número para
    quien no tiene. Sin comparar el nombre, el resumen le muestra al pediatra
    el diagnóstico psiquiátrico de la madre atribuido al chico: un dato de
    salud de una persona que ese profesional no atiende, ya fuera del sistema
    y sin forma de retirarlo.
    """
    ca, cb = _clave_de_nombre(a), _clave_de_nombre(b)
    if not ca or not cb:
        return False
    if ca == cb:
        return True
    # "Marco Garcete" contra "Marco Antonio Garcete": el registro más corto
    # tiene que estar contenido en el otro, no basta con una palabra suelta.
    pa, pb = set(ca.split()), set(cb.split())
    chico, grande = (pa, pb) if len(pa) <= len(pb) else (pb, pa)
    return len(chico) >= 2 and chico <= grande


def _filtro_de_telefono(columna, digitos: str):
    """Prefiltro en SQL por los últimos dígitos del número.

    Limpia los separadores DENTRO de la consulta: el número está guardado como
    "+595 981 111-222" o "0981 111-222", así que un LIKE sobre el texto crudo
    no encuentra nada. `replace` anidado funciona igual en SQLite y en
    PostgreSQL, y no hace falta migrar ninguna columna.

    El match fino sigue en Python; lo que NO se puede hacer es al revés
    —limitar primero y filtrar después—, que era el bug: traía las últimas 80
    citas de TODA la empresa y recién ahí buscaba al paciente, así que una
    clínica con 30 pacientes por día perdía todo el historial de más de tres
    días atrás y anunciaba "primera vez" de gente que ya había venido.
    """
    limpia = columna
    for separador in (" ", "-", "(", ")", "+", ".", "/"):
        limpia = func.replace(limpia, separador, "")
    # "Termina con" y no "contiene": después de limpiar, tanto "0981111222"
    # como "595981111222" terminan en los mismos dígitos significativos.
    return limpia.like(f"%{digitos[-8:]}")


def _historial(db: Session, company_id: int, telefono: str, nombre: str,
               antes_de: datetime) -> tuple[list, list, bool]:
    """Visitas anteriores del paciente: (atendidas, faltas, hay_otra_persona)."""
    digitos = _telefono(telefono)
    if len(digitos) < 6:
        return [], [], False
    desde = antes_de - timedelta(days=MESES_DE_HISTORIAL * 30)
    candidatas = (
        db.query(Appointment)
        .filter(
            Appointment.company_id == company_id,
            Appointment.scheduled_at < antes_de,
            Appointment.scheduled_at >= desde,
            Appointment.status.notin_(["cancelled"]),
            _filtro_de_telefono(Appointment.patient_phone, digitos),
        )
        .order_by(Appointment.scheduled_at.desc())
        .limit(60)
        .all()
    )
    del_numero = [a for a in candidatas if _telefono(a.patient_phone) == digitos]
    propias = [a for a in del_numero if _mismo_paciente(a.patient_name, nombre)]
    otra_persona = len(propias) < len(del_numero)
    # `no_show` es una afirmación explícita de que el paciente NO se presentó:
    # contarla como consulta previa le hace creer al doctor que hubo una visita
    # que nunca ocurrió. Se lleva aparte porque "faltó tres veces" es
    # justamente lo que quiere saber.
    vino = [a for a in propias if a.status != "no_show"][:6]
    falto = [a for a in propias if a.status == "no_show"][:6]
    return vino, falto, otra_persona


def _ultima_receta(db: Session, company_id: int, telefono: str, nombre: str,
                   antes_de: datetime):
    digitos = _telefono(telefono)
    if len(digitos) < 6:
        return None, []
    # `antes_de` viene de `Appointment.scheduled_at`, que se guarda en hora de
    # Paraguay; `Prescription.issued_at` se guarda en UTC. Compararlos crudos
    # es mezclar dos relojes: la receta que el doctor cargó ESTA mañana queda
    # "3 horas en el futuro" y desaparece del resumen del turno de la tarde,
    # que es justo cuando más la necesita.
    antes_de = _a_utc(antes_de)
    desde = antes_de - timedelta(days=MESES_DE_HISTORIAL * 30)
    recetas = (
        db.query(Prescription)
        .filter(
            Prescription.company_id == company_id,
            Prescription.status != "cancelled",
            Prescription.issued_at <= antes_de,
            Prescription.issued_at >= desde,
            _filtro_de_telefono(Prescription.patient_phone, digitos),
        )
        .order_by(Prescription.issued_at.desc())
        .limit(10)
        .all()
    )
    receta = next(
        (r for r in recetas
         if _telefono(r.patient_phone) == digitos
         and _mismo_paciente(r.patient_name, nombre)),
        None,
    )
    if not receta:
        return None, []
    items = (
        db.query(PrescriptionItem)
        .filter(
            PrescriptionItem.company_id == company_id,
            PrescriptionItem.prescription_id == receta.id,
        )
        .all()
    )
    return receta, items


def ficha_de_la_cita(db: Session, company: Company, cita: Appointment,
                     ahora: datetime | None = None) -> dict:
    """Lo que el profesional necesita saber de ESE paciente, en datos."""
    ahora = ahora or datetime.now(ZoneInfo(TIMEZONE)).replace(tzinfo=None)
    servicio = (
        db.query(Service)
        .filter(Service.company_id == company.id, Service.id == cita.service_id)
        .first()
        if cita.service_id else None
    )
    # El corte es el momento presente además de la hora de la cita: el resumen
    # sale la noche anterior, así que NINGUNA cita del día siguiente ocurrió
    # todavía. Sin esto, un paciente con turno a las 09:00 y otro a las 15:00
    # aparecía en el segundo como "ya vino, última visita: mañana".
    corte = min(cita.scheduled_at, ahora)
    previas, faltas, otra_persona = _historial(
        db, company.id, cita.patient_phone, cita.patient_name, corte)
    receta, items = _ultima_receta(
        db, company.id, cita.patient_phone, cita.patient_name, corte)

    doctores = {d.id: d.name for d in db.query(Doctor).filter(
        Doctor.company_id == company.id).all()}

    ficha = {
        "hora": cita.scheduled_at.strftime("%H:%M"),
        "paciente": cita.patient_name,
        "telefono": cita.patient_phone,
        "motivo": cita.notes or "",
        "servicio": servicio.name if servicio else "",
        "duracion_min": cita.duration_min,
        "estado": cita.status,
        # El teléfono va en el JSON pero NUNCA en el texto que se manda por
        # WhatsApp: acá sirve para que el portal pueda abrir la ficha del
        # paciente desde el post-it, y quien lo lee ya es su médico.
        "telefono": cita.patient_phone,
        # La diferencia más importante de todas: no se atiende igual a alguien
        # que viene por primera vez que a alguien que ya vino seis veces.
        "primera_vez": not previas,
        "visitas_previas": len(previas),
        # Faltas sin avisar. Es información que el doctor quiere y que antes
        # se contaba como si hubiera venido.
        "faltas_previas": len(faltas),
        # Hay registros con el mismo número a nombre de OTRA persona. No se
        # muestran: se avisa que existen, para que el profesional pregunte.
        "numero_compartido": otra_persona,
        "ultima_visita": (
            f"{previas[0].scheduled_at.strftime('%d/%m/%Y')} con "
            f"{doctores.get(previas[0].doctor_id, 'otro profesional')}"
            if previas else ""
        ),
        # Si la cita no está confirmada, el doctor conviene que lo sepa antes
        # de bloquear el horario.
        "sin_confirmar": cita.status == "pending",
        # Si nadie verificó el turno contra un horario, puede no ser real.
        "turno_sin_verificar": cita.verificacion in ("sin_verificar", "forzada"),
    }
    if servicio and servicio.prep:
        ficha["preparacion_requerida"] = servicio.prep
    if receta:
        ficha["ultima_receta"] = {
            "fecha": receta.issued_at.strftime("%d/%m/%Y"),
            "por": doctores.get(receta.doctor_id, ""),
            "diagnostico": receta.diagnosis,
            "medicacion": [
                f"{i.medication} {i.dose}".strip()
                + (f" — {i.frequency}" if i.frequency else "")
                for i in items
            ],
            "vigente": receta.status == "active",
        }
    return ficha


def armar(db: Session, company: Company, doctor: Doctor,
          dia: date | None = None) -> dict:
    """El resumen del día para un profesional."""
    # La agenda vive en hora de Paraguay; `date.today()` usaría el reloj UTC
    # del contenedor y, de madrugada, el resumen sería del día equivocado.
    ahora = datetime.now(ZoneInfo(TIMEZONE)).replace(tzinfo=None)
    dia = dia or ahora.date()
    inicio = datetime(dia.year, dia.month, dia.day)
    fin = inicio.replace(hour=23, minute=59, second=59)
    citas = (
        db.query(Appointment)
        .filter(
            Appointment.company_id == company.id,
            Appointment.doctor_id == doctor.id,
            Appointment.scheduled_at >= inicio,
            Appointment.scheduled_at <= fin,
            Appointment.status.notin_(["cancelled"]),
        )
        .order_by(Appointment.scheduled_at)
        .all()
    )
    fichas = [ficha_de_la_cita(db, company, c, ahora=ahora) for c in citas]
    return {
        "doctor": doctor.name,
        "doctor_id": doctor.id,
        "fecha": dia.isoformat(),
        "dia_de_la_semana": DIAS[dia.weekday()],
        "total": len(fichas),
        "primera_vez": sum(1 for f in fichas if f["primera_vez"]),
        "sin_confirmar": sum(1 for f in fichas if f["sin_confirmar"]),
        "pacientes": fichas,
        "texto": _texto(doctor, dia, fichas, company),
    }


def _texto(doctor: Doctor, dia: date, fichas: list[dict], company: Company) -> str:
    """El mensaje listo para mandarle al profesional.

    Se arma acá, con f-strings, y no con un modelo: es información clínica y
    un resumen "redactado" puede afirmar algo que el doctor nunca escribió.
    """
    encabezado = [
        f"*Tu agenda del {DIAS[dia.weekday()]} {dia.strftime('%d/%m')}* — {company.name}",
        f"{doctor.name}",
    ]
    if not fichas:
        encabezado.append("\nNo tenés pacientes agendados para ese día.")
        return "\n".join(encabezado)

    nuevos = sum(1 for f in fichas if f["primera_vez"])
    resumen = f"{len(fichas)} paciente{'s' if len(fichas) != 1 else ''}"
    if nuevos:
        resumen += f", {nuevos} por primera vez"
    sin_confirmar = sum(1 for f in fichas if f["sin_confirmar"])
    if sin_confirmar:
        resumen += f", {sin_confirmar} sin confirmar"
    encabezado.append(resumen)
    encabezado.append("━━━━━━━━━━━━━━━━━━")

    bloques = []
    for f in fichas:
        lineas = [f"*{f['hora']}* · {f['paciente']}"]
        detalle = []
        if f["servicio"]:
            detalle.append(f["servicio"])
        if f["motivo"]:
            detalle.append(f["motivo"])
        if detalle:
            lineas.append("  " + " · ".join(detalle))

        if f["primera_vez"]:
            lineas.append("  🆕 Primera vez en el centro")
        else:
            # "veces", no "vez"+"ces": el plural cambia la z por c.
            veces = "vez" if f["visitas_previas"] == 1 else "veces"
            lineas.append(
                f"  Ya vino {f['visitas_previas']} {veces}. "
                f"Última: {f['ultima_visita']}"
            )
        if f["faltas_previas"]:
            veces = "vez" if f["faltas_previas"] == 1 else "veces"
            lineas.append(f"  ⚠️ Faltó {f['faltas_previas']} {veces} sin avisar")
        if f["numero_compartido"]:
            lineas.append(
                "  ℹ️ Con este mismo número hay registros a nombre de otra "
                "persona (no se muestran). Confirmá con quién estás hablando."
            )

        receta = f.get("ultima_receta")
        if receta:
            quien = f" (Dr./Dra. {receta['por']})" if receta["por"] != doctor.name else ""
            lineas.append(f"  💊 Receta del {receta['fecha']}{quien}:")
            if receta["diagnostico"]:
                lineas.append(f"     Dx: {receta['diagnostico']}")
            for med in receta["medicacion"][:4]:
                lineas.append(f"     • {med}")
            if len(receta["medicacion"]) > 4:
                lineas.append(f"     • …y {len(receta['medicacion']) - 4} más")

        if f.get("preparacion_requerida"):
            lineas.append(f"  ⚠️ Preparación: {f['preparacion_requerida']}")
        if f["sin_confirmar"]:
            lineas.append("  ⏳ No confirmó todavía")
        if f["turno_sin_verificar"]:
            lineas.append("  ❓ Turno tomado sin verificar contra tu horario")
        bloques.append("\n".join(lineas))

    pie = [
        "━━━━━━━━━━━━━━━━━━",
        "_Datos cargados en el sistema, sin interpretación. "
        "El historial se busca por el número de teléfono del paciente._",
    ]
    return "\n".join(encabezado + [""] + ["\n\n".join(bloques)] + [""] + pie)
