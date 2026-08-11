"""Convenios con seguros y entrega de recetas.

La regla que estas pruebas defienden: el bot RELATA lo que cargó el doctor.
No lo redacta, no lo resume y no lo interpreta. Un prompt que dice "no cambies
nada" es una intención; que el texto salga de `format` y se anexe después del
modelo es un hecho.
"""
import json

from tests.test_api import _create_company, client

from app import chat as chat_engine
from app.db import SessionLocal
from app.models import (
    Doctor,
    Insurer,
    Prescription,
    PrescriptionItem,
    Service,
    ServiceCoverage,
)


def _mock_llm(responses):
    calls = []

    async def fake_chat_raw(messages, **kwargs):
        calls.append({"messages": list(messages), "kwargs": kwargs})
        return responses[min(len(calls) - 1, len(responses) - 1)]

    return fake_chat_raw, calls


def _tool_call(name: str, args: dict, cid: str = "c1") -> dict:
    return {
        "content": None,
        "tool_calls": [{"id": cid, "function": {"name": name, "arguments": json.dumps(args)}}],
    }


def _sanatorio(nombre: str) -> dict:
    return _create_company(name=nombre, vertical="medical")


# --- Convenios con seguros ---


def _armar_convenio(cid: int, precio: int, cobertura: int, copago: int = 0) -> None:
    db = SessionLocal()
    try:
        db.add(Service(company_id=cid, name="Ecografía abdominal", category="Estudios",
                       price_gs=precio, duration_min=30,
                       prep="Ayuno de 6 horas y vejiga llena."))
        db.add(Insurer(company_id=cid, name="Seguro Ñandutí", plan="Plan Oro",
                       coverage_pct=cobertura, copay_gs=copago))
        db.commit()
    finally:
        db.close()


def test_cobertura_la_calcula_el_servidor_no_el_modelo(monkeypatch):
    """Un porcentaje mal calculado en un precio es una discusión en la caja."""
    company = _sanatorio("Sanatorio Convenio")
    cid = company["id"]
    _armar_convenio(cid, precio=200000, cobertura=70, copago=20000)

    fake, _ = _mock_llm([
        _tool_call("check_coverage", {"service": "ecografía abdominal", "insurer": "Ñandutí"}),
        {"content": "Con tu seguro te sale ₲ 80.000."},
    ])
    monkeypatch.setattr(chat_engine, "chat_raw", fake)
    resp = client.post(f"/api/companies/{cid}/chat",
                       json={"contact_phone": "+595981100001", "text": "tengo Ñandutí, cuánto sale la eco?"})
    result = resp.json()["actions"][0]["result"]

    assert result["covered"] is True
    assert result["coverage_pct"] == 70
    # 200.000 - 70% = 60.000, más 20.000 de copago = 80.000
    assert result["patient_pays"] == "₲ 80.000"
    assert result["prep"] == "Ayuno de 6 horas y vejiga llena."


def test_sin_convenio_se_dice_con_honestidad(monkeypatch):
    company = _sanatorio("Sanatorio Sin Convenio")
    cid = company["id"]
    _armar_convenio(cid, precio=200000, cobertura=70)

    fake, _ = _mock_llm([
        _tool_call("check_coverage", {"service": "ecografía abdominal", "insurer": "Prepaga Inexistente"}),
        {"content": "No tenemos convenio con esa prepaga."},
    ])
    monkeypatch.setattr(chat_engine, "chat_raw", fake)
    resp = client.post(f"/api/companies/{cid}/chat",
                       json={"contact_phone": "+595981100002", "text": "tengo Prepaga Inexistente"})
    result = resp.json()["actions"][0]["result"]

    assert result["covered"] is False
    assert "Seguro Ñandutí Plan Oro" in result["convenios_disponibles"]


def test_estudio_excluido_del_convenio_se_avisa_antes_de_la_caja(monkeypatch):
    company = _sanatorio("Sanatorio Excluido")
    cid = company["id"]
    _armar_convenio(cid, precio=200000, cobertura=80)

    db = SessionLocal()
    try:
        srv = db.query(Service).filter(Service.company_id == cid).one()
        ins = db.query(Insurer).filter(Insurer.company_id == cid).one()
        db.add(ServiceCoverage(company_id=cid, insurer_id=ins.id, service_id=srv.id, excluded=True))
        db.commit()
    finally:
        db.close()

    fake, _ = _mock_llm([
        _tool_call("check_coverage", {"service": "ecografía", "insurer": "Ñandutí"}),
        {"content": "Ese estudio no está cubierto."},
    ])
    monkeypatch.setattr(chat_engine, "chat_raw", fake)
    resp = client.post(f"/api/companies/{cid}/chat",
                       json={"contact_phone": "+595981100003", "text": "cubre mi seguro?"})
    result = resp.json()["actions"][0]["result"]

    assert result["covered"] is False
    assert result["patient_pays"] == "₲ 200.000"


# --- Recetas ---


def _cargar_receta(cid: int, telefono: str) -> None:
    db = SessionLocal()
    try:
        doc = Doctor(company_id=cid, name="Dra. Benítez", specialty="Clínica médica")
        db.add(doc)
        db.flush()
        receta = Prescription(
            company_id=cid, doctor_id=doc.id, patient_name="Marcos Duarte",
            patient_phone=telefono, diagnosis="Faringitis bacteriana",
            indications="Reposo 48 horas y volver si sigue la fiebre.",
        )
        db.add(receta)
        db.flush()
        db.add(PrescriptionItem(
            company_id=cid, prescription_id=receta.id, medication="Amoxicilina 500 mg",
            dose="1 comprimido", route="vía oral", frequency="cada 8 horas",
            every_hours=8, duration_days=7,
            instructions="Tomar con las comidas. Terminar el tratamiento completo.",
        ))
        db.commit()
    finally:
        db.close()


def test_la_receta_llega_palabra_por_palabra_aunque_el_modelo_la_parafrasee(monkeypatch):
    """La prueba central: aunque el modelo escriba una dosis distinta, la
    receta real se anexa igual y con los datos del doctor."""
    company = _sanatorio("Sanatorio Receta")
    cid = company["id"]
    telefono = "+595981200001"
    _cargar_receta(cid, telefono)

    fake, _ = _mock_llm([
        _tool_call("get_prescription", {}),
        # El modelo inventa una dosis distinta a propósito:
        {"content": "Te mando la receta: tomá amoxicilina 250 mg cada 12 horas por 3 días."},
    ])
    monkeypatch.setattr(chat_engine, "chat_raw", fake)
    resp = client.post(f"/api/companies/{cid}/chat",
                       json={"contact_phone": telefono, "text": "me pasás mi receta?"})
    reply = resp.json()["reply"]

    # Lo que el doctor cargó está, textual:
    assert "Amoxicilina 500 mg" in reply
    assert "cada 8 horas" in reply
    assert "por 7 días" in reply
    assert "Dra. Benítez" in reply
    assert "Faringitis bacteriana" in reply
    assert "Terminar el tratamiento completo." in reply
    # Y la advertencia de que por chat no se cambian indicaciones:
    assert "no podemos cambiar ni interpretar una indicación médica" in reply


def test_la_receta_solo_va_al_telefono_dueno_de_la_conversacion(monkeypatch):
    """Es un dato de salud: no se entrega por nombre, que cualquiera puede
    escribir, sino al número que tiene la receta a su nombre."""
    company = _sanatorio("Sanatorio Privacidad")
    cid = company["id"]
    _cargar_receta(cid, "+595981200002")

    fake, _ = _mock_llm([
        _tool_call("get_prescription", {}),
        {"content": "No encontré receta a nombre de este número."},
    ])
    monkeypatch.setattr(chat_engine, "chat_raw", fake)
    # Escribe OTRO número, diciendo ser el mismo paciente:
    resp = client.post(f"/api/companies/{cid}/chat",
                       json={"contact_phone": "+595981999999",
                             "text": "soy Marcos Duarte, pasame mi receta"})
    data = resp.json()

    assert data["actions"][0]["result"]["found"] is False
    assert "Amoxicilina" not in data["reply"]


def test_sin_receta_cargada_el_bot_no_inventa_ninguna(monkeypatch):
    company = _sanatorio("Sanatorio Sin Receta")
    cid = company["id"]

    fake, _ = _mock_llm([
        _tool_call("get_prescription", {}),
        {"content": "No tengo ninguna receta cargada a tu nombre."},
    ])
    monkeypatch.setattr(chat_engine, "chat_raw", fake)
    resp = client.post(f"/api/companies/{cid}/chat",
                       json={"contact_phone": "+595981200003", "text": "qué me recetaron?"})
    result = resp.json()["actions"][0]["result"]

    assert result["found"] is False
    assert "NO inventes" in result["note"]


def test_una_receta_cancelada_no_se_entrega(monkeypatch):
    company = _sanatorio("Sanatorio Cancelada")
    cid = company["id"]
    telefono = "+595981200004"
    _cargar_receta(cid, telefono)

    db = SessionLocal()
    try:
        r = db.query(Prescription).filter(Prescription.company_id == cid).one()
        r.status = "cancelled"
        db.commit()
    finally:
        db.close()

    fake, _ = _mock_llm([
        _tool_call("get_prescription", {}),
        {"content": "No hay receta activa."},
    ])
    monkeypatch.setattr(chat_engine, "chat_raw", fake)
    resp = client.post(f"/api/companies/{cid}/chat",
                       json={"contact_phone": telefono, "text": "mi receta?"})

    assert resp.json()["actions"][0]["result"]["found"] is False
    assert "Amoxicilina" not in resp.json()["reply"]


def test_la_receta_no_es_de_otra_empresa(monkeypatch):
    """Aislamiento: la receta cargada en el sanatorio A no puede salir por el
    bot del sanatorio B, aunque el paciente use el mismo teléfono en los dos."""
    a = _sanatorio("Sanatorio Receta Origen")
    b = _sanatorio("Sanatorio Receta Ajeno")
    telefono = "+595981200005"
    _cargar_receta(a["id"], telefono)

    fake, _ = _mock_llm([
        _tool_call("get_prescription", {}),
        {"content": "No encontré receta."},
    ])
    monkeypatch.setattr(chat_engine, "chat_raw", fake)
    resp = client.post(f"/api/companies/{b['id']}/chat",
                       json={"contact_phone": telefono, "text": "mi receta?"})

    assert resp.json()["actions"][0]["result"]["found"] is False
    assert "Amoxicilina" not in resp.json()["reply"]


def test_el_seguro_se_encuentra_aunque_se_escriba_sin_tildes(monkeypatch):
    """En WhatsApp nadie pone tildes. Observado en producción: el paciente
    escribió 'Seguro Nanduti Plan Oro' y el sistema le dijo que no había
    convenio... mientras se lo listaba entre los disponibles."""
    company = _sanatorio("Sanatorio Sin Tildes")
    cid = company["id"]
    _armar_convenio(cid, precio=180000, cobertura=80, copago=10000)

    fake, _ = _mock_llm([
        _tool_call("check_coverage", {"service": "ecografia abdominal", "insurer": "Seguro Nanduti Plan Oro"}),
        {"content": "Con tu seguro te sale ₲ 46.000."},
    ])
    monkeypatch.setattr(chat_engine, "chat_raw", fake)
    resp = client.post(f"/api/companies/{cid}/chat",
                       json={"contact_phone": "+595981100010", "text": "tengo Nanduti, cuanto sale la eco?"})
    result = resp.json()["actions"][0]["result"]

    assert result["covered"] is True, "el convenio existe: escribirlo sin tildes no puede negarlo"
    assert result["insurer"] == "Seguro Ñandutí Plan Oro"
    # 180.000 - 80% = 36.000, más 10.000 de copago
    assert result["patient_pays"] == "₲ 46.000"


def test_busqueda_de_estudios_ignora_tildes_y_acota_el_catalogo(monkeypatch):
    """Con ~300 estudios, devolverlos todos no le sirve al modelo."""
    company = _sanatorio("Sanatorio Búsqueda")
    cid = company["id"]
    db = SessionLocal()
    try:
        for n in range(40):
            db.add(Service(company_id=cid, name=f"Estudio de relleno {n}", category="Otros",
                           price_gs=50000, duration_min=15))
        db.add(Service(company_id=cid, name="Ecografía abdominal total", category="Ecografía",
                       specialty="Radiología", price_gs=180000, duration_min=30,
                       prep="Ayuno de 8 horas."))
        db.commit()
    finally:
        db.close()

    fake, _ = _mock_llm([
        _tool_call("list_services", {"query": "ecografia abdominal"}),
        {"content": "La ecografía abdominal sale ₲ 180.000."},
    ])
    monkeypatch.setattr(chat_engine, "chat_raw", fake)
    resp = client.post(f"/api/companies/{cid}/chat",
                       json={"contact_phone": "+595981100011", "text": "quiero una eco abdominal"})
    result = resp.json()["actions"][0]["result"]

    nombres = [s["name"] for s in result["services"]]
    assert "Ecografía abdominal total" in nombres
    assert len(result["services"]) <= 12, "el catálogo entero no entra en el contexto"
    assert result["services"][0]["preparacion"] == "Ayuno de 8 horas."


# --- Confirmación de la próxima visita ---


def _cita_pendiente(cid: int, telefono: str, dias: int = 5):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from app.config import TIMEZONE
    from app.models import Appointment

    db = SessionLocal()
    try:
        doc = Doctor(company_id=cid, name="Dr. Riveros", specialty="Cardiología")
        db.add(doc)
        db.flush()
        cuando = (datetime.now(ZoneInfo(TIMEZONE)).replace(tzinfo=None) + timedelta(days=dias)
                  ).replace(hour=10, minute=30, second=0, microsecond=0)
        appt = Appointment(company_id=cid, doctor_id=doc.id, patient_name="Rosa Ortiz",
                           patient_phone=telefono, scheduled_at=cuando, status="pending")
        db.add(appt)
        db.commit()
        db.refresh(appt)
        return appt.id
    finally:
        db.close()


def test_un_si_confirma_la_cita_sin_llamar_al_modelo(monkeypatch):
    """Que una cita quede confirmada no puede depender de que un LLM
    interprete bien un 'dale'. Además este turno sale gratis y sin espera."""
    from app.models import Appointment

    company = _sanatorio("Sanatorio Confirma")
    cid = company["id"]
    telefono = "+595981400001"
    appt_id = _cita_pendiente(cid, telefono)

    async def explota(*args, **kwargs):
        raise AssertionError("confirmar no debe llamar al modelo")

    monkeypatch.setattr(chat_engine, "chat_raw", explota)
    resp = client.post(f"/api/companies/{cid}/chat",
                       json={"contact_phone": telefono, "text": "dale"})
    data = resp.json()

    assert data["actions"][0]["tool"] == "confirm_appointment"
    assert "confirmada" in data["reply"]
    assert "Dr. Riveros" in data["reply"]

    db = SessionLocal()
    try:
        assert db.get(Appointment, appt_id).status == "confirmed"
    finally:
        db.close()


def test_un_si_con_peticion_NO_dispara_la_guardia(monkeypatch):
    """'sí, pero quiero cambiar la hora' no es una confirmación. Ante la duda,
    la guardia no actúa y lo maneja el bot."""
    from app.models import Appointment

    company = _sanatorio("Sanatorio Ambiguo")
    cid = company["id"]
    telefono = "+595981400002"
    appt_id = _cita_pendiente(cid, telefono)

    fake, _ = _mock_llm([{"content": "Claro, ¿qué horario te queda mejor?"}])
    monkeypatch.setattr(chat_engine, "chat_raw", fake)
    resp = client.post(f"/api/companies/{cid}/chat",
                       json={"contact_phone": telefono, "text": "si pero quiero cambiar la hora"})

    assert resp.json()["actions"] == []
    db = SessionLocal()
    try:
        assert db.get(Appointment, appt_id).status == "pending", "no se confirmó sola"
    finally:
        db.close()


def test_un_no_cancela_y_el_bot_ofrece_alternativas(monkeypatch):
    from app.models import Appointment

    company = _sanatorio("Sanatorio Rechaza")
    cid = company["id"]
    telefono = "+595981400003"
    appt_id = _cita_pendiente(cid, telefono)

    fake, calls = _mock_llm([{"content": "Sin problema, ¿te va el jueves a las 15:00?"}])
    monkeypatch.setattr(chat_engine, "chat_raw", fake)
    client.post(f"/api/companies/{cid}/chat",
                json={"contact_phone": telefono, "text": "no puedo"})

    db = SessionLocal()
    try:
        assert db.get(Appointment, appt_id).status == "cancelled"
    finally:
        db.close()
    # Y al bot se le avisa para que ofrezca alternativas en vez de repreguntar.
    assert "ya quedó cancelada" in calls[0]["messages"][0]["content"]


def test_la_confirmacion_no_alcanza_a_la_cita_de_otra_empresa(monkeypatch):
    from app.models import Appointment

    a = _sanatorio("Sanatorio Cita Propia")
    b = _sanatorio("Sanatorio Cita Ajena")
    telefono = "+595981400004"
    ajena = _cita_pendiente(a["id"], telefono)

    fake, _ = _mock_llm([{"content": "¿En qué te ayudo?"}])
    monkeypatch.setattr(chat_engine, "chat_raw", fake)
    client.post(f"/api/companies/{b['id']}/chat",
                json={"contact_phone": telefono, "text": "dale"})

    db = SessionLocal()
    try:
        assert db.get(Appointment, ajena).status == "pending"
    finally:
        db.close()


# --- API del panel: convenios y recetas ---


def test_convenio_se_carga_y_no_se_duplica():
    company = _sanatorio("Sanatorio API Convenio")
    cid = company["id"]
    alta = client.post(f"/api/companies/{cid}/insurers",
                       json={"name": "Seguro Ñandutí", "plan": "Plan Oro",
                             "coverage_pct": 80, "copay_gs": 15000})
    assert alta.status_code == 201
    repetido = client.post(f"/api/companies/{cid}/insurers",
                           json={"name": "Seguro Ñandutí", "plan": "Plan Oro"})
    assert repetido.status_code == 409

    listado = client.get(f"/api/companies/{cid}/insurers").json()
    assert listado[0]["coverage_pct"] == 80


def test_la_receta_exige_un_profesional_de_la_misma_empresa():
    """La clave foránea compuesta ya lo impide en el motor; acá se responde
    con un 422 legible en vez de un error de base."""
    a = _sanatorio("Sanatorio Receta Propia")
    b = _sanatorio("Sanatorio Receta Ajena")
    doc_b = client.post(f"/api/companies/{b['id']}/doctors",
                        json={"name": "Dr. Ajeno"}).json()

    resp = client.post(f"/api/companies/{a['id']}/prescriptions", json={
        "doctor_id": doc_b["id"], "patient_name": "Paciente",
        "patient_phone": "+595981600001",
        "items": [{"medication": "Ibuprofeno 400 mg", "dose": "1 comprimido"}],
    })
    assert resp.status_code == 422
    assert "no es de esta empresa" in resp.json()["detail"]


def test_la_receta_dice_por_que_no_hay_recordatorios():
    """Que la clínica crea que el paciente va a recibir avisos que nunca van
    a salir es peor que no ofrecer la función."""
    company = _sanatorio("Sanatorio Receta Sin Aviso")
    cid = company["id"]
    doc = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dra. Vera"}).json()

    resp = client.post(f"/api/companies/{cid}/prescriptions", json={
        "doctor_id": doc["id"], "patient_name": "Sin Contacto",
        "patient_phone": "+595981600002",
        "reminders_enabled": True, "consent_by": "Dra. Vera",
        "items": [{"medication": "Amoxicilina 500 mg", "dose": "1 comprimido",
                   "every_hours": 8, "duration_days": 5}],
    })
    assert resp.status_code == 201
    datos = resp.json()
    assert datos["recordatorios"]["programadas"] == 0
    assert "no escribió nunca" in datos["recordatorios"]["motivo"]


def test_editar_la_receta_sube_la_version_y_cancela_las_tomas_viejas():
    from app.models import Conversation

    company = _sanatorio("Sanatorio Receta Editada")
    cid = company["id"]
    doc = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dr. Edita"}).json()
    tel = "+595981600003"

    db = SessionLocal()
    try:  # el paciente escribió alguna vez: queda verificado
        db.add(Conversation(company_id=cid, contact_phone=tel, channel="whatsapp"))
        db.commit()
    finally:
        db.close()

    creada = client.post(f"/api/companies/{cid}/prescriptions", json={
        "doctor_id": doc["id"], "patient_name": "Con Contacto", "patient_phone": tel,
        "reminders_enabled": True, "consent_by": "Dr. Edita",
        "items": [{"medication": "Amoxicilina 500 mg", "dose": "1 comprimido",
                   "every_hours": 8, "duration_days": 3}],
    }).json()
    assert creada["recordatorios"]["programadas"] == 9
    assert creada["version"] == 1

    editada = client.patch(f"/api/companies/{cid}/prescriptions/{creada['id']}", json={
        "doctor_id": doc["id"], "patient_name": "Con Contacto", "patient_phone": tel,
        "reminders_enabled": True, "consent_by": "Dr. Edita",
        "items": [{"medication": "Amoxicilina 875 mg", "dose": "1 comprimido",
                   "every_hours": 12, "duration_days": 3}],
    }).json()
    assert editada["version"] == 2
    assert editada["tomas_canceladas"] == 9   # las viejas se dieron de baja
    assert editada["recordatorios"]["programadas"] == 6  # 12h × 3 días


def test_una_pauta_a_demanda_se_marca_como_tal():
    company = _sanatorio("Sanatorio A Demanda API")
    cid = company["id"]
    doc = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dr. Dolor"}).json()
    creada = client.post(f"/api/companies/{cid}/prescriptions", json={
        "doctor_id": doc["id"], "patient_name": "Paciente", "patient_phone": "+595981600004",
        "items": [{"medication": "Paracetamol 500 mg", "dose": "1 comprimido",
                   "frequency": "si tenés dolor", "every_hours": 0}],
    }).json()
    assert creada["items"][0]["a_demanda"] is True


def test_cancelar_el_tratamiento_apaga_los_recordatorios():
    company = _sanatorio("Sanatorio Cancela API")
    cid = company["id"]
    doc = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dr. Stop"}).json()
    creada = client.post(f"/api/companies/{cid}/prescriptions", json={
        "doctor_id": doc["id"], "patient_name": "Paciente", "patient_phone": "+595981600005",
        "items": [{"medication": "Ibuprofeno 400 mg", "dose": "1 comprimido"}],
    }).json()
    resp = client.post(f"/api/companies/{cid}/prescriptions/{creada['id']}/cancel")
    assert resp.status_code == 200

    listado = client.get(f"/api/companies/{cid}/prescriptions").json()
    assert listado[0]["status"] == "cancelled"
    assert listado[0]["reminders_enabled"] is False


def test_la_receta_NO_queda_guardada_en_el_historial(monkeypatch):
    """Privacidad y contexto, de un solo cambio.

    `messages.body` alimenta la auditoría diaria del Guard, que manda las
    conversaciones a un LLM externo: persistir el bloque mandaría nombre,
    diagnóstico y dosis del paciente fuera del país todos los días. Y el
    historial del turno siguiente se arma con esa misma columna, así que la
    receta volvería al contexto del modelo y podría parafrasearla —justo lo
    que la entrega verbatim evita.
    """
    from app.models import AgentRun, Message

    company = _sanatorio("Sanatorio No Persiste")
    cid = company["id"]
    telefono = "+595981200099"
    _cargar_receta(cid, telefono)

    fake, _ = _mock_llm([
        _tool_call("get_prescription", {}),
        {"content": "Te la mando."},
    ])
    monkeypatch.setattr(chat_engine, "chat_raw", fake)
    resp = client.post(f"/api/companies/{cid}/chat",
                       json={"contact_phone": telefono, "text": "mi receta?"})

    # Al paciente SÍ le llega, textual.
    assert "Amoxicilina 500 mg" in resp.json()["reply"]

    db = SessionLocal()
    try:
        salientes = (
            db.query(Message)
            .filter(Message.company_id == cid, Message.direction == "out")
            .all()
        )
        assert salientes, "tiene que haber quedado el mensaje de salida"
        for m in salientes:
            assert "Amoxicilina" not in m.body, "la medicación quedó guardada en el historial"
            assert "Faringitis" not in m.body, "el diagnóstico quedó guardado en el historial"
        assert any("receta" in m.body for m in salientes), "debe quedar la marca de que se envió"

        for run in db.query(AgentRun).filter(AgentRun.company_id == cid).all():
            assert "Amoxicilina" not in (run.answer or "")
    finally:
        db.close()


def test_la_receta_no_vuelve_al_contexto_del_modelo(monkeypatch):
    """El turno siguiente no debe llevarle la receta al modelo."""
    company = _sanatorio("Sanatorio Contexto Limpio")
    cid = company["id"]
    telefono = "+595981200098"
    _cargar_receta(cid, telefono)

    fake, _ = _mock_llm([
        _tool_call("get_prescription", {}),
        {"content": "Te la mando."},
    ])
    monkeypatch.setattr(chat_engine, "chat_raw", fake)
    client.post(f"/api/companies/{cid}/chat",
                json={"contact_phone": telefono, "text": "mi receta?"})

    fake2, calls2 = _mock_llm([{"content": "¿Algo más?"}])
    monkeypatch.setattr(chat_engine, "chat_raw", fake2)
    client.post(f"/api/companies/{cid}/chat",
                json={"contact_phone": telefono, "text": "gracias"})

    enviado = json.dumps(calls2[0]["messages"], ensure_ascii=False)
    assert "Amoxicilina" not in enviado, "la receta volvió al contexto del modelo"
