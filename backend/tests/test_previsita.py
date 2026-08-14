"""El resumen que recibe el PROFESIONAL antes de atender.

Lo que existía era una lista de horas y nombres: le decía al doctor a quién
iba a ver, no lo que necesita saber antes de que el paciente entre —si ya
vino, qué se le recetó la vez pasada, qué se le va a hacer hoy—.

Son datos clínicos, así que las pruebas cuidan dos cosas por igual: que la
información esté, y que no llegue a quien no corresponde.
"""
from datetime import date, datetime, timedelta

import pytest

from tests.test_api import _create_company, client

PORTAL = ["booking", "healthcare", "practitioner"]
"""El resumen pre-visita es del bloque 4, que se vende aparte: una clínica
que solo compró la agenda recibe 402 en estos endpoints, no el resumen."""


from app import previsita
from app.db import SessionLocal
from app.models import (
    Appointment, Company, Doctor, Prescription, PrescriptionItem, Service,
)


def _doctor(cid, nombre="Dra. Agenda Previa", telefono="+595 981 555000"):
    return client.post(f"/api/companies/{cid}/doctors",
                       json={"name": nombre, "phone": telefono}).json()


def _cita(cid, doctor_id, paciente, telefono, cuando, **kw):
    db = SessionLocal()
    try:
        a = Appointment(company_id=cid, doctor_id=doctor_id, patient_name=paciente,
                        patient_phone=telefono, scheduled_at=cuando,
                        status=kw.pop("status", "confirmed"), **kw)
        db.add(a)
        db.commit()
        db.refresh(a)
        return a
    finally:
        db.close()


def _receta(cid, doctor_id, paciente, telefono, cuando, diagnostico, medicacion):
    db = SessionLocal()
    try:
        r = Prescription(company_id=cid, doctor_id=doctor_id, patient_name=paciente,
                         patient_phone=telefono, diagnosis=diagnostico, issued_at=cuando)
        db.add(r)
        db.flush()
        for med, dosis, frec in medicacion:
            db.add(PrescriptionItem(company_id=cid, prescription_id=r.id,
                                    medication=med, dose=dosis, frequency=frec))
        db.commit()
        return r.id
    finally:
        db.close()


def _armar(cid, doctor_id, dia):
    db = SessionLocal()
    try:
        return previsita.armar(db, db.get(Company, cid), db.get(Doctor, doctor_id), dia)
    finally:
        db.close()


MANANA = (datetime.now() + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)


# --- Lo que el doctor necesita saber ---


def test_distingue_al_paciente_nuevo_del_que_ya_vino():
    """No se atiende igual a alguien que viene por primera vez que a alguien
    que ya vino seis veces. Es el dato más importante del resumen."""
    company = _create_company(name="Clínica Primera Vez")
    cid = company["id"]
    doc = _doctor(cid)

    _cita(cid, doc["id"], "Marco Garcete", "595981111222", MANANA)
    _cita(cid, doc["id"], "Ana Nueva", "595981333444", MANANA + timedelta(hours=1))
    # Marco ya vino dos veces antes.
    _cita(cid, doc["id"], "Marco Garcete", "595981111222", MANANA - timedelta(days=60))
    _cita(cid, doc["id"], "Marco Garcete", "595981111222", MANANA - timedelta(days=200))

    r = _armar(cid, doc["id"], MANANA.date())
    por_nombre = {f["paciente"]: f for f in r["pacientes"]}

    assert por_nombre["Ana Nueva"]["primera_vez"] is True
    assert por_nombre["Marco Garcete"]["primera_vez"] is False
    assert por_nombre["Marco Garcete"]["visitas_previas"] == 2
    assert "Última:" in r["texto"] or "Ya vino" in r["texto"]
    assert r["primera_vez"] == 1


def test_el_historial_se_encuentra_aunque_el_telefono_este_escrito_distinto():
    """El mismo número se guarda como "+595 981 111-222" o "0981111222". Sin
    comparar por dígitos se perdía la mitad del historial."""
    company = _create_company(name="Clínica Teléfonos")
    cid = company["id"]
    doc = _doctor(cid)
    _cita(cid, doc["id"], "Marco", "+595 981 111-222", MANANA)
    _cita(cid, doc["id"], "Marco", "595981111222", MANANA - timedelta(days=30))

    r = _armar(cid, doc["id"], MANANA.date())
    assert r["pacientes"][0]["primera_vez"] is False


def test_trae_la_ultima_receta_con_la_medicacion():
    """Lo que el doctor quiere ver antes de recetar de nuevo."""
    company = _create_company(name="Clínica Receta Previa")
    cid = company["id"]
    doc = _doctor(cid)
    _cita(cid, doc["id"], "Marco Garcete", "595981111222", MANANA)
    _cita(cid, doc["id"], "Marco Garcete", "595981111222", MANANA - timedelta(days=45))
    _receta(cid, doc["id"], "Marco Garcete", "595981111222",
            datetime.now() - timedelta(days=45), "Hipertensión arterial",
            [("Enalapril", "10 mg", "cada 12 horas"), ("Aspirina", "100 mg", "1 por día")])

    r = _armar(cid, doc["id"], MANANA.date())
    ficha = r["pacientes"][0]
    assert ficha["ultima_receta"]["diagnostico"] == "Hipertensión arterial"
    assert any("Enalapril" in m for m in ficha["ultima_receta"]["medicacion"])
    assert "Enalapril 10 mg" in r["texto"]
    assert "Hipertensión arterial" in r["texto"]


def test_avisa_la_preparacion_del_estudio():
    """Si el paciente viene en ayunas o no, el doctor lo tiene que saber
    antes, no cuando ya está en el consultorio."""
    company = _create_company(name="Clínica Preparación")
    cid = company["id"]
    doc = _doctor(cid)
    db = SessionLocal()
    try:
        s = Service(company_id=cid, name="Ecografía abdominal", duration_min=45,
                    prep="Ayuno de 8 horas.")
        db.add(s)
        db.commit()
        sid = s.id
    finally:
        db.close()
    _cita(cid, doc["id"], "Paciente Eco", "595981777888", MANANA, service_id=sid,
          duration_min=45)

    r = _armar(cid, doc["id"], MANANA.date())
    assert r["pacientes"][0]["servicio"] == "Ecografía abdominal"
    assert r["pacientes"][0]["preparacion_requerida"] == "Ayuno de 8 horas."
    assert "Ayuno de 8 horas" in r["texto"]


def test_marca_los_turnos_que_el_paciente_no_confirmo():
    company = _create_company(name="Clínica Sin Confirmar")
    cid = company["id"]
    doc = _doctor(cid)
    _cita(cid, doc["id"], "No Confirmó", "595981999000", MANANA, status="pending")
    r = _armar(cid, doc["id"], MANANA.date())
    assert r["pacientes"][0]["sin_confirmar"] is True
    assert r["sin_confirmar"] == 1
    assert "No confirmó" in r["texto"]


def test_las_citas_canceladas_no_aparecen():
    company = _create_company(name="Clínica Canceladas")
    cid = company["id"]
    doc = _doctor(cid)
    _cita(cid, doc["id"], "Se Canceló", "595981000111", MANANA, status="cancelled")
    r = _armar(cid, doc["id"], MANANA.date())
    assert r["total"] == 0


# --- Quién ve qué ---


def test_cada_doctor_ve_solo_a_sus_pacientes():
    """Regresión de un bug del prototipo. Acá además son datos clínicos."""
    company = _create_company(name="Clínica Dos Doctores")
    cid = company["id"]
    doc_a = _doctor(cid, "Dra. A")
    doc_b = _doctor(cid, "Dr. B", "+595 981 555111")
    _cita(cid, doc_a["id"], "Paciente De A", "595981222333", MANANA)
    _cita(cid, doc_b["id"], "Paciente De B", "595981444555", MANANA)

    r = _armar(cid, doc_a["id"], MANANA.date())
    assert [f["paciente"] for f in r["pacientes"]] == ["Paciente De A"]
    assert "Paciente De B" not in r["texto"]


def test_el_historial_no_cruza_de_empresa():
    """Dos clínicas pueden tener al mismo paciente; sus historiales no se
    mezclan aunque compartan el número."""
    a = _create_company(name="Clínica Aislada Uno")
    b = _create_company(name="Clínica Aislada Dos")
    doc_a = _doctor(a["id"], "Dra. Uno")
    doc_b = _doctor(b["id"], "Dr. Dos", "+595 981 555222")
    telefono = "595981666777"

    _cita(a["id"], doc_a["id"], "Marco", telefono, MANANA)
    # En la OTRA clínica ya vino y tiene receta.
    _cita(b["id"], doc_b["id"], "Marco", telefono, MANANA - timedelta(days=20))
    _receta(b["id"], doc_b["id"], "Marco", telefono,
            datetime.now() - timedelta(days=20), "Secreto de la otra clínica",
            [("Medicamento Ajeno", "1 mg", "")])

    r = _armar(a["id"], doc_a["id"], MANANA.date())
    ficha = r["pacientes"][0]
    assert ficha["primera_vez"] is True, "vio el historial de otra empresa"
    assert "ultima_receta" not in ficha
    assert "Secreto de la otra clínica" not in r["texto"]
    assert "Medicamento Ajeno" not in r["texto"]


def test_la_receta_de_otro_colega_del_centro_se_ve_con_su_nombre():
    """Dentro de la misma institución es dato clínico legítimo, pero el doctor
    tiene que saber que no la escribió él."""
    company = _create_company(name="Clínica Colegas")
    cid = company["id"]
    doc_a = _doctor(cid, "Dra. Que Atiende")
    doc_b = _doctor(cid, "Dr. Que Recetó", "+595 981 555333")
    _cita(cid, doc_a["id"], "Marco", "595981888999", MANANA)
    _receta(cid, doc_b["id"], "Marco", "595981888999",
            datetime.now() - timedelta(days=10), "Faringitis",
            [("Amoxicilina", "500 mg", "cada 8 horas")])

    r = _armar(cid, doc_a["id"], MANANA.date())
    assert r["pacientes"][0]["ultima_receta"]["por"] == "Dr. Que Recetó"
    assert "Dr. Que Recetó" in r["texto"]


# --- El envío ---


def test_no_se_manda_a_un_doctor_sin_telefono():
    """Son datos clínicos: sin un número cargado no van a ningún lado."""
    company = _create_company(name="Clínica Sin Teléfono", packs=PORTAL)
    cid = company["id"]
    doc = client.post(f"/api/companies/{cid}/doctors",
                      json={"name": "Dr. Sin Tel"}).json()
    _cita(cid, doc["id"], "Alguien", "595981111000", MANANA)

    r = client.post(f"/api/companies/{cid}/doctors/{doc['id']}/pre-visit/send", json={})
    assert r.status_code == 422
    assert "no tiene teléfono cargado" in r.json()["detail"]


def test_sin_pacientes_no_se_manda_nada():
    """Un mensaje diario que casi siempre dice "no tenés nada" se deja de leer."""
    company = _create_company(name="Clínica Día Libre", packs=PORTAL)
    cid = company["id"]
    doc = _doctor(cid)
    r = client.post(f"/api/companies/{cid}/doctors/{doc['id']}/pre-visit/send",
                    json={"on_date": MANANA.date().isoformat()})
    assert r.json()["enviado"] is False


def test_cinco_pacientes_no_generan_cinco_mensajes():
    """El dedup es por (doctor, día): agendar el quinto turno del martes no
    puede mandarle un quinto resumen."""
    from app import job_handlers, jobs
    from app.models import Job

    company = _create_company(name="Clínica Dedup", packs=PORTAL)
    cid = company["id"]
    doc = _doctor(cid)
    db = SessionLocal()
    try:
        db.query(Job).filter(Job.company_id == cid).delete()
        db.commit()
        doctor = db.get(Doctor, doc["id"])
        for i in range(5):
            job_handlers.schedule_previsita(db, doctor, MANANA.date())
        pendientes = db.query(Job).filter(
            Job.company_id == cid, Job.kind == job_handlers.PREVISITA_KIND).count()
    finally:
        db.close()
    assert pendientes == 1


def test_el_resumen_se_programa_al_agendar():
    company = _create_company(name="Clínica Programa Solo", packs=PORTAL)
    cid = company["id"]
    doc = _doctor(cid)
    from app import job_handlers
    from app.models import Job

    db = SessionLocal()
    try:
        db.query(Job).filter(Job.company_id == cid).delete()
        db.commit()
    finally:
        db.close()

    client.post(f"/api/companies/{cid}/appointments", json={
        "doctor_id": doc["id"], "patient_name": "Marco",
        "scheduled_at": (datetime.now() + timedelta(days=3)).replace(
            hour=10, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")})

    db = SessionLocal()
    try:
        tipos = {j.kind for j in db.query(Job).filter(Job.company_id == cid).all()}
    finally:
        db.close()
    assert job_handlers.PREVISITA_KIND in tipos
    assert job_handlers.REMINDER_KIND in tipos


def test_el_resumen_sale_la_noche_anterior():
    from app import job_handlers
    from app.models import Job

    company = _create_company(name="Clínica Noche Anterior", packs=PORTAL)
    cid = company["id"]
    doc = _doctor(cid)
    dia = (datetime.now() + timedelta(days=5)).date()
    db = SessionLocal()
    try:
        db.query(Job).filter(Job.company_id == cid).delete()
        db.commit()
        job_handlers.schedule_previsita(db, db.get(Doctor, doc["id"]), dia)
        job = db.query(Job).filter(Job.company_id == cid,
                                   Job.kind == job_handlers.PREVISITA_KIND).one()
        # Guardado en UTC, como todo lo de la cola: 20:00 de Paraguay.
        esperado = job_handlers.local_a_utc(
            datetime(dia.year, dia.month, dia.day, job_handlers.PREVISITA_HORA)
            - timedelta(days=1))
        assert job.run_at == esperado
    finally:
        db.close()


# --- El resumen no lo escribe un modelo ---


def test_el_texto_se_arma_en_el_servidor_sin_llm():
    """Un resumen "redactado" por un modelo puede afirmar algo que el doctor
    nunca escribió. Igual que las recetas: esto se relata, no se genera."""
    import pathlib

    fuente = pathlib.Path(previsita.__file__).read_text(encoding="utf-8")
    cuerpo = fuente.split('"""', 2)[-1]
    for prohibido in ("chat_raw", "complete(", "from .llm", "model_for"):
        assert prohibido not in cuerpo, f"el resumen pasa por el modelo: {prohibido}"


def test_el_endpoint_devuelve_el_resumen_completo():
    company = _create_company(name="Clínica Endpoint Previsita", packs=PORTAL)
    cid = company["id"]
    doc = _doctor(cid)
    _cita(cid, doc["id"], "Marco Garcete", "595981111222", MANANA)

    r = client.get(f"/api/companies/{cid}/doctors/{doc['id']}/pre-visit",
                   params={"on_date": MANANA.date().isoformat()})
    assert r.status_code == 200
    datos = r.json()
    assert datos["total"] == 1
    assert datos["pacientes"][0]["paciente"] == "Marco Garcete"
    assert doc["name"] in datos["texto"]


def test_el_resumen_de_otra_empresa_da_404():
    a = _create_company(name="Clínica Previsita A", packs=PORTAL)
    b = _create_company(name="Clínica Previsita B", packs=PORTAL)
    doc_a = _doctor(a["id"], "Dra. A")
    r = client.get(f"/api/companies/{b['id']}/doctors/{doc_a['id']}/pre-visit")
    assert r.status_code == 404


@pytest.mark.parametrize("visitas,esperado", [(1, "1 vez."), (2, "2 veces."), (5, "5 veces.")])
def test_el_plural_de_vez_es_veces(visitas, esperado):
    """Decía "2 vezces". Lo lee un médico, no un programador."""
    company = _create_company(name=f"Clínica Plural {visitas}")
    cid = company["id"]
    doc = _doctor(cid)
    _cita(cid, doc["id"], "Marco", "595981222111", MANANA)
    for i in range(visitas):
        _cita(cid, doc["id"], "Marco", "595981222111",
              MANANA - timedelta(days=30 * (i + 1)))

    r = _armar(cid, doc["id"], MANANA.date())
    assert esperado in r["texto"]
    assert "vezces" not in r["texto"]


# --- Lo que encontró la revisión adversarial ---


def test_no_se_muestra_el_historial_de_otra_persona_con_el_mismo_telefono():
    """EL fallo crítico: una madre agenda con su celular para ella y para el
    hijo. Sin comparar el nombre, el pediatra recibía el diagnóstico
    psiquiátrico de la madre atribuido al chico: dato de salud de alguien que
    ese profesional no atiende, ya fuera del sistema y sin poder retirarlo."""
    company = _create_company(name="Clínica Celular Compartido")
    cid = company["id"]
    doc = _doctor(cid)
    celular = "595981123456"

    _cita(cid, doc["id"], "Juan Pérez", celular, MANANA)          # el hijo
    _cita(cid, doc["id"], "María Benítez", celular,               # la madre
          MANANA - timedelta(days=40))
    _receta(cid, doc["id"], "María Benítez", celular,
            datetime.now() - timedelta(days=40), "Trastorno bipolar",
            [("Litio", "300 mg", "cada 12 horas")])

    r = _armar(cid, doc["id"], MANANA.date())
    ficha = r["pacientes"][0]
    assert ficha["paciente"] == "Juan Pérez"
    assert ficha["primera_vez"] is True, "le contó las visitas de otra persona"
    assert "ultima_receta" not in ficha
    for ajeno in ("Trastorno bipolar", "Litio", "María Benítez"):
        assert ajeno not in r["texto"], f"filtró dato de otra persona: {ajeno}"
    # Se avisa que el número está compartido, sin decir de quién.
    assert ficha["numero_compartido"] is True
    assert "otra persona" in r["texto"]


def test_el_mismo_paciente_con_el_nombre_algo_distinto_si_se_reconoce():
    """"Marco Garcete" y "Marco Antonio Garcete" son la misma persona: con un
    filtro estricto se perdería el historial de casi todos."""
    company = _create_company(name="Clínica Nombre Parcial")
    cid = company["id"]
    doc = _doctor(cid)
    tel = "595981333222"
    _cita(cid, doc["id"], "Marco Garcete", tel, MANANA)
    _cita(cid, doc["id"], "Marco Antonio Garcete", tel, MANANA - timedelta(days=30))

    r = _armar(cid, doc["id"], MANANA.date())
    assert r["pacientes"][0]["primera_vez"] is False
    assert r["pacientes"][0]["numero_compartido"] is False


def test_el_historial_no_se_pierde_en_una_clinica_con_volumen():
    """El límite se aplicaba ANTES de filtrar por teléfono: traía las últimas
    80 citas de TODA la empresa. Una clínica con 30 pacientes por día lo
    agotaba en tres días y anunciaba "primera vez" de quien ya había venido.
    Cuanto más grande el cliente, más mentía."""
    company = _create_company(name="Clínica Con Volumen")
    cid = company["id"]
    doc = _doctor(cid)
    tel = "595981777333"

    _cita(cid, doc["id"], "Marco Garcete", tel, MANANA - timedelta(days=40))
    for i in range(120):  # 120 citas de OTROS, todas más recientes
        _cita(cid, doc["id"], f"Otro Paciente {i}", f"5959812{i:05d}",
              MANANA - timedelta(days=2, minutes=i))
    _cita(cid, doc["id"], "Marco Garcete", tel, MANANA)

    r = _armar(cid, doc["id"], MANANA.date())
    ficha = next(f for f in r["pacientes"] if f["paciente"] == "Marco Garcete")
    assert ficha["primera_vez"] is False, "el volumen de la clínica borró el historial"
    assert ficha["visitas_previas"] == 1


def test_la_receta_no_se_pierde_en_una_clinica_con_volumen():
    """Mismo bug en las recetas, y peor: no tenían ventana temporal, así que
    cualquier clínica con 40 recetas emitidas perdía todo lo anterior."""
    company = _create_company(name="Clínica Muchas Recetas")
    cid = company["id"]
    doc = _doctor(cid)
    tel = "595981444555"
    _cita(cid, doc["id"], "Marco Garcete", tel, MANANA)
    _cita(cid, doc["id"], "Marco Garcete", tel, MANANA - timedelta(days=30))
    _receta(cid, doc["id"], "Marco Garcete", tel,
            datetime.now() - timedelta(days=30), "Hipertensión arterial",
            [("Enalapril", "10 mg", "cada 12 horas")])
    for i in range(60):  # 60 recetas de otros, todas más nuevas
        _receta(cid, doc["id"], f"Otro {i}", f"5959813{i:05d}",
                datetime.now() - timedelta(days=1, minutes=i), "Gripe",
                [("Paracetamol", "500 mg", "")])

    r = _armar(cid, doc["id"], MANANA.date())
    ficha = r["pacientes"][0]
    assert ficha.get("ultima_receta"), "el volumen de la clínica ocultó la receta"
    assert ficha["ultima_receta"]["diagnostico"] == "Hipertensión arterial"


def test_el_prefijo_nacional_y_el_internacional_son_el_mismo_numero():
    """El bot guarda "595981..." (el wa_id de Meta) y recepción tipea
    "0981...". Sin sacar el prefijo son personas distintas y el historial se
    parte al medio."""
    company = _create_company(name="Clínica Prefijos")
    cid = company["id"]
    doc = _doctor(cid)
    _cita(cid, doc["id"], "Marco Garcete", "595981111222", MANANA)
    _cita(cid, doc["id"], "Marco Garcete", "0981 111-222", MANANA - timedelta(days=20))

    r = _armar(cid, doc["id"], MANANA.date())
    assert r["pacientes"][0]["primera_vez"] is False


def test_una_falta_no_es_una_visita():
    """"no_show" dice que el paciente NO se presentó. Contarla como consulta
    le hace creer al doctor que hubo una visita que nunca ocurrió."""
    company = _create_company(name="Clínica Faltas")
    cid = company["id"]
    doc = _doctor(cid)
    tel = "595981888444"
    _cita(cid, doc["id"], "Marco Garcete", tel, MANANA)
    for dias in (20, 50):
        _cita(cid, doc["id"], "Marco Garcete", tel, MANANA - timedelta(days=dias),
              status="no_show")

    r = _armar(cid, doc["id"], MANANA.date())
    ficha = r["pacientes"][0]
    assert ficha["visitas_previas"] == 0
    assert ficha["primera_vez"] is True
    assert ficha["faltas_previas"] == 2
    # Y es justo lo que el doctor quiere saber.
    assert "Faltó 2 veces" in r["texto"]
    assert "Ya vino" not in r["texto"]


def test_un_turno_del_mismo_dia_no_cuenta_como_visita_pasada():
    """El resumen sale la noche ANTERIOR: ninguna cita del día siguiente
    ocurrió todavía. Un paciente con turno a las 09:00 y otro más tarde
    aparecía en el segundo como "ya vino, última visita: mañana"."""
    company = _create_company(name="Clínica Mismo Día")
    cid = company["id"]
    doc = _doctor(cid)
    tel = "595981555777"
    _cita(cid, doc["id"], "Marco Garcete", tel, MANANA)
    _cita(cid, doc["id"], "Marco Garcete", tel, MANANA + timedelta(hours=6))

    r = _armar(cid, doc["id"], MANANA.date())
    assert all(f["primera_vez"] for f in r["pacientes"]), \
        "una cita futura contó como visita pasada"
    assert "Ya vino" not in r["texto"]


def test_el_servicio_de_otra_empresa_no_entra_en_el_resumen():
    a = _create_company(name="Clínica Servicio Propio")
    b = _create_company(name="Clínica Servicio Ajeno")
    doc = _doctor(a["id"])
    db = SessionLocal()
    try:
        ajeno = Service(company_id=b["id"], name="Estudio Secreto Ajeno",
                        prep="Preparación de otra clínica")
        db.add(ajeno)
        db.commit()
        sid = ajeno.id
    finally:
        db.close()
    _cita(a["id"], doc["id"], "Marco", "595981666222", MANANA, service_id=sid)

    r = _armar(a["id"], doc["id"], MANANA.date())
    assert "Estudio Secreto Ajeno" not in r["texto"]
    assert r["pacientes"][0]["servicio"] == ""


def test_el_resumen_se_programa_aunque_el_turno_sea_para_hoy():
    """El early return del recordatorio T-24h cortaba antes de programar el
    resumen. Un turno tomado a menos de 24 horas dejaba al doctor sin aviso,
    justo cuando más falta hace porque no tuvo tiempo de mirar la agenda."""
    from app import job_handlers
    from app.models import Job

    company = _create_company(name="Clínica Turno Urgente")
    cid = company["id"]
    doc = _doctor(cid)
    db = SessionLocal()
    try:
        db.query(Job).filter(Job.company_id == cid).delete()
        db.commit()
        doctor = db.get(Doctor, doc["id"])
        # Turno mañana temprano, agendado hoy a última hora: el recordatorio
        # T-24h ya no entra, el resumen del profesional sí.
        job_handlers.schedule_appointment_reminder(
            db, Appointment(company_id=cid, doctor_id=doc["id"],
                            patient_name="Urgente", patient_phone="595981000999",
                            scheduled_at=datetime.now() + timedelta(hours=3),
                            status="pending"))
        db.commit()
        tipos = {j.kind for j in db.query(Job).filter(Job.company_id == cid).all()}
    finally:
        db.close()
    assert job_handlers.REMINDER_KIND not in tipos, "la cita es en 3 horas"
    # El resumen tampoco: su horario de salida (20:00 de ayer) ya pasó. Lo que
    # importa es que se INTENTE, no que el early return lo saltee.
    import inspect
    fuente = inspect.getsource(job_handlers.schedule_appointment_reminder)
    antes_del_return = fuente.split("if run_at <= now")[0]
    assert "schedule_previsita" in antes_del_return, \
        "el resumen quedó detrás del early return del recordatorio"
