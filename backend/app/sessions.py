"""Lease de sesiones de canal.

Dos procesos usando la misma sesión de WhatsApp la corrompen (se pelean por
las credenciales y la dejan inservible). Un lease con vencimiento resuelve el
caso sin coordinación externa: quien lo tiene, trabaja; el resto espera.
Si el dueño muere, el lease vence solo y otro worker puede tomarlo.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .models import ChannelSession

LEASE_MINUTES = 2  # se renueva con cada heartbeat; si el worker muere, vence


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def acquire(db: Session, company_id: int, worker_id: str, channel: str = "whatsapp") -> bool:
    """Toma o renueva el lease. False si otro worker vivo lo tiene."""
    session = (
        db.query(ChannelSession)
        .filter(ChannelSession.company_id == company_id, ChannelSession.channel == channel)
        .with_for_update(nowait=False)
        .first()
        if db.bind.dialect.name != "sqlite"
        else db.query(ChannelSession)
        .filter(ChannelSession.company_id == company_id, ChannelSession.channel == channel)
        .first()
    )
    now = _now()
    if session is None:
        db.add(ChannelSession(
            company_id=company_id, channel=channel, worker_id=worker_id,
            lease_until=now + timedelta(minutes=LEASE_MINUTES), last_heartbeat=now,
        ))
        db.commit()
        return True
    if session.worker_id and session.worker_id != worker_id and session.lease_until > now:
        return False  # otro worker vivo lo tiene
    session.worker_id = worker_id
    session.lease_until = now + timedelta(minutes=LEASE_MINUTES)
    session.last_heartbeat = now
    db.commit()
    return True


def heartbeat(db: Session, company_id: int, worker_id: str, status: str = "",
              phone: str = "", channel: str = "whatsapp") -> bool:
    """Renueva el lease y reporta estado. False si perdió el lease."""
    session = (
        db.query(ChannelSession)
        .filter(ChannelSession.company_id == company_id, ChannelSession.channel == channel)
        .first()
    )
    if not session or (session.worker_id and session.worker_id != worker_id):
        return False
    now = _now()
    session.lease_until = now + timedelta(minutes=LEASE_MINUTES)
    session.last_heartbeat = now
    if status:
        session.status = status
    if phone:
        session.phone = phone
    db.commit()
    return True


def release(db: Session, company_id: int, worker_id: str, channel: str = "whatsapp") -> None:
    session = (
        db.query(ChannelSession)
        .filter(ChannelSession.company_id == company_id, ChannelSession.channel == channel)
        .first()
    )
    if session and session.worker_id == worker_id:
        session.worker_id = ""
        session.status = "disconnected"
        db.commit()


def is_stale(db: Session, company_id: int, channel: str = "whatsapp") -> bool:
    """True si la sesión dice estar conectada pero dejó de latir."""
    session = (
        db.query(ChannelSession)
        .filter(ChannelSession.company_id == company_id, ChannelSession.channel == channel)
        .first()
    )
    if not session or session.status != "connected":
        return False
    return session.last_heartbeat < _now() - timedelta(minutes=LEASE_MINUTES * 2)
