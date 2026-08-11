"""Ejecución durable de trabajos.

Contrato: `enqueue(kind, run_at, payload)` y un worker que los ejecuta. La
implementación de hoy es una cola en PostgreSQL — suficiente y sin infra
extra. Si la escala lo pide, Temporal entra detrás de este mismo contrato
sin tocar a quien encola.

Garantías:
- **Sobrevive reinicios**: el trabajo vive en la base, no en memoria.
- **Idempotente al encolar**: `dedup_key` evita duplicados.
- **Un solo ejecutor a la vez**: lease con vencimiento (si el worker muere,
  el trabajo se recupera solo).
- **Reintentos con backoff**: un fallo transitorio no pierde el trabajo.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from sqlalchemy import or_
from sqlalchemy.orm import Session

from . import db as db_module
from .models import Job

logger = logging.getLogger("metabot.jobs")

LEASE_MINUTES = 5
POLL_SECONDS = 20
BACKOFF_BASE_MINUTES = 2  # 2, 4, 8, 16… minutos

# El worker dormía POLL_SECONDS fijos entre pasadas, así que un mensaje de
# WhatsApp recién encolado esperaba hasta 20 segundos ANTES de que el bot
# empezara siquiera a pensar. Con este aviso, encolar algo que ya vence
# despierta al worker en el acto; el poll queda como red de seguridad para lo
# programado a futuro y para lo que encole otro proceso.
_hay_trabajo: asyncio.Event | None = None


def _avisar_al_worker() -> None:
    """Despierta al worker si está durmiendo. No falla si no hay bucle."""
    if _hay_trabajo is None:
        return
    try:
        bucle = _hay_trabajo._loop  # type: ignore[attr-defined]
    except AttributeError:
        bucle = None
    if bucle and bucle.is_running():
        # enqueue() se llama desde código sincrónico dentro del request; el
        # Event pertenece al bucle del worker, así que hay que cruzarlo.
        bucle.call_soon_threadsafe(_hay_trabajo.set)
    else:
        _hay_trabajo.set()

# kind → handler. El handler recibe (db, company_id, payload) y puede fallar:
# si lanza, el trabajo se reintenta.
HANDLERS: dict[str, Callable[[Session, int, dict], Awaitable[None]]] = {}


def handler(kind: str):
    """Registra el ejecutor de un tipo de trabajo."""

    def decorator(fn):
        HANDLERS[kind] = fn
        return fn

    return decorator


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def enqueue(
    db: Session,
    company_id: int,
    kind: str,
    run_at: datetime,
    payload: dict | None = None,
    dedup_key: str | None = None,
    max_attempts: int = 5,
) -> Job | None:
    """Programa un trabajo. Devuelve None si ya existía (por dedup_key)."""
    if dedup_key:
        existing = db.query(Job).filter(Job.dedup_key == dedup_key).first()
        if existing:
            return None
    job = Job(
        company_id=company_id,
        kind=kind,
        payload=json.dumps(payload or {}, ensure_ascii=False),
        dedup_key=dedup_key,
        run_at=run_at,
        max_attempts=max_attempts,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    if run_at <= _now():
        _avisar_al_worker()
    return job


def cancel(db: Session, dedup_key: str) -> bool:
    """Cancela un trabajo pendiente (ej. se canceló la cita)."""
    job = (
        db.query(Job)
        .filter(Job.dedup_key == dedup_key, Job.status == "pending")
        .first()
    )
    if not job:
        return False
    job.status = "cancelled"
    db.commit()
    return True


def claim_due(db: Session, worker_id: str, limit: int = 10) -> list[Job]:
    """Toma trabajos vencidos, marcándolos con un lease propio."""
    now = _now()
    candidates = (
        db.query(Job)
        .filter(
            Job.status == "pending",
            Job.run_at <= now,
            or_(Job.locked_until.is_(None), Job.locked_until < now),
        )
        .order_by(Job.run_at)
        .limit(limit)
        .all()
    )
    claimed = []
    for job in candidates:
        # Relectura con condición: si otro worker lo tomó entre medio, se salta.
        updated = (
            db.query(Job)
            .filter(
                Job.id == job.id,
                Job.status == "pending",
                or_(Job.locked_until.is_(None), Job.locked_until < now),
            )
            .update(
                {"locked_by": worker_id, "locked_until": now + timedelta(minutes=LEASE_MINUTES)},
                synchronize_session=False,
            )
        )
        if updated:
            db.commit()
            db.refresh(job)
            claimed.append(job)
        else:
            db.rollback()
    return claimed


async def run_job(db: Session, job: Job) -> None:
    """Ejecuta un trabajo y registra el resultado."""
    fn = HANDLERS.get(job.kind)
    job.attempts += 1
    if not fn:
        job.status = "failed"
        job.last_error = f"Sin handler para '{job.kind}'"
        db.commit()
        logger.error("trabajo %s sin handler: %s", job.id, job.kind)
        return
    try:
        await fn(db, job.company_id, json.loads(job.payload or "{}"))
        job.status = "done"
        job.completed_at = _now()
        job.locked_by = ""
        job.locked_until = None
        db.commit()
        logger.info("trabajo %s (%s) completado", job.id, job.kind)
    except Exception as exc:  # el handler decide qué es fatal lanzando o no
        job.last_error = f"{type(exc).__name__}: {exc}"[:500]
        job.locked_by = ""
        job.locked_until = None
        if job.attempts >= job.max_attempts:
            job.status = "failed"
            logger.error("trabajo %s agotó reintentos: %s", job.id, job.last_error)
        else:
            # Backoff exponencial: 2, 4, 8, 16… minutos
            delay = BACKOFF_BASE_MINUTES * (2 ** (job.attempts - 1))
            job.run_at = _now() + timedelta(minutes=delay)
            logger.warning(
                "trabajo %s falló (intento %s/%s), reintenta en %s min: %s",
                job.id, job.attempts, job.max_attempts, delay, job.last_error,
            )
        db.commit()


async def process_due(worker_id: str, limit: int = 10) -> int:
    """Una pasada del worker. Devuelve cuántos trabajos ejecutó."""
    db = db_module.SessionLocal()
    try:
        jobs = claim_due(db, worker_id, limit)
        for job in jobs:
            await run_job(db, job)
        return len(jobs)
    finally:
        db.close()


async def worker_loop(worker_id: str) -> None:
    """Bucle del worker: al arrancar recupera lo que quedó pendiente."""
    global _hay_trabajo
    _hay_trabajo = asyncio.Event()
    logger.info("worker de trabajos durables iniciado (%s)", worker_id)
    while True:
        try:
            await process_due(worker_id)
        except Exception:
            logger.exception("fallo en el bucle de trabajos")
        # Espera hasta POLL_SECONDS, pero se corta apenas alguien encola algo
        # que ya vence. Un mensaje entrante no puede quedar 20s en la cola
        # mientras el paciente mira el celular.
        _hay_trabajo.clear()
        try:
            await asyncio.wait_for(_hay_trabajo.wait(), timeout=POLL_SECONDS)
        except asyncio.TimeoutError:
            pass
