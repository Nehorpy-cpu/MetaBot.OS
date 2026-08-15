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


# --- La clínica carga su horario desde el panel ---


def test_cargar_el_horario_pasa_la_agenda_a_verificada():
    company = _create_company(name="Clínica Panel Horario")
    cid = company["id"]
    doc = client.post(f"/api/companies/{cid}/doctors",
                      json={"name": "Dr. Panel", "schedule": "Lun a Vie 08-14"}).json()

    antes = client.get(f"/api/companies/{cid}/doctors/{doc['id']}/schedule").json()
    assert antes["agenda_mode"] == "libre"
    assert antes["franjas"] == []
    assert "recepción confirma" in antes["nota"]
    # El texto libre se muestra para transcribirlo, no se interpreta.
    assert antes["texto_libre"] == "Lun a Vie 08-14"

    r = client.put(f"/api/companies/{cid}/doctors/{doc['id']}/schedule", json={
        "franjas": [{"weekday": d, "desde": "08:00", "hasta": "14:00"} for d in range(5)]})
    assert r.status_code == 200
    assert r.json()["agenda_mode"] == "estructurado"
    assert r.json()["franjas"] == 5

    despues = client.get(f"/api/companies/{cid}/doctors/{doc['id']}/schedule").json()
    assert len(despues["franjas"]) == 5
    assert despues["franjas"][0]["desde"] == "08:00"


def test_al_cambiar_el_horario_se_listan_las_citas_que_quedan_afuera():
    """Son personas que ya reservaron: se avisan, no se cancelan solas."""
    company = _create_company(name="Clínica Reprogramar")
    cid = company["id"]
    doc = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dr. Cambio"}).json()
    domingo = _proximo(DOM, 11, 0)
    db = SessionLocal()
    try:
        db.add(Appointment(company_id=cid, doctor_id=doc["id"], patient_name="Ya Reservó",
                           patient_phone="595981555444", scheduled_at=domingo,
                           duration_min=30, status="confirmed"))
        db.commit()
    finally:
        db.close()

    r = client.put(f"/api/companies/{cid}/doctors/{doc['id']}/schedule", json={
        "franjas": [{"weekday": d, "desde": "08:00", "hasta": "14:00"} for d in range(5)]})
    afuera = r.json()["citas_fuera_de_horario"]
    assert len(afuera) == 1
    assert afuera[0]["paciente"] == "Ya Reservó"
    assert afuera[0]["telefono"] == "595981555444"

    # Y la cita SIGUE ahí: la decisión de moverla es de una persona.
    citas = client.get(f"/api/companies/{cid}/appointments").json()
    assert len(citas) == 1


def test_dejar_el_horario_vacio_vuelve_a_modo_libre():
    """Marcarlo estructurado y sin franjas dejaría al profesional sin poder
    recibir ningún turno."""
    company = _create_company(name="Clínica Vacía Panel")
    cid = company["id"]
    doc = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dr. Vacío"}).json()
    client.put(f"/api/companies/{cid}/doctors/{doc['id']}/schedule",
               json={"franjas": [{"weekday": 0, "desde": "08:00", "hasta": "14:00"}]})
    r = client.put(f"/api/companies/{cid}/doctors/{doc['id']}/schedule", json={"franjas": []})
    assert r.json()["agenda_mode"] == "libre"


def test_una_franja_al_reves_se_rechaza():
    company = _create_company(name="Clínica Franja Mala")
    cid = company["id"]
    doc = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dr. Mal"}).json()
    r = client.put(f"/api/companies/{cid}/doctors/{doc['id']}/schedule", json={
        "franjas": [{"weekday": 0, "desde": "14:00", "hasta": "08:00"}]})
    assert r.status_code == 422


def test_el_horario_de_la_clinica_se_carga_una_sola_vez():
    """Cinco filas cubren a los 40 médicos y matan el domingo a las 23:00."""
    company = _create_company(name="Clínica Horario General")
    cid = company["id"]
    r = client.put(f"/api/companies/{cid}/clinic-schedule", json={
        "franjas": [{"weekday": d, "desde": "07:00", "hasta": "19:00"} for d in range(5)]})
    assert r.status_code == 200 and r.json()["franjas"] == 5
    visto = client.get(f"/api/companies/{cid}/clinic-schedule").json()
    assert len(visto["franjas"]) == 5
    assert "no confirma que cada profesional esté" in visto["nota"]


def test_cargar_una_licencia_lista_a_quien_hay_que_llamar():
    company = _create_company(name="Clínica Licencia Panel")
    cid = company["id"]
    doc = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dr. Licencia"}).json()
    cuando = _proximo(MIE, 10, 0)
    db = SessionLocal()
    try:
        db.add(Appointment(company_id=cid, doctor_id=doc["id"], patient_name="Tenía Turno",
                           patient_phone="595981666555", scheduled_at=cuando,
                           duration_min=30, status="confirmed"))
        db.commit()
    finally:
        db.close()

    r = client.post(f"/api/companies/{cid}/absences", json={
        "doctor_id": doc["id"], "desde": cuando.date().isoformat(),
        "hasta": (cuando.date() + timedelta(days=7)).isoformat(), "motivo": "congreso"})
    assert r.status_code == 201
    afectadas = r.json()["citas_afectadas"]
    assert len(afectadas) == 1 and afectadas[0]["paciente"] == "Tenía Turno"

    assert len(client.get(f"/api/companies/{cid}/absences").json()) == 1
    client.delete(f"/api/companies/{cid}/absences/{r.json()['id']}")
    assert client.get(f"/api/companies/{cid}/absences").json() == []


def test_una_licencia_al_reves_se_rechaza():
    company = _create_company(name="Clínica Licencia Mala")
    cid = company["id"]
    r = client.post(f"/api/companies/{cid}/absences", json={
        "desde": "2026-09-10", "hasta": "2026-09-01", "motivo": "?"})
    assert r.status_code == 422


def test_el_horario_de_otra_empresa_no_se_ve():
    a = _create_company(name="Clínica Aislada A")
    b = _create_company(name="Clínica Aislada B")
    doc_a = client.post(f"/api/companies/{a['id']}/doctors", json={"name": "Dr. A"}).json()
    r = client.get(f"/api/companies/{b['id']}/doctors/{doc_a['id']}/schedule")
    assert r.status_code == 404


# --- El alta desde el panel también se valida ---


def test_el_panel_no_carga_un_turno_fuera_de_horario_sin_avisar():
    """Recepción podía cargar un domingo a las 23:00 con un profesional que
    atiende de mañana, y el sistema mandaba el recordatorio de una cita que no
    existe. El bot ya lo rechazaba; este endpoint no chequeaba nada."""
    company = _create_company(name="Clínica Panel Alta")
    cid = company["id"]
    doc = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dr. Panel Alta"}).json()
    client.put(f"/api/companies/{cid}/doctors/{doc['id']}/schedule", json={
        "franjas": [{"weekday": d, "desde": "08:00", "hasta": "14:00"} for d in range(5)]})

    r = client.post(f"/api/companies/{cid}/appointments", json={
        "doctor_id": doc["id"], "patient_name": "Paciente Domingo",
        "scheduled_at": _proximo(DOM, 23, 0).strftime("%Y-%m-%dT%H:%M:%S")})
    assert r.status_code == 409
    detalle = r.json()["detail"]
    assert detalle["codigo"] == "sin_franjas_ese_dia"
    assert "no atiende los domingos" in detalle["motivo"]
    assert detalle["se_puede_forzar"] is True
    assert client.get(f"/api/companies/{cid}/appointments").json() == []


def test_recepcion_puede_forzar_un_sobreturno():
    """Un sobreturno es decisión de la clínica. Lo que no puede ser es un
    descuido: queda marcado como forzada."""
    company = _create_company(name="Clínica Forzar")
    cid = company["id"]
    doc = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dr. Forzar"}).json()
    client.put(f"/api/companies/{cid}/doctors/{doc['id']}/schedule", json={
        "franjas": [{"weekday": d, "desde": "08:00", "hasta": "14:00"} for d in range(5)]})

    r = client.post(f"/api/companies/{cid}/appointments?forzar=true", json={
        "doctor_id": doc["id"], "patient_name": "Sobreturno",
        "scheduled_at": _proximo(DOM, 23, 0).strftime("%Y-%m-%dT%H:%M:%S")})
    assert r.status_code == 201
    assert r.json()["verificacion"] == "forzada"


def test_el_turno_dentro_del_horario_queda_verificado():
    company = _create_company(name="Clínica Alta OK")
    cid = company["id"]
    doc = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dr. Alta OK"}).json()
    client.put(f"/api/companies/{cid}/doctors/{doc['id']}/schedule", json={
        "franjas": [{"weekday": d, "desde": "08:00", "hasta": "14:00"} for d in range(5)]})

    r = client.post(f"/api/companies/{cid}/appointments", json={
        "doctor_id": doc["id"], "patient_name": "En Horario",
        "scheduled_at": _proximo(MIE, 10, 0).strftime("%Y-%m-%dT%H:%M:%S")})
    assert r.status_code == 201
    assert r.json()["verificacion"] == "verificado"


def test_sin_horario_cargado_el_panel_sigue_pudiendo_agendar():
    """Las clínicas que todavía no migraron tienen que poder seguir usando el
    panel igual que antes."""
    company = _create_company(name="Clínica Panel Libre")
    cid = company["id"]
    doc = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dr. Libre"}).json()
    r = client.post(f"/api/companies/{cid}/appointments", json={
        "doctor_id": doc["id"], "patient_name": "Sin Verificar",
        "scheduled_at": _proximo(DOM, 23, 0).strftime("%Y-%m-%dT%H:%M:%S")})
    assert r.status_code == 201
    assert r.json()["verificacion"] == "sin_verificar"


def test_el_turno_toma_la_duracion_del_servicio():
    company = _create_company(name="Clínica Duración Panel")
    cid = company["id"]
    doc = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dr. Dur"}).json()
    svc = client.post(f"/api/companies/{cid}/services", json={
        "name": "Ecografía abdominal", "duration_min": 45, "price_gs": 250000}).json()
    r = client.post(f"/api/companies/{cid}/appointments", json={
        "doctor_id": doc["id"], "patient_name": "Con Servicio",
        "service_id": svc["id"],
        "scheduled_at": _proximo(MIE, 10, 0).strftime("%Y-%m-%dT%H:%M:%S")})
    assert r.status_code == 201
    assert r.json()["duration_min"] == 45


def test_si_el_dia_esta_bien_y_falla_la_hora_ofrece_los_huecos_de_ese_dia():
    """Lo más útil para quien está agendando: no "no atiende a esa hora" a
    secas, sino a qué hora sí."""
    cid, did, _ = _armar("Clínica Huecos Mismo Día", [(MIE, "08:00", "14:00")])
    v = _verificar(cid, did, _proximo(MIE, 19, 0))
    assert v["codigo"] == "fuera_de_franja"
    assert v["alternativas"], "no ofreció horarios del mismo día"
    assert all(h < "14:00" for h in v["alternativas"])


def test_el_panel_recibe_los_horarios_libres_al_rechazar():
    company = _create_company(name="Clínica Panel Huecos")
    cid = company["id"]
    doc = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dr. Huecos"}).json()
    client.put(f"/api/companies/{cid}/doctors/{doc['id']}/schedule", json={
        "franjas": [{"weekday": MIE, "desde": "08:00", "hasta": "14:00"}]})
    r = client.post(f"/api/companies/{cid}/appointments", json={
        "doctor_id": doc["id"], "patient_name": "Fuera de Hora",
        "scheduled_at": _proximo(MIE, 19, 0).strftime("%Y-%m-%dT%H:%M:%S")})
    assert r.status_code == 409
    assert r.json()["detail"]["horarios_libres"], "el panel no puede ofrecer nada"


def test_el_bot_ve_el_horario_de_las_franjas_y_no_el_texto_libre():
    """`Doctor.schedule` es texto libre que la clínica carga a mano y que nadie
    cruza contra las franjas.

    En producción el texto de un cardiólogo decía "Lun, Mié y Vie 14:00-19:00"
    y sus franjas decían 07:00 a 12:00 esos mismos días. El bot leyó el texto,
    le rechazó al paciente un viernes a la mañana que SÍ era horario del
    doctor, y le ofreció dos horarios de la tarde en los que no atiende. No
    inventó nada: le habíamos dado dos verdades contradictorias.
    """
    from app.chat import _execute_tool
    from app.models import Conversation

    # `_armar` le pone al doctor el texto libre "Lun a Vie 08:00-14:00"; las
    # franjas dicen otra cosa. Esa es exactamente la contradicción.
    cid, doc, _ = _armar("Clínica Dos Horarios",
                         [(LUN, "07:00", "12:00"), (MIE, "07:00", "12:00"),
                          (VIE, "07:00", "12:00")])

    db = SessionLocal()
    try:
        conv = Conversation(company_id=cid, contact_phone="595981000123", channel="test")
        db.add(conv)
        db.commit()
        r = _execute_tool("list_doctors", {}, db, db.get(Company, cid), conv)
    finally:
        db.close()

    ficha = next(d for d in r["doctors"] if d["id"] == doc)
    assert "14:00" not in ficha["schedule"], "le pasó el texto libre que contradice las franjas"
    assert "07:00 a 12:00" in ficha["schedule"]
    assert "lunes" in ficha["schedule"] and "viernes" in ficha["schedule"]
    # Y no se le manda el aviso de "sin confirmar" a un horario que SÍ está
    # cargado: eso lo haría dudar de un dato bueno.
    assert "schedule_sin_confirmar" not in ficha


def test_sin_franjas_el_texto_libre_va_marcado_como_sin_confirmar():
    """Hay clínicas operando solo con el texto a mano. No se les rompe el bot:
    se le dice al modelo que ese dato no está verificado."""
    from app.chat import _execute_tool
    from app.models import Conversation

    cid, doc, _ = _armar("Clínica Solo Texto", [], modo="libre")

    db = SessionLocal()
    try:
        conv = Conversation(company_id=cid, contact_phone="595981000124", channel="test")
        db.add(conv)
        db.commit()
        r = _execute_tool("list_doctors", {}, db, db.get(Company, cid), conv)
    finally:
        db.close()

    ficha = next(d for d in r["doctors"] if d["id"] == doc)
    assert ficha["schedule"] == "Lun a Vie 08:00-14:00"
    assert "no lo des como seguro" in ficha["schedule_sin_confirmar"]


def test_el_prompt_no_le_dicta_al_modelo_el_horario_escrito_a_mano():
    """La lista de doctores del system prompt es lo que el modelo lee ANTES de
    llamar a ninguna herramienta.

    Mientras dijo el texto libre, el bot contestaba con ese horario sin llegar
    a consultar la agenda: arreglar solo `list_doctors` no alcanzó, la
    respuesta equivocada salía igual.
    """
    from app.chat import _build_system_prompt
    from app.models import Agent

    cid, doc, _ = _armar("Clínica Prompt Horario",
                         [(LUN, "07:00", "12:00"), (VIE, "07:00", "12:00")])
    db = SessionLocal()
    try:
        agente = (
            db.query(Agent)
            .filter(Agent.company_id == cid, Agent.slug == "cx")
            .first()
        )
        prompt = _build_system_prompt(db, db.get(Company, cid), agente)
    finally:
        db.close()

    assert "Doctores del centro:" in prompt
    assert "07:00 a 12:00" in prompt
    assert "08:00-14:00" not in prompt, "le dictó el texto libre al modelo"


def test_check_agenda_devuelve_el_horario_de_las_franjas():
    """La herramienta que el modelo consulta para decidir tampoco puede
    devolver el texto que contradice a las franjas."""
    from app.chat import _execute_tool
    from app.models import Conversation

    cid, doc, _ = _armar("Clínica Check Agenda Horario",
                         [(LUN, "07:00", "12:00"), (VIE, "07:00", "12:00")])
    viernes = _proximo(VIE, 9)
    db = SessionLocal()
    try:
        conv = Conversation(company_id=cid, contact_phone="595981000125", channel="test")
        db.add(conv)
        db.commit()
        r = _execute_tool(
            "check_agenda", {"doctor_id": doc, "date": viernes.date().isoformat()},
            db, db.get(Company, cid), conv,
        )
    finally:
        db.close()
    assert "07:00 a 12:00" in r["work_schedule"]
    assert "08:00-14:00" not in r["work_schedule"]
