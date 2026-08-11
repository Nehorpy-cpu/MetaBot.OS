"""La agenda la verifica el servidor, no el modelo.

El fallo que estas pruebas cierran, medido en producción: `book_appointment`
validaba solape con otras citas y nada más. Un paciente podía quedar agendado
un domingo a las 23:00 con un doctor que atiende lunes a viernes de mañana, y
el sistema le mandaba el recordatorio T-24h de una cita que no existía. El
domingo el paciente viajaba a una clínica cerrada.
"""
from datetime import date, datetime, timedelta

import pytest

from tests.test_api import _create_company, client

from app import agenda
from app.db import SessionLocal
from app.models import (
    Appointment,
    Company,
    Doctor,
    DoctorAbsence,
    DoctorSchedule,
    DoctorService,
    Service,
)

LUN, MAR, MIE, JUE, VIE, SAB, DOM = range(7)


def _proximo(weekday: int, hora: int, minuto: int = 0, desde: datetime | None = None):
    """La próxima fecha futura que caiga en ese día de la semana."""
    base = desde or datetime.now()
    dias = (weekday - base.weekday()) % 7
    fecha = (base + timedelta(days=dias or 7)).replace(
        hour=hora, minute=minuto, second=0, microsecond=0)
    return fecha


def _armar(nombre, franjas=(), modo="estructurado", servicios=()):
    """Empresa + doctor con sus franjas. `franjas` = (weekday, desde, hasta)
    en 'HH:MM'."""
    company = _create_company(name=nombre)
    resp = client.post(
        f"/api/companies/{company['id']}/doctors",
        json={"name": "Dra. Agenda", "specialty": "Cardiología",
              "schedule": "Lun a Vie 08:00-14:00", "phone": "", "email": ""},
    )
    assert resp.status_code == 201, f"no se creó el doctor: {resp.status_code} {resp.text}"
    doctor = resp.json()
    db = SessionLocal()
    try:
        doc = db.get(Doctor, doctor["id"])
        assert doc is not None, f"el doctor {doctor['id']} no está en la base"
        doc.agenda_mode = modo
        for weekday, desde, hasta in franjas:
            hi = int(desde[:2]) * 60 + int(desde[3:])
            hf = int(hasta[:2]) * 60 + int(hasta[3:])
            db.add(DoctorSchedule(company_id=company["id"], doctor_id=doc.id,
                                  weekday=weekday, hora_inicio=hi, hora_fin=hf))
        ids = {}
        for sn, dur in servicios:
            s = Service(company_id=company["id"], name=sn, duration_min=dur)
            db.add(s)
            db.flush()
            ids[sn] = s.id
        db.commit()
        return company["id"], doctor["id"], ids
    finally:
        db.close()


def _verificar(company_id, doctor_id, cuando, **kw):
    db = SessionLocal()
    try:
        return agenda.verificar_turno(
            db, db.get(Company, company_id), db.get(Doctor, doctor_id), cuando, **kw)
    finally:
        db.close()


# --- El fallo original ---


def test_no_se_agenda_el_domingo_con_un_doctor_que_atiende_de_lunes_a_viernes():
    """EL fallo: el paciente viajaba el domingo a una clínica cerrada, después
    de recibir un recordatorio de una cita que no existía."""
    cid, did, _ = _armar("Clínica Domingo",
                         [(d, "08:00", "14:00") for d in (LUN, MAR, MIE, JUE, VIE)])
    v = _verificar(cid, did, _proximo(DOM, 23, 0))
    assert v["ok"] is False
    assert v["codigo"] == "sin_franjas_ese_dia"
    assert "no atiende los domingos" in v["motivo"]
    # Y le dice al bot qué ofrecer en su lugar.
    assert "lunes" in v["motivo"]


def test_dentro_del_horario_se_agenda():
    cid, did, _ = _armar("Clínica OK",
                         [(d, "08:00", "14:00") for d in (LUN, MAR, MIE, JUE, VIE)])
    v = _verificar(cid, did, _proximo(MIE, 10, 0))
    assert v["ok"] is True
    assert v["verificacion"] == "verificado"


def test_fuera_de_la_franja_aunque_sea_un_dia_que_atiende():
    cid, did, _ = _armar("Clínica Tarde", [(MIE, "08:00", "14:00")])
    v = _verificar(cid, did, _proximo(MIE, 19, 0))
    assert v["ok"] is False
    assert v["codigo"] == "fuera_de_franja"
    assert "08:00 a 14:00" in v["motivo"]


# --- El turno tiene que entrar entero ---


def test_un_estudio_largo_no_entra_justo_antes_del_cierre():
    """Franja hasta las 15:00 y un estudio de 45 minutos a las 14:30: hoy el
    paciente salía a las 15:15 de una clínica que cierra a las 15:00."""
    cid, did, ids = _armar("Clínica Borde", [(MAR, "08:00", "15:00")],
                           servicios=[("Ecocardiograma", 45)])
    v = _verificar(cid, did, _proximo(MAR, 14, 30), service_id=ids["Ecocardiograma"])
    assert v["ok"] is False
    assert v["codigo"] == "fuera_de_franja"
    # Media hora antes sí entra.
    assert _verificar(cid, did, _proximo(MAR, 14, 15),
                      service_id=ids["Ecocardiograma"])["ok"] is True


def test_los_huecos_ofrecidos_no_incluyen_los_que_no_entran():
    cid, did, ids = _armar("Clínica Huecos", [(MAR, "08:00", "15:00")],
                           servicios=[("Ecocardiograma", 45)])
    db = SessionLocal()
    try:
        libres = agenda.huecos_del_dia(
            db, db.get(Company, cid), db.get(Doctor, did),
            _proximo(MAR, 8, 0).date(), ids["Ecocardiograma"], tope=99)
    finally:
        db.close()
    assert "14:30" not in libres, "ofreció un horario donde el estudio no entra"
    assert "14:15" in libres


def test_no_se_suman_franjas_contiguas():
    """Si el doctor corta a las 12 y vuelve a las 12 es porque cambia de
    consultorio: un turno de una hora a las 11:30 no cabe."""
    cid, did, ids = _armar("Clínica Contiguas",
                           [(MIE, "08:00", "12:00"), (MIE, "12:00", "16:00")],
                           servicios=[("Procedimiento", 60)])
    v = _verificar(cid, did, _proximo(MIE, 11, 30), service_id=ids["Procedimiento"])
    assert v["ok"] is False


# --- Duración real y solapes ---


def test_la_duracion_sale_del_servicio():
    cid, _, ids = _armar("Clínica Duración", [(MIE, "08:00", "16:00")],
                         servicios=[("Consulta", 20), ("Ecografía", 45)])
    db = SessionLocal()
    try:
        assert agenda.duracion_de(db, cid, ids["Consulta"]) == 20
        assert agenda.duracion_de(db, cid, ids["Ecografía"]) == 45
        assert agenda.duracion_de(db, cid, None) == 30
    finally:
        db.close()


@pytest.mark.parametrize("valor,esperado", [(0, 5), (-10, 5), (99999, 480)])
def test_la_duracion_tiene_piso_y_techo(valor, esperado):
    """Con duración 0 la cita ocupa un intervalo vacío: no solapa con nada y
    se pueden apilar infinitas a la misma hora. La clínica edita ese campo
    desde el panel."""
    cid, _, ids = _armar(f"Clínica Duración {valor}", servicios=[("Raro", valor)])
    db = SessionLocal()
    try:
        assert agenda.duracion_de(db, cid, ids["Raro"]) == esperado
    finally:
        db.close()


def test_una_cita_larga_previa_bloquea_aunque_haya_empezado_mucho_antes():
    """La ventana de búsqueda de solapes tiene que cubrir la duración máxima:
    con una ventana corta, un estudio de 8 horas empezado a la mañana no
    aparecía y el solape pasaba."""
    cid, did, ids = _armar("Clínica Larga", [(MIE, "07:00", "20:00")],
                           servicios=[("Estudio largo", 480)])
    inicio = _proximo(MIE, 8, 0)
    db = SessionLocal()
    try:
        db.add(Appointment(company_id=cid, doctor_id=did, patient_name="Otro",
                           patient_phone="595981000000", scheduled_at=inicio,
                           duration_min=480, status="pending"))
        db.commit()
    finally:
        db.close()
    v = _verificar(cid, did, inicio + timedelta(hours=7))
    assert v["ok"] is False
    assert v["codigo"] == "ocupado"


def test_al_chocar_ofrece_alternativas_reales():
    cid, did, _ = _armar("Clínica Alternativas", [(MIE, "08:00", "12:00")])
    inicio = _proximo(MIE, 9, 0)
    db = SessionLocal()
    try:
        db.add(Appointment(company_id=cid, doctor_id=did, patient_name="Otro",
                           patient_phone="595981000001", scheduled_at=inicio,
                           duration_min=30, status="pending"))
        db.commit()
    finally:
        db.close()
    v = _verificar(cid, did, inicio)
    assert v["codigo"] == "ocupado"
    assert v["alternativas"], "no ofreció ningún horario alternativo"
    assert "09:00" not in v["alternativas"]


# --- Licencias y cierres ---


def test_un_doctor_de_licencia_no_recibe_turnos():
    cid, did, _ = _armar("Clínica Licencia", [(d, "08:00", "14:00") for d in range(5)])
    cuando = _proximo(MIE, 10, 0)
    db = SessionLocal()
    try:
        db.add(DoctorAbsence(company_id=cid, doctor_id=did,
                             desde=cuando.date() - timedelta(days=2),
                             hasta=cuando.date() + timedelta(days=5),
                             motivo="vacaciones"))
        db.commit()
    finally:
        db.close()
    v = _verificar(cid, did, cuando)
    assert v["ok"] is False
    assert v["codigo"] == "ausencia"
    assert "vacaciones" in v["motivo"]
    assert "Vuelve a atender" in v["motivo"]


def test_el_cierre_de_la_clinica_alcanza_a_todos():
    """Una ausencia sin doctor cierra la institución: feriado, mudanza, lo
    que sea."""
    cid, did, _ = _armar("Clínica Cerrada", [(d, "08:00", "14:00") for d in range(5)])
    cuando = _proximo(MIE, 10, 0)
    db = SessionLocal()
    try:
        db.add(DoctorAbsence(company_id=cid, doctor_id=None, desde=cuando.date(),
                             hasta=cuando.date(), motivo="feriado"))
        db.commit()
    finally:
        db.close()
    v = _verificar(cid, did, cuando)
    assert v["ok"] is False and v["codigo"] == "ausencia"
    assert "La institución no atiende" in v["motivo"]


def test_la_licencia_se_respeta_tambien_sin_horario_estructurado():
    """En modo libre no sabemos su horario, pero la licencia es un dato duro
    que alguien cargó."""
    cid, did, _ = _armar("Clínica Libre Licencia", modo="libre")
    cuando = _proximo(MIE, 10, 0)
    db = SessionLocal()
    try:
        db.add(DoctorAbsence(company_id=cid, doctor_id=did, desde=cuando.date(),
                             hasta=cuando.date(), motivo="congreso"))
        db.commit()
    finally:
        db.close()
    assert _verificar(cid, did, cuando)["codigo"] == "ausencia"


# --- El doctor que todavía no cargó su horario ---


def test_sin_horario_cargado_se_sigue_agendando_pero_sin_prometer():
    """Bloquear a una clínica que no cargó su horario le rompe el negocio.
    Lo que cambia es que la cita queda como PEDIDO."""
    cid, did, _ = _armar("Clínica Sin Cargar", modo="libre")
    v = _verificar(cid, did, _proximo(DOM, 23, 0))
    assert v["ok"] is True
    assert v["verificacion"] == "sin_verificar"


def test_el_horario_de_la_institucion_acota_pero_no_habilita():
    """Cinco filas matan el domingo a las 23:00 para los 40 médicos. Pero un
    turno DENTRO de ese horario sigue sin estar verificado: la clínica declaró
    cuándo abre, no cuándo está cada profesional."""
    cid, did, _ = _armar("Clínica Institución", modo="libre")
    db = SessionLocal()
    try:
        for d in (LUN, MAR, MIE, JUE, VIE):
            db.add(DoctorSchedule(company_id=cid, doctor_id=None, weekday=d,
                                  hora_inicio=7 * 60, hora_fin=19 * 60))
        db.commit()
    finally:
        db.close()

    fuera = _verificar(cid, did, _proximo(DOM, 23, 0))
    assert fuera["ok"] is False
    assert fuera["codigo"] == "fuera_horario_clinica"

    dentro = _verificar(cid, did, _proximo(MIE, 10, 0))
    assert dentro["ok"] is True
    assert dentro["verificacion"] == "sin_verificar", "prometió algo que nadie declaró"


def test_estructurado_sin_franjas_falla_cerrado():
    """Marcado como estructurado pero sin franjas: volver en silencio a "se
    agenda cualquier cosa" sería peor que decir que no se puede."""
    cid, did, _ = _armar("Clínica Vacía", modo="estructurado")
    v = _verificar(cid, did, _proximo(MIE, 10, 0))
    assert v["ok"] is False
    assert v["codigo"] == "sin_franjas_cargadas"
    assert "escalá a un humano" in v["motivo"]


def test_sin_horario_no_se_inventan_huecos():
    cid, did, _ = _armar("Clínica Sin Huecos", modo="libre")
    db = SessionLocal()
    try:
        libres = agenda.huecos_del_dia(db, db.get(Company, cid), db.get(Doctor, did),
                                       _proximo(MIE, 8, 0).date())
    finally:
        db.close()
    assert libres == []


# --- Consulta y estudio con el mismo profesional ---


def test_el_estudio_solo_se_hace_en_su_franja():
    """El cardiólogo atiende consulta toda la semana pero hace ecos solo los
    martes a la tarde."""
    cid, did, ids = _armar("Clínica Eco", servicios=[("Ecocardiograma", 45)])
    db = SessionLocal()
    try:
        eco = ids["Ecocardiograma"]
        # Consulta: lunes a viernes de mañana.
        for d in (LUN, MAR, MIE, JUE, VIE):
            db.add(DoctorSchedule(company_id=cid, doctor_id=did, weekday=d,
                                  hora_inicio=8 * 60, hora_fin=12 * 60))
        # Eco: solo martes a la tarde.
        db.add(DoctorSchedule(company_id=cid, doctor_id=did, weekday=MAR,
                              hora_inicio=14 * 60, hora_fin=18 * 60, service_id=eco))
        db.commit()
    finally:
        db.close()

    # Consulta el lunes a la mañana: bien.
    assert _verificar(cid, did, _proximo(LUN, 9, 0))["ok"] is True
    # Eco el lunes a la mañana: no, aunque el doctor esté ahí.
    assert _verificar(cid, did, _proximo(LUN, 9, 0), service_id=ids["Ecocardiograma"])["ok"] is False
    # Eco el martes a la tarde: bien.
    assert _verificar(cid, did, _proximo(MAR, 15, 0), service_id=ids["Ecocardiograma"])["ok"] is True


def test_no_se_ofrece_un_estudio_con_quien_no_lo_hace():
    cid, did, ids = _armar("Clínica No Hace", [(MIE, "08:00", "16:00")],
                           servicios=[("Consulta", 30), ("Ecocardiograma", 45)])
    db = SessionLocal()
    try:
        # La clínica declaró que este doctor hace SOLO la consulta.
        db.add(DoctorService(company_id=cid, doctor_id=did, service_id=ids["Consulta"]))
        db.commit()
    finally:
        db.close()
    v = _verificar(cid, did, _proximo(MIE, 10, 0), service_id=ids["Ecocardiograma"])
    assert v["ok"] is False
    assert v["codigo"] == "servicio_no_habilitado"
    assert "no realiza" in v["motivo"]


def test_si_la_clinica_no_cargo_que_hace_cada_uno_no_se_bloquea_a_nadie():
    """No migrado no es lo mismo que prohibido."""
    cid, did, ids = _armar("Clínica Sin Vincular", [(MIE, "08:00", "16:00")],
                           servicios=[("Ecocardiograma", 45)])
    assert _verificar(cid, did, _proximo(MIE, 10, 0),
                      service_id=ids["Ecocardiograma"])["ok"] is True


# --- Anticipación ---


def test_no_se_agenda_para_dentro_de_diez_minutos():
    cid, did, _ = _armar("Clínica Ya", [(d, "00:00", "23:59") for d in range(7)])
    v = _verificar(cid, did, datetime.now() + timedelta(minutes=10))
    assert v["ok"] is False
    assert v["codigo"] == "muy_pronto"


def test_el_pasado_se_rechaza():
    cid, did, _ = _armar("Clínica Pasado", [(d, "00:00", "23:59") for d in range(7)])
    v = _verificar(cid, did, datetime.now() - timedelta(days=1))
    assert v["ok"] is False and v["codigo"] == "muy_pronto"


# --- El texto libre no se parsea ---


def test_agenda_no_toca_el_texto_libre_del_horario():
    """Interpretar `Doctor.schedule` con una regex para decidir si hay turno
    sería la misma regla violada con otro disfraz."""
    fuente = (__import__("pathlib").Path(agenda.__file__)).read_text(encoding="utf-8")
    cuerpo = fuente.split('"""', 2)[-1]  # sin el docstring del módulo
    # `Doctor.schedule` puntual, no cualquier cosa que lo contenga:
    # `Appointment.scheduled_at` es otra columna y es legítima.
    assert "Doctor.schedule" not in cuerpo
    assert "doctor.schedule" not in cuerpo
    assert "import re" not in cuerpo
