"""Recordatorios de toma: los seis prerequisitos que faltaban.

Una revisión adversarial dijo que la primera versión no estaba en condiciones
de mandarle mensajes a pacientes reales. Cada prueba de acá fija uno de los
bloqueantes que había que cerrar antes.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from tests.test_api import _create_company, client

from app import chat as chat_engine
from app import jobs, medication
from app.config import TIMEZONE
from app.db import SessionLocal
from app.models import Conversation, Doctor, Job, Prescription, PrescriptionItem


def _receta(cid: int, telefono: str, *, consentida: bool = True,
            cada_horas: int = 8, dias: int = 3) -> int:
    db = SessionLocal()
    try:
        doc = Doctor(company_id=cid, name="Dra. Ayala", specialty="Clínica médica")
        db.add(doc)
        db.flush()
        r = Prescription(
            company_id=cid, doctor_id=doc.id, patient_name="Ana Rojas",
            patient_phone=telefono, diagnosis="Infección urinaria",
            reminders_enabled=consentida, consent_by="Dra. Ayala",
        )
        db.add(r)
        db.flush()
        db.add(PrescriptionItem(
            company_id=cid, prescription_id=r.id, medication="Ciprofloxacina 500 mg",
            dose="1 comprimido", route="vía oral", frequency=f"cada {cada_horas} horas",
            every_hours=cada_horas, duration_days=dias,
            instructions="Tomar con abundante agua.",
        ))
        db.commit()
        return r.id
    finally:
        db.close()


def _escribio(cid: int, telefono: str) -> None:
    """El paciente le escribió a la clínica alguna vez."""
    db = SessionLocal()
    try:
        db.add(Conversation(company_id=cid, contact_phone=telefono, channel="whatsapp"))
        db.commit()
    finally:
        db.close()


def _programar(receta_id: int) -> dict:
    db = SessionLocal()
    try:
        return medication.programar(db, db.get(Prescription, receta_id))
    finally:
        db.close()


# --- P2: identidad del paciente ---


def test_no_se_manda_a_un_telefono_que_nunca_escribio():
    """Un dígito mal tipeado mandaría datos de salud a un desconocido."""
    company = _create_company(name="Clínica Sin Contacto")
    rid = _receta(company["id"], "+595981500001")
    r = _programar(rid)
    assert r["programadas"] == 0
    assert "no escribió nunca" in r["motivo"]


def test_con_el_paciente_verificado_si_se_programan():
    company = _create_company(name="Clínica Verificada")
    tel = "+595981500002"
    _escribio(company["id"], tel)
    rid = _receta(company["id"], tel, cada_horas=8, dias=3)
    r = _programar(rid)
    assert r["programadas"] == 9  # 3 días × 3 tomas


# --- Consentimiento ---


def test_sin_consentimiento_no_se_programa_nada():
    """Apagados por defecto: el recordatorio se activa cuando el paciente lo
    pide, no cuando la clínica lo asume."""
    company = _create_company(name="Clínica Sin Consentir")
    tel = "+595981500003"
    _escribio(company["id"], tel)
    rid = _receta(company["id"], tel, consentida=False)
    r = _programar(rid)
    assert r["programadas"] == 0
    assert "no pidió recordatorios" in r["motivo"]


# --- Pauta a demanda ---


def test_una_pauta_a_demanda_no_se_vuelve_horario_fijo():
    """'Si tenés dolor' no es cada N horas. Convertirlo sería inventar una
    indicación que el doctor no dio, y despertar al paciente por un
    analgésico condicional."""
    company = _create_company(name="Clínica A Demanda")
    tel = "+595981500004"
    _escribio(company["id"], tel)
    rid = _receta(company["id"], tel, cada_horas=0, dias=0)
    r = _programar(rid)
    assert r["programadas"] == 0
    assert r["a_demanda_omitidas"] == 1


# --- P4: horario silencioso ---


@pytest.mark.parametrize("hora,silencio", [(23, True), (3, True), (6, True), (7, False), (14, False), (21, False)])
def test_franja_de_silencio(hora, silencio):
    momento = datetime(2026, 8, 20, hora, 0)
    assert medication.en_silencio(momento) is silencio


def test_una_toma_de_madrugada_se_corre_a_la_manana():
    corrida = medication.correr_fuera_del_silencio(datetime(2026, 8, 20, 3, 0))
    assert corrida == datetime(2026, 8, 20, 7, 0)
    # Una de las 23:00 se va a la mañana SIGUIENTE
    corrida = medication.correr_fuera_del_silencio(datetime(2026, 8, 20, 23, 30))
    assert corrida == datetime(2026, 8, 21, 7, 0)


def test_ninguna_toma_programada_cae_en_la_madrugada():
    company = _create_company(name="Clínica Sin Madrugada")
    tel = "+595981500005"
    _escribio(company["id"], tel)
    rid = _receta(company["id"], tel, cada_horas=4, dias=3)
    _programar(rid)

    db = SessionLocal()
    try:
        tomas = db.query(Job).filter(Job.kind == medication.DOSE_KIND).all()
        assert tomas
        for t in tomas:
            local = t.run_at.replace(tzinfo=__import__("datetime").timezone.utc).astimezone(ZoneInfo(TIMEZONE))
            assert not medication.en_silencio(local.replace(tzinfo=None)), \
                f"una toma quedó a las {local.hour}:00 hora de Paraguay"
    finally:
        db.close()


# --- P5: receta editada ---


def test_editar_la_receta_invalida_las_tomas_viejas():
    """Si no, el paciente recibe la dosis NUEVA en los horarios VIEJOS."""
    company = _create_company(name="Clínica Editada")
    tel = "+595981500006"
    _escribio(company["id"], tel)
    rid = _receta(company["id"], tel, cada_horas=12, dias=2)
    _programar(rid)

    db = SessionLocal()
    try:
        receta = db.get(Prescription, rid)
        item = db.query(PrescriptionItem).filter(PrescriptionItem.prescription_id == rid).one()
        viejo = db.query(Job).filter(
            Job.dedup_key == medication.dedup_dosis(item.id, 1, 1)
        ).one()

        # El doctor edita: sube la versión y se dan de baja las tomas viejas.
        canceladas = medication.cancelar(db, receta)
        receta.version += 1
        db.commit()
        assert canceladas > 0
        db.refresh(viejo)
        assert viejo.status == "cancelled"

        # Y una toma vieja que igual llegara al worker se descarta por versión.
        import asyncio
        item2 = db.query(PrescriptionItem).filter(PrescriptionItem.prescription_id == rid).one()
        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            medication._enviar_dosis(db, company["id"],
                                     {"prescription_id": rid, "item_id": item2.id,
                                      "version": 1, "n": 1, "de": 4})
        )  # no debe lanzar: simplemente no envía
    finally:
        db.close()


# --- P3: baja del paciente ---


def test_stop_da_de_baja_sin_pasar_por_el_modelo(monkeypatch):
    company = _create_company(name="Clínica Baja")
    tel = "+595981500007"

    async def explota(*args, **kwargs):
        raise AssertionError("la baja no puede depender de un modelo")

    monkeypatch.setattr(chat_engine, "chat_raw", explota)
    resp = client.post(f"/api/companies/{company['id']}/chat",
                       json={"contact_phone": tel, "text": "STOP"})
    assert resp.json()["actions"][0]["tool"] == "opt_out"

    db = SessionLocal()
    try:
        conv = db.query(Conversation).filter(Conversation.contact_phone == tel).one()
        assert conv.opted_out is True
    finally:
        db.close()


def test_un_paciente_dado_de_baja_no_recibe_tomas():
    company = _create_company(name="Clínica Baja Programa")
    tel = "+595981500008"
    _escribio(company["id"], tel)
    db = SessionLocal()
    try:
        conv = db.query(Conversation).filter(Conversation.contact_phone == tel).one()
        conv.opted_out = True
        db.commit()
    finally:
        db.close()

    rid = _receta(company["id"], tel)
    r = _programar(rid)
    assert r["programadas"] == 0
    assert "baja" in r["motivo"]


def test_la_baja_se_respeta_tambien_en_el_envio(monkeypatch):
    """No alcanza con no programar: el paciente puede darse de baja DESPUÉS,
    con las tomas ya en la cola."""
    import asyncio

    from app import outbound

    company = _create_company(name="Clínica Baja Tardía")
    tel = "+595981500009"
    _escribio(company["id"], tel)
    rid = _receta(company["id"], tel)
    _programar(rid)

    enviados = []

    async def fake_enviar(db, cid, telefono, texto):
        enviados.append(telefono)
        return {"sent": True}

    monkeypatch.setattr(outbound, "enviar", fake_enviar)

    db = SessionLocal()
    try:
        conv = db.query(Conversation).filter(Conversation.contact_phone == tel).one()
        conv.opted_out = True
        db.commit()
        item = db.query(PrescriptionItem).filter(PrescriptionItem.prescription_id == rid).one()
        receta = db.get(Prescription, rid)
        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            medication._enviar_dosis(db, company["id"],
                                     {"prescription_id": rid, "item_id": item.id,
                                      "version": receta.version, "n": 1, "de": 9})
        )
    finally:
        db.close()
    assert enviados == [], "se le mandó a alguien que pidió la baja"


# --- Texto ---


def test_el_texto_de_la_toma_sale_de_la_base_no_de_un_modelo():
    company = _create_company(name="Clínica Texto")
    tel = "+595981500010"
    _escribio(company["id"], tel)
    rid = _receta(company["id"], tel)
    db = SessionLocal()
    try:
        receta = db.get(Prescription, rid)
        item = db.query(PrescriptionItem).filter(PrescriptionItem.prescription_id == rid).one()
        doctor = db.get(Doctor, receta.doctor_id)
        texto = medication.texto_dosis(receta, item, doctor, 2, 9)
    finally:
        db.close()

    assert "Ciprofloxacina 500 mg" in texto
    assert "1 comprimido" in texto
    assert "Tomar con abundante agua." in texto
    assert "Dra. Ayala" in texto
    assert "toma 2 de 9" in texto
    assert "*STOP*" in texto            # la baja siempre a la vista
    assert "no podemos cambiar una indicación médica" in texto


def test_hay_tope_de_avisos_por_medicamento():
    """'Cada 4 horas por 30 días' son 180 mensajes: eso no es un
    recordatorio, es hostigamiento."""
    company = _create_company(name="Clínica Tope")
    tel = "+595981500011"
    _escribio(company["id"], tel)
    rid = _receta(company["id"], tel, cada_horas=4, dias=60)
    r = _programar(rid)
    assert r["programadas"] == medication.MAX_TOMAS_POR_ITEM
