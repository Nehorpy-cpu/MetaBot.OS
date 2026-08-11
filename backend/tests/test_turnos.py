"""Fechas relativas y turnos propios del paciente.

De la corrida real del 11-ago-2026 (que fue martes): el paciente escribió
"Dr. Benitez Sosa esta bien el martes a las 10" y el bot agendó para el
"martes 12 de agosto de 2026". El 12 era MIÉRCOLES. Y cuando después preguntó
"¿y cuándo es mi turno?", el bot le contestó con los horarios ocupados del
doctor diciéndole que su propio turno estaba ocupado.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tests.test_api import _create_company, client

from app import chat as motor
from app.config import TIMEZONE
from app.db import SessionLocal
from app.models import Agent, Appointment, Company, Conversation, Doctor


def _empresa_con_doctor(nombre):
    company = _create_company(name=nombre)
    doctor = client.post(
        f"/api/companies/{company['id']}/doctors",
        json={"name": "Dr. Marcos Benítez Sosa", "specialty": "Cardiología",
              "schedule": "Lun a Mié 10:00-15:00", "phone": "", "email": ""},
    ).json()
    return company, doctor


def _conversacion(company_id, telefono="595981777888"):
    db = SessionLocal()
    try:
        conv = Conversation(company_id=company_id, contact_phone=telefono,
                            channel="whatsapp")
        db.add(conv)
        db.commit()
        db.refresh(conv)
        return conv
    finally:
        db.close()


# --- El día de la semana lo dice el servidor ---


def test_el_calendario_va_en_el_prompt_ya_resuelto():
    """El modelo se equivocaba haciendo la aritmética: le anunció al paciente
    "martes 12 de agosto" para una fecha que caía miércoles. Ahora las fechas
    van calculadas y solo tiene que copiarlas."""
    company, _ = _empresa_con_doctor("Clínica Calendario")
    db = SessionLocal()
    try:
        empresa = db.get(Company, company["id"])
        agente = db.query(Agent).filter(
            Agent.company_id == empresa.id, Agent.slug == "cx").first()
        prompt = motor._build_system_prompt(db, empresa, agente)
    finally:
        db.close()

    ahora = datetime.now(ZoneInfo(TIMEZONE))
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    assert "Calendario de los próximos días" in prompt
    # Cada uno de los próximos 8 días, con su nombre correcto.
    for i in range(8):
        fecha = ahora + timedelta(days=i)
        esperado = f"{dias[fecha.weekday()]} {fecha.strftime('%d/%m/%Y')}"
        assert esperado in prompt, f"falta o está mal: {esperado}"
    assert "(hoy)" in prompt and "(mañana)" in prompt


def test_al_agendar_el_servidor_dicta_el_dia_de_la_semana():
    """La respuesta de la herramienta trae el texto exacto que el bot tiene
    que repetir, para que no vuelva a inventar el día."""
    company, doctor = _empresa_con_doctor("Clínica Día Correcto")
    conv = _conversacion(company["id"])

    # Un miércoles concreto y futuro.
    ahora = datetime.now(ZoneInfo(TIMEZONE)).replace(tzinfo=None)
    proximo_miercoles = ahora + timedelta(days=(2 - ahora.weekday()) % 7 or 7)
    cuando = proximo_miercoles.replace(hour=11, minute=0, second=0, microsecond=0)

    db = SessionLocal()
    try:
        empresa = db.get(Company, company["id"])
        conversacion = db.get(Conversation, conv.id)
        r = motor._execute_tool(
            "book_appointment",
            {"doctor_id": doctor["id"], "patient_name": "Marco Garcete",
             "datetime_iso": cuando.strftime("%Y-%m-%dT%H:%M")},
            db, empresa, conversacion,
        )
    finally:
        db.close()

    assert r["ok"] is True
    assert r["dia_de_la_semana"] == "miércoles"
    assert "miércoles" in r["decirle_al_paciente"]
    assert cuando.strftime("%d/%m/%Y") in r["decirle_al_paciente"]
    # Y le recuerda al modelo qué tiene que hacer.
    assert "confirme" in r["message"] and "recordatorio" in r["message"]


def test_no_se_agenda_a_nombre_de_relleno():
    """El modelo agendaba a nombre de "el paciente" cuando no había preguntado."""
    company, doctor = _empresa_con_doctor("Clínica Sin Relleno")
    conv = _conversacion(company["id"], "595981777999")
    cuando = datetime.now(ZoneInfo(TIMEZONE)).replace(tzinfo=None) + timedelta(days=3)

    db = SessionLocal()
    try:
        empresa = db.get(Company, company["id"])
        conversacion = db.get(Conversation, conv.id)
        r = motor._execute_tool(
            "book_appointment",
            {"doctor_id": doctor["id"], "patient_name": "el paciente",
             "datetime_iso": cuando.strftime("%Y-%m-%dT%H:%M")},
            db, empresa, conversacion,
        )
        assert "error" in r
        assert "a nombre de quién" in r["error"]
        # Y no quedó nada agendado.
        assert db.query(Appointment).filter(
            Appointment.company_id == empresa.id).count() == 0
    finally:
        db.close()


def test_al_agendar_se_recuerda_el_nombre_del_paciente():
    company, doctor = _empresa_con_doctor("Clínica Recuerda")
    conv = _conversacion(company["id"], "595981778000")
    cuando = datetime.now(ZoneInfo(TIMEZONE)).replace(tzinfo=None) + timedelta(days=3)

    db = SessionLocal()
    try:
        empresa = db.get(Company, company["id"])
        conversacion = db.get(Conversation, conv.id)
        motor._execute_tool(
            "book_appointment",
            {"doctor_id": doctor["id"], "patient_name": "Joaquín Villalba",
             "para_otra_persona": True,
             "datetime_iso": cuando.strftime("%Y-%m-%dT%H:%M")},
            db, empresa, conversacion,
        )
        db.commit()
        actualizada = db.get(Conversation, conv.id)
        assert actualizada.patient_name == "Joaquín Villalba"
        # Es para otra persona: NO se toma como el nombre de quien escribe.
        assert actualizada.stated_name == ""
    finally:
        db.close()


# --- "¿Cuándo es mi turno?" ---


def test_el_paciente_puede_preguntar_por_su_propio_turno():
    """Antes esto se contestaba con check_agenda, que devuelve los horarios
    OCUPADOS del doctor: el bot le decía al paciente que su propio turno
    estaba ocupado."""
    company, doctor = _empresa_con_doctor("Clínica Mis Turnos")
    telefono = "595981778111"
    conv = _conversacion(company["id"], telefono)
    cuando = datetime.now(ZoneInfo(TIMEZONE)).replace(tzinfo=None) + timedelta(days=2)

    db = SessionLocal()
    try:
        empresa = db.get(Company, company["id"])
        conversacion = db.get(Conversation, conv.id)
        motor._execute_tool(
            "book_appointment",
            {"doctor_id": doctor["id"], "patient_name": "Marco Garcete",
             "datetime_iso": cuando.strftime("%Y-%m-%dT%H:%M")},
            db, empresa, conversacion,
        )
        r = motor._execute_tool("my_appointments", {}, db, empresa, conversacion)
    finally:
        db.close()

    assert len(r["appointments"]) == 1
    turno = r["appointments"][0]
    assert turno["paciente"] == "Marco Garcete"
    assert turno["doctor"] == "Dr. Marcos Benítez Sosa"
    assert "pendiente" in turno["estado"]
    # Con el nombre del día, para que el bot no lo recalcule.
    assert any(d in turno["cuando"] for d in
               ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"])


def test_sin_turnos_lo_dice_claro():
    company, _ = _empresa_con_doctor("Clínica Sin Turnos")
    conv = _conversacion(company["id"], "595981778222")
    db = SessionLocal()
    try:
        empresa = db.get(Company, company["id"])
        r = motor._execute_tool("my_appointments", {}, db, empresa,
                                db.get(Conversation, conv.id))
    finally:
        db.close()
    assert r["appointments"] == []
    assert "no tiene ningún turno" in r["note"]


def test_los_turnos_de_otro_paciente_no_se_ven():
    """El teléfono es la identidad: el turno de otro número no aparece."""
    company, doctor = _empresa_con_doctor("Clínica Turnos Ajenos")
    mio = _conversacion(company["id"], "595981778333")
    cuando = datetime.now(ZoneInfo(TIMEZONE)).replace(tzinfo=None) + timedelta(days=4)

    db = SessionLocal()
    try:
        empresa = db.get(Company, company["id"])
        db.add(Appointment(
            company_id=empresa.id, doctor_id=doctor["id"],
            patient_name="Otra Persona", patient_phone="595999999999",
            scheduled_at=cuando, status="pending", notes="",
        ))
        db.commit()
        r = motor._execute_tool("my_appointments", {}, db, empresa,
                                db.get(Conversation, mio.id))
    finally:
        db.close()
    assert r["appointments"] == []


def test_la_herramienta_esta_en_el_pack_de_agenda():
    from app import packs

    assert "my_appointments" in packs.BOOKING.tools
