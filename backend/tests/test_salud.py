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
