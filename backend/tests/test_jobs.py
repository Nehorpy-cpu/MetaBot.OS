"""Ejecución durable: lo que no se puede perder.

De la suite obligatoria: 'recordatorios después de reiniciar servidor'.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from tests.test_api import _create_company, client

from app import job_handlers, jobs
from app.db import SessionLocal
from app.models import Appointment, Job


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _db():
    return SessionLocal()


@pytest.fixture(autouse=True)
def _cola_limpia():
    """Cada test arranca con la cola vacía: si no, los trabajos pendientes
    de otros tests se mezclan al reclamar."""
    db = SessionLocal()
    try:
        db.query(Job).delete()
        db.commit()
    finally:
        db.close()
    yield


# --- Contrato de la cola ---

def test_job_survives_restart(monkeypatch):
    """El caso que importa: el trabajo vive en la base, no en memoria. Un
    'reinicio' (proceso nuevo, worker nuevo) lo ejecuta igual."""
    company = _create_company(name="Durable Reinicio")
    ejecutados = []

    @jobs.handler("prueba_reinicio")
    async def _h(db, company_id, payload):
        ejecutados.append(payload["dato"])

    db = _db()
    try:
        # Se programó ANTES del "reinicio", con hora ya vencida
        jobs.enqueue(db, company["id"], "prueba_reinicio", _now() - timedelta(minutes=1),
                     payload={"dato": "no se pierde"})
    finally:
        db.close()

    # "Reinicio": otro worker toma lo pendiente
    import asyncio

    asyncio.run(jobs.process_due("worker-despues-del-reinicio"))
    assert ejecutados == ["no se pierde"]


def test_job_not_run_before_its_time():
    company = _create_company(name="Durable Futuro")
    ejecutados = []

    @jobs.handler("prueba_futuro")
    async def _h(db, company_id, payload):
        ejecutados.append(1)

    db = _db()
    try:
        jobs.enqueue(db, company["id"], "prueba_futuro", _now() + timedelta(hours=2))
    finally:
        db.close()

    import asyncio

    asyncio.run(jobs.process_due("w1"))
    assert ejecutados == []  # todavía no le toca


def test_enqueue_is_idempotent_by_dedup_key():
    company = _create_company(name="Durable Dedup")
    db = _db()
    try:
        primero = jobs.enqueue(db, company["id"], "k", _now(), dedup_key="unico-123")
        segundo = jobs.enqueue(db, company["id"], "k", _now(), dedup_key="unico-123")
        assert primero is not None
        assert segundo is None  # no duplica
        total = db.query(Job).filter(Job.dedup_key == "unico-123").count()
        assert total == 1
    finally:
        db.close()


def test_failed_job_retries_with_backoff():
    """Un fallo transitorio no pierde el trabajo: reintenta más tarde."""
    company = _create_company(name="Durable Reintento")
    intentos = {"n": 0}

    @jobs.handler("prueba_falla")
    async def _h(db, company_id, payload):
        intentos["n"] += 1
        raise RuntimeError("WhatsApp desconectado")

    db = _db()
    try:
        job = jobs.enqueue(db, company["id"], "prueba_falla", _now() - timedelta(minutes=1),
                           max_attempts=3)
        job_id = job.id
    finally:
        db.close()

    import asyncio

    asyncio.run(jobs.process_due("w1"))
    db = _db()
    try:
        job = db.get(Job, job_id)
        assert intentos["n"] == 1
        assert job.status == "pending"          # sigue vivo
        assert job.attempts == 1
        assert job.run_at > _now()              # reprogramado con backoff
        assert "WhatsApp desconectado" in job.last_error
    finally:
        db.close()


def test_job_fails_permanently_after_max_attempts():
    company = _create_company(name="Durable Agotado")

    @jobs.handler("prueba_agota")
    async def _h(db, company_id, payload):
        raise RuntimeError("siempre falla")

    db = _db()
    try:
        job = jobs.enqueue(db, company["id"], "prueba_agota", _now() - timedelta(minutes=1),
                           max_attempts=2)
        job_id = job.id
    finally:
        db.close()

    import asyncio

    for _ in range(2):
        db = _db()
        try:  # forzar que ya venza el backoff
            j = db.get(Job, job_id)
            j.run_at = _now() - timedelta(minutes=1)
            db.commit()
        finally:
            db.close()
        asyncio.run(jobs.process_due("w1"))

    db = _db()
    try:
        job = db.get(Job, job_id)
        assert job.status == "failed"   # queda registrado, no desaparece
        assert job.attempts == 2
    finally:
        db.close()


def test_two_workers_do_not_run_the_same_job():
    """Lease: el segundo worker no toma un trabajo ya tomado."""
    company = _create_company(name="Durable Lease")
    db = _db()
    try:
        jobs.enqueue(db, company["id"], "k", _now() - timedelta(minutes=1))
        tomados_1 = jobs.claim_due(db, "worker-1")
        tomados_2 = jobs.claim_due(db, "worker-2")
        assert len(tomados_1) == 1
        assert tomados_2 == []
    finally:
        db.close()


# --- Recordatorio de cita, de punta a punta ---

def test_booking_schedules_durable_reminder():
    company = _create_company(name="Cita Durable")
    cid = company["id"]
    doc = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dr. Durable"}).json()
    cuando = _now() + timedelta(days=3)
    appt = client.post(
        f"/api/companies/{cid}/appointments",
        json={"doctor_id": doc["id"], "patient_name": "Paciente",
              "patient_phone": "+595971000111",
              "scheduled_at": cuando.strftime("%Y-%m-%dT%H:%M:%S")},
    ).json()

    db = _db()
    try:
        job = db.query(Job).filter(
            Job.dedup_key == job_handlers.reminder_dedup_key(appt["id"])
        ).first()
        assert job is not None, "agendar debe programar el recordatorio"
        assert job.kind == job_handlers.REMINDER_KIND
        # Programado 24 h antes de la cita. `cuando` se escribió como hora de
        # agenda (local de Paraguay) y la cola razona en UTC, así que hay que
        # comparar contra el instante convertido: esta prueba antes esperaba el
        # valor sin convertir y por eso consagraba un desfase de 3 horas.
        esperado = job_handlers.local_a_utc(cuando - timedelta(hours=24))
        assert abs((job.run_at - esperado).total_seconds()) < 90
    finally:
        db.close()


def test_cancelling_appointment_cancels_reminder():
    company = _create_company(name="Cita Cancelada")
    cid = company["id"]
    doc = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dr. Cancel"}).json()
    appt = client.post(
        f"/api/companies/{cid}/appointments",
        json={"doctor_id": doc["id"], "patient_name": "Se cancela",
              "scheduled_at": (_now() + timedelta(days=4)).strftime("%Y-%m-%dT%H:%M:%S")},
    ).json()
    client.patch(f"/api/companies/{cid}/appointments/{appt['id']}", json={"status": "cancelled"})

    db = _db()
    try:
        job = db.query(Job).filter(
            Job.dedup_key == job_handlers.reminder_dedup_key(appt["id"])
        ).first()
        assert job.status == "cancelled"
    finally:
        db.close()


def test_reminder_not_scheduled_for_imminent_appointment():
    """Una cita dentro de las próximas 24 h no necesita recordatorio."""
    company = _create_company(name="Cita Inminente")
    cid = company["id"]
    doc = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dr. Hoy"}).json()
    appt = client.post(
        f"/api/companies/{cid}/appointments",
        json={"doctor_id": doc["id"], "patient_name": "Hoy mismo",
              "scheduled_at": (_now() + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S")},
    ).json()

    db = _db()
    try:
        job = db.query(Job).filter(
            Job.dedup_key == job_handlers.reminder_dedup_key(appt["id"])
        ).first()
        assert job is None
    finally:
        db.close()


@pytest.mark.parametrize("wa_mode,debe_enviar", [("meta", True), ("qr", False), ("none", False)])
def test_reminder_respects_channel_capability(monkeypatch, wa_mode, debe_enviar):
    """El recordatorio es proactivo: solo sale por canales que lo admiten."""
    company = _create_company(name=f"Cita Canal {wa_mode}")
    cid = company["id"]
    client.patch(f"/api/companies/{cid}", json={"wa_mode": wa_mode})
    doc = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dr. Canal"}).json()
    appt = client.post(
        f"/api/companies/{cid}/appointments",
        json={"doctor_id": doc["id"], "patient_name": "Cliente",
              "patient_phone": "+595971222333",
              "scheduled_at": (_now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S")},
    ).json()

    enviados = []

    async def fake_send(pnid, to, text):
        enviados.append(to)
        return {"sent": True}

    monkeypatch.setattr(job_handlers.whatsapp, "send_text", fake_send)

    import asyncio

    db = _db()
    try:
        asyncio.run(job_handlers._send_appointment_reminder(db, cid, {"appointment_id": appt["id"]}))
    finally:
        db.close()
    assert bool(enviados) is debe_enviar


def test_recordatorio_se_programa_en_utc_no_en_hora_local():
    """Regresión: la agenda se guarda en hora de Paraguay y la cola compara
    contra UTC. Sin conversión, el recordatorio salía 3 horas ANTES: el aviso
    de una cita de las 06:00 le llegaba al paciente a las 03:00 de la
    madrugada."""
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo

    from app import job_handlers
    from app.config import TIMEZONE
    from app.models import Appointment

    company = _create_company(name="Clínica Huso Horario")
    doc = client.post(f"/api/companies/{company['id']}/doctors", json={"name": "Dr. Reloj"}).json()

    # Cita a las 06:00 hora de Paraguay, dentro de 10 días.
    ahora_local = datetime.now(ZoneInfo(TIMEZONE)).replace(tzinfo=None)
    cita_local = (ahora_local + timedelta(days=10)).replace(hour=6, minute=0, second=0, microsecond=0)

    db = SessionLocal()
    try:
        appt = Appointment(
            company_id=company["id"], doctor_id=doc["id"],
            patient_name="Paciente Madrugada", patient_phone="+595981000600",
            scheduled_at=cita_local, status="pending",
        )
        db.add(appt)
        db.commit()
        db.refresh(appt)
        job_handlers.schedule_appointment_reminder(db, appt)

        job = db.query(Job).filter(
            Job.dedup_key == job_handlers.reminder_dedup_key(appt.id)
        ).one()

        # El instante correcto: 24h antes de la cita, expresado en UTC.
        esperado = (
            (cita_local - timedelta(hours=job_handlers.REMINDER_HOURS_BEFORE))
            .replace(tzinfo=ZoneInfo(TIMEZONE))
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
        )
        assert abs((job.run_at - esperado).total_seconds()) < 1, (
            f"run_at={job.run_at} esperado={esperado}: se está mezclando hora local con UTC"
        )

        # Y en hora local eso cae a las 06:00 del día anterior, no a las 03:00.
        local_del_aviso = (
            job.run_at.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(TIMEZONE))
        )
        assert local_del_aviso.hour == 6, f"el aviso saldría a las {local_del_aviso.hour}:00 hora de Paraguay"
    finally:
        db.close()
