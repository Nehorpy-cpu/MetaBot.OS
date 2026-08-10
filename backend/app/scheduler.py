"""Planificador del enjambre: el sistema trabaja solo.

- Lunes 07:00 (hora Paraguay): informe semanal del Quant por empresa.
- Todos los días 20:00: auditoría del Guard sobre conversaciones nuevas.
- Todos los días 18:00: envío de recordatorios de citas de mañana
  (solo empresas con canal WhatsApp activo).
- Domingos 06:00: escaneo de competencia (empresas con URLs cargadas).

Se desactiva con SCHEDULER_ENABLED=0 (tests, workers auxiliares).
Los fallos de una empresa no frenan a las demás.
"""
import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from . import swarm, whatsapp
from .config import TIMEZONE
from .db import SessionLocal
from .llm import LLMError
from .models import Company

logger = logging.getLogger("metabot.scheduler")

SCHEDULER_ENABLED = os.environ.get("SCHEDULER_ENABLED", "1") == "1"
_scheduler: AsyncIOScheduler | None = None


async def _for_each_company(task_name: str, coro_factory):
    db = SessionLocal()
    try:
        for company in db.query(Company).all():
            try:
                await coro_factory(db, company)
            except LLMError as exc:
                logger.error("%s: LLM caído para %s: %s", task_name, company.name, exc)
            except Exception:
                logger.exception("%s falló para %s", task_name, company.name)
    finally:
        db.close()


async def job_weekly_reports():
    await _for_each_company("informe semanal", swarm.run_weekly_report)


async def job_guard_audits():
    await _for_each_company("auditoría", swarm.run_guard_audit)


async def job_competitive_scans():
    await _for_each_company("competencia", swarm.run_competitive_scan)


async def job_prompt_optimization():
    await _for_each_company("optimización de prompts", swarm.run_prompt_optimization)


async def job_send_reminders():
    from .routers.medical import list_reminders  # import tardío: evita ciclo

    from . import channels

    db = SessionLocal()
    try:
        for company in db.query(Company).filter(Company.wa_mode != "none").all():
            # Solo canales con capability de mensaje proactivo (Cloud API).
            if not channels.can_send_proactive(company.wa_mode):
                continue
            try:
                data = list_reminders(company.id, None, db)
                for r in data["reminders"]:
                    if r["phone"]:
                        await whatsapp.send_text(company.wa_phone_number_id, r["phone"], r["text"])
                if data["count"]:
                    logger.info("recordatorios enviados: %s (%s)", data["count"], company.name)
            except Exception:
                logger.exception("recordatorios fallaron para %s", company.name)
    finally:
        db.close()


def start_scheduler() -> AsyncIOScheduler | None:
    global _scheduler
    if not SCHEDULER_ENABLED or _scheduler:
        return _scheduler
    _scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    _scheduler.add_job(job_weekly_reports, CronTrigger(day_of_week="mon", hour=7, minute=0))
    _scheduler.add_job(job_guard_audits, CronTrigger(hour=20, minute=0))
    _scheduler.add_job(job_send_reminders, CronTrigger(hour=18, minute=0))
    _scheduler.add_job(job_competitive_scans, CronTrigger(day_of_week="sun", hour=6, minute=0))
    _scheduler.add_job(job_prompt_optimization, CronTrigger(day_of_week="sat", hour=7, minute=0))
    _scheduler.start()
    logger.info("planificador del enjambre iniciado (%s)", TIMEZONE)
    return _scheduler
