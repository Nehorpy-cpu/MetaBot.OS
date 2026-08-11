"""Quién escribe, quién es el paciente, y qué datos ya tenemos de él.

De las capturas reales: el paciente escribió "Dr. Benitez Sosa esta bien el
martes a las 10 Marco Garcete me llamo" y el bot agendó sin reconocer que
"Marco Garcete" era el nombre, sin llamarlo por su nombre, y en otro turno le
pidió el número de teléfono desde el que le estaba escribiendo.
"""
import pytest

from tests.test_api import _create_company, client

from app import chat as motor
from app.db import SessionLocal
from app.models import Agent, Company, Conversation


# --- El nombre que la persona dice, se guarda ---


@pytest.mark.parametrize("texto,esperado", [
    ("Dr. Benitez Sosa esta bien el martes a las 10 Marco Garcete me llamo", "Marco Garcete"),
    ("me llamo Rossana Villalba", "Rossana Villalba"),
    ("Mi nombre es Juan Carlos Benítez", "Juan Carlos Benítez"),
    ("hola soy Marta", "Marta"),
    ("Soy Ana María Rolón, quiero un turno", "Ana María Rolón"),
])
def test_reconoce_el_nombre_en_medio_de_la_frase(texto, esperado):
    """El nombre viene pegado a otra cosa, no en un mensaje aparte."""
    assert motor._nombre_declarado(texto) == esperado


@pytest.mark.parametrize("texto", [
    "soy alérgico a la penicilina",
    "soy de Luque",
    "soy paciente del Dr. Benítez",
    "quiero un turno",
    "soy diabético",
    "",
])
def test_no_confunde_cualquier_cosa_con_un_nombre(texto):
    """"Soy alérgico" no es un nombre. Guardar eso y después saludar
    "¡Hola alérgico!" es peor que no guardar nada."""
    assert motor._nombre_declarado(texto) == ""


def test_el_nombre_declarado_sobrevive_al_corte_del_historial():
    """El historial se corta en 20 mensajes: si el nombre solo vive ahí, el
    bot se lo vuelve a preguntar a la vigésimo primera."""
    company = _create_company(name="Clínica Memoria")
    db = SessionLocal()
    try:
        conv = Conversation(company_id=company["id"], contact_phone="595981111111",
                            channel="whatsapp")
        db.add(conv)
        db.commit()
        assert conv.stated_name == ""
    finally:
        db.close()


# --- Rellenos que el modelo inventa cuando no preguntó ---


@pytest.mark.parametrize("relleno", [
    "el paciente", "Paciente", "Usuario", "N/A", "null", "nombre del paciente",
    "unknown", "-", "  ", "12345", "TU NOMBRE",
])
def test_no_se_agenda_a_nombre_de_un_relleno(relleno):
    """Una cita a nombre de "el paciente" no le sirve a nadie en recepción."""
    assert motor._nombre_de_persona(relleno) == ""


@pytest.mark.parametrize("bueno", [
    "Marco Garcete", "Ana", "José María Ávalos Ruiz Díaz", "Ñandutí Lezcano",
])
def test_los_nombres_de_verdad_pasan(bueno):
    assert motor._nombre_de_persona(bueno) == bueno


# --- Lo que el bot ve de la persona ---


def _conversacion(company_id, **kw):
    db = SessionLocal()
    try:
        conv = Conversation(company_id=company_id, contact_phone="595981222333",
                            channel="whatsapp", **kw)
        db.add(conv)
        db.commit()
        db.refresh(conv)
        return conv
    finally:
        db.close()


def test_el_bot_sabe_el_telefono_y_no_lo_pide():
    """Pedirle el número a alguien que te está escribiendo por WhatsApp desde
    ese número es la queja textual del dueño."""
    company = _create_company(name="Clínica Teléfono")
    conv = _conversacion(company["id"])
    bloque = motor._bloque_de_contacto(conv)
    assert "595981222333" in bloque
    assert "no se lo pidas" in bloque.lower()


def test_el_bot_usa_el_nombre_que_le_dijeron():
    company = _create_company(name="Clínica Nombre")
    conv = _conversacion(company["id"], stated_name="Marco Garcete")
    bloque = motor._bloque_de_contacto(conv)
    assert "Marco Garcete" in bloque
    assert "no se lo vuelvas a preguntar" in bloque.lower()


def test_el_nombre_del_perfil_no_se_ofrece_como_nombre_del_paciente():
    """La gente pone "Mami" o el nombre de su comercio en el perfil. Pasarlo
    como nombre haría que el bot agende a "Mami"."""
    company = _create_company(name="Clínica Perfil")
    conv = _conversacion(company["id"], contact_name="Mami ❤️")
    bloque = motor._bloque_de_contacto(conv)
    assert "puede no ser su nombre real" in bloque
    assert "no lo uses para agendar" in bloque.lower()


def test_distingue_a_quien_escribe_de_quien_se_atiende():
    """La madre agenda para el hijo: son dos personas distintas y el bot no
    puede tratarlas como la misma."""
    company = _create_company(name="Clínica Tercero")
    conv = _conversacion(company["id"], stated_name="Rossana",
                         patient_name="Joaquín Villalba")
    bloque = motor._bloque_de_contacto(conv)
    assert "Joaquín Villalba" in bloque
    assert "no es quien te escribe" in bloque


def test_sin_conversacion_no_rompe():
    """El simulador del panel y los tests llaman sin conversación."""
    assert motor._bloque_de_contacto(None) == ""


# --- Las reglas que le llegan al modelo ---


def test_la_regla_dice_que_no_pida_el_telefono():
    from app import packs

    reglas = packs.BOOKING.rules
    assert "EL TELÉFONO YA LO TENÉS" in reglas
    assert "nombre DEL PACIENTE" in reglas


def test_la_regla_pide_confirmacion_y_avisa_del_recordatorio():
    """Lo que pidió el dueño: en vez del teléfono, pedir que confirme y
    avisarle que un día antes le llega el recordatorio."""
    from app import packs

    reglas = packs.BOOKING.rules.lower()
    assert "confirme" in reglas
    assert "un día antes" in reglas and "recordatorio" in reglas


def test_la_preparacion_ya_no_se_vuelca_ante_cualquier_pregunta():
    """La regla decía "avisá SIEMPRE la preparación previa", y por eso a un
    "¿hacen cardiología?" contestaba con ayunos de tres estudios."""
    from app import packs

    reglas = packs.HEALTHCARE.rules
    assert "AL AGENDAR" in reglas
    assert "avisá siempre la preparación" not in reglas


def test_el_estilo_prohibe_volcar_lo_no_pedido():
    assert "NI MÁS NI MENOS" in motor.STYLE_RULES
