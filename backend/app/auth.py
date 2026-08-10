"""Autenticación y aislamiento por tenant.

Principio: el `company_id` con el que trabaja un request sale SIEMPRE de la
identidad autenticada (membresías del usuario) y jamás se confía en un dato
enviado por el frontend. Un usuario que pide /companies/7/... solo llega si
tiene membresía activa en la empresa 7.
"""
import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .config import ADMIN_TOKEN
from .db import get_db
from .models import AuditLog, AuthSession, Membership, User
from .permissions import Perm, role_has

SESSION_COOKIE = "mb_session"
SESSION_IDLE_HOURS = 8
SESSION_MAX_DAYS = 30
MIN_PASSWORD_LEN = 10


# --- Hashing de contraseñas (scrypt de la stdlib: sin dependencias nuevas) ---

_SCRYPT = {"n": 2**15, "r": 8, "p": 1, "dklen": 32}
# OpenSSL limita la memoria de scrypt a 32 MB por defecto; N=2^15 con r=8
# necesita ~34 MB, así que se sube el tope explícitamente.
_MAXMEM = 128 * _SCRYPT["n"] * _SCRYPT["r"] * 2


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, maxmem=_MAXMEM, **_SCRYPT)
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT["n"], _SCRYPT["r"], _SCRYPT["p"],
        base64.b64encode(salt).decode(), base64.b64encode(dk).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, dk_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        n_i, r_i = int(n), int(r)
        dk = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt_b64),
            n=n_i, r=r_i, p=int(p), dklen=len(base64.b64decode(dk_b64)),
            maxmem=128 * n_i * r_i * 2,
        )
        return hmac.compare_digest(dk, base64.b64decode(dk_b64))
    except (ValueError, TypeError):
        return False


# Hash señuelo: se verifica igual cuando el email no existe, para no filtrar
# por tiempo de respuesta qué correos están registrados.
_DUMMY_HASH = hash_password("no-existe-este-usuario")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# --- Sesiones ---

def create_session(db: Session, user: User, ip: str = "") -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(AuthSession(
        user_id=user.id,
        token_hash=_token_hash(token),
        expires_at=now + timedelta(days=SESSION_MAX_DAYS),
        ip=ip[:45],
    ))
    user.last_login_at = now
    db.commit()
    return token


def revoke_session(db: Session, token: str) -> None:
    session = db.query(AuthSession).filter(AuthSession.token_hash == _token_hash(token)).first()
    if session and not session.revoked_at:
        session.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()


def audit(db: Session, action: str, *, actor_kind: str = "user", user_id: int | None = None,
          company_id: int | None = None, ok: bool = True, ip: str = "", detail: dict | None = None) -> None:
    db.add(AuditLog(
        actor_kind=actor_kind, user_id=user_id, company_id=company_id,
        action=action[:60], ok=ok, ip=ip[:45],
        detail=json.dumps(detail, ensure_ascii=False)[:2000] if detail else "",
    ))
    db.commit()


# --- Identidad del request ---

class Identity:
    """Quién hace el request y a qué empresas puede acceder."""

    def __init__(self, user: User | None, is_platform: bool):
        self.user = user
        self.is_platform = is_platform  # platform admin o token de plataforma

    @property
    def user_id(self) -> int | None:
        return self.user.id if self.user else None

    def label(self) -> str:
        if self.user:
            return self.user.email
        return "token-de-plataforma"


def resolve_identity(request: Request, db: Session) -> Identity | None:
    """ÚNICA resolución de identidad: la usan el middleware y las dependencias.

    Aplica revocación, expiración absoluta y expiración por inactividad.
    Tener una sola implementación evita que middleware y endpoints difieran
    (el middleware ignoraba el idle y una cookie robada valía 30 días).
    """
    token = request.cookies.get(SESSION_COOKIE, "")
    if token:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        session = (
            db.query(AuthSession)
            .filter(AuthSession.token_hash == _token_hash(token), AuthSession.revoked_at.is_(None))
            .first()
        )
        if session and session.expires_at > now:
            if session.last_seen_at + timedelta(hours=SESSION_IDLE_HOURS) > now:
                user = db.get(User, session.user_id)
                if user and user.status == "active":
                    # Throttle: no escribir en cada request
                    if (now - session.last_seen_at) > timedelta(minutes=5):
                        session.last_seen_at = now
                        db.commit()
                    return Identity(user, user.is_platform_admin)

    # Token de plataforma (Authorization: Bearer): acceso de operador.
    header = request.headers.get("Authorization", "")
    bearer = header[7:] if header.startswith("Bearer ") else ""
    if ADMIN_TOKEN and bearer and hmac.compare_digest(bearer, ADMIN_TOKEN):
        return Identity(None, True)
    return None


def get_identity(request: Request, db: Session = Depends(get_db)) -> Identity:
    identity = resolve_identity(request, db)
    if not identity:
        raise HTTPException(401, "No autorizado")
    return identity


def assert_company_access(db: Session, identity: Identity, company_id: int, perm: Perm = Perm.READ) -> None:
    """Valida acceso al tenant. 404 (no 403) para no revelar su existencia."""
    if identity.is_platform:
        return
    membership = _membership(db, identity.user_id, company_id)
    if not membership:
        raise HTTPException(404, "Empresa no encontrada")
    if not role_has(membership.role, perm):
        raise HTTPException(403, f"Tu rol ({membership.role}) no permite esta acción")


def _membership(db: Session, user_id: int, company_id: int) -> Membership | None:
    return (
        db.query(Membership)
        .filter(
            Membership.user_id == user_id,
            Membership.company_id == company_id,
            Membership.status == "active",
        )
        .first()
    )


def allowed_company_ids(db: Session, identity: Identity) -> list[int] | None:
    """Empresas visibles. None = todas (operador de plataforma)."""
    if identity.is_platform:
        return None
    return [
        m.company_id
        for m in db.query(Membership).filter(
            Membership.user_id == identity.user_id, Membership.status == "active"
        )
    ]


def require_company(perm: Perm = Perm.READ):
    """Dependencia: valida que la identidad pueda operar sobre `company_id`.

    Devuelve el company_id ya autorizado. Los routers reciben el tenant de
    acá, no del path sin validar.
    """

    def dependency(
        company_id: int,
        identity: Identity = Depends(get_identity),
        db: Session = Depends(get_db),
    ) -> int:
        if identity.is_platform:
            return company_id
        membership = _membership(db, identity.user_id, company_id)
        if not membership:
            # 404 y no 403: no se confirma que la empresa exista.
            raise HTTPException(404, "Empresa no encontrada")
        if not role_has(membership.role, perm):
            raise HTTPException(
                403, f"Tu rol ({membership.role}) no permite esta acción"
            )
        return company_id

    return dependency
