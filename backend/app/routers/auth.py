"""Login, sesión y datos del usuario autenticado."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from .. import auth as auth_lib
from ..db import get_db
from ..models import AuthSession, Company, Membership, User

router = APIRouter(prefix="/auth", tags=["auth"])

MAX_FAILED = 10
LOCK_MINUTES = 15


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.post("/login")
def login(payload: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else ""
    email = payload.email.lower().strip()
    user = db.query(User).filter(User.email == email).first()

    if user and user.locked_until and user.locked_until > _now():
        auth_lib.audit(db, "login.locked", user_id=user.id, ok=False, ip=ip)
        raise HTTPException(429, "Demasiados intentos. Probá de nuevo en unos minutos.")

    # Se verifica siempre (con hash señuelo si el usuario no existe) para no
    # filtrar por tiempo qué correos están registrados.
    stored = user.password_hash if user else auth_lib._DUMMY_HASH
    ok = auth_lib.verify_password(payload.password, stored)

    if not ok or not user or user.status != "active":
        if user:
            user.failed_attempts += 1
            if user.failed_attempts >= MAX_FAILED:
                user.locked_until = _now() + timedelta(minutes=LOCK_MINUTES)
                user.failed_attempts = 0
            db.commit()
            auth_lib.audit(db, "login.failed", user_id=user.id, ok=False, ip=ip)
        else:
            auth_lib.audit(db, "login.unknown_email", actor_kind="system", ok=False, ip=ip,
                           detail={"email": email})
        raise HTTPException(401, "Credenciales inválidas")

    user.failed_attempts = 0
    user.locked_until = None
    token = auth_lib.create_session(db, user, ip)
    response.set_cookie(
        auth_lib.SESSION_COOKIE, token,
        httponly=True, secure=True, samesite="strict",
        max_age=auth_lib.SESSION_IDLE_HOURS * 3600, path="/",
    )
    auth_lib.audit(db, "login.ok", user_id=user.id, ip=ip)
    return _me_payload(db, user)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(auth_lib.SESSION_COOKIE, "")
    if token:
        auth_lib.revoke_session(db, token)
    response.delete_cookie(auth_lib.SESSION_COOKIE, path="/")
    return {"ok": True}


class CambioDeClave(BaseModel):
    actual: str = Field(min_length=1, max_length=200)
    nueva: str = Field(min_length=10, max_length=200)


@router.post("/password")
def cambiar_clave(
    payload: CambioDeClave,
    request: Request,
    identity: auth_lib.Identity = Depends(auth_lib.get_identity),
    db: Session = Depends(get_db),
):
    """Cambiar la propia contraseña.

    Existe porque el sistema reparte claves temporales: el portal del
    profesional le entrega una al médico y le dice que la cambie. Sin este
    endpoint, esa clave —que pasó por las manos de quien la creó— es la
    definitiva, y la promesa del panel era falsa.

    Exige la clave actual: una sesión robada no puede además apoderarse de la
    cuenta. Y al cambiarla se cierran TODAS las sesiones menos esta, que es
    el sentido de cambiarla cuando uno sospecha que se filtró.
    """
    if not identity.user:
        # El token de plataforma es una variable de entorno, no una cuenta.
        raise HTTPException(400, "El operador de la plataforma no cambia clave por acá")
    user = identity.user
    ip = request.client.host if request.client else ""
    if not auth_lib.verify_password(payload.actual, user.password_hash):
        auth_lib.audit(db, "auth.password", user_id=user.id, ok=False, ip=ip)
        raise HTTPException(403, "La contraseña actual no es correcta")
    if payload.nueva == payload.actual:
        raise HTTPException(422, "La contraseña nueva tiene que ser distinta")

    user.password_hash = auth_lib.hash_password(payload.nueva)
    actual = request.cookies.get(auth_lib.SESSION_COOKIE, "")
    conservar = auth_lib._token_hash(actual) if actual else ""
    cerradas = 0
    for sesion in db.query(AuthSession).filter(
        AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)
    ):
        if sesion.token_hash != conservar:
            sesion.revoked_at = _now()
            cerradas += 1
    db.commit()
    auth_lib.audit(db, "auth.password", user_id=user.id, ok=True, ip=ip,
                   detail={"sesiones_cerradas": cerradas})
    return {"ok": True, "sesiones_cerradas": cerradas}


def _me_payload(db: Session, user: User) -> dict:
    memberships = []
    for m in db.query(Membership).filter(
        Membership.user_id == user.id, Membership.status == "active"
    ):
        company = db.get(Company, m.company_id)
        if company:
            memberships.append({"company_id": company.id, "name": company.name, "role": m.role})
    return {
        "user": {"id": user.id, "email": user.email, "full_name": user.full_name},
        "is_platform_admin": user.is_platform_admin,
        "memberships": memberships,
    }


@router.get("/me")
def me(identity: auth_lib.Identity = Depends(auth_lib.get_identity), db: Session = Depends(get_db)):
    if identity.user:
        return _me_payload(db, identity.user)
    # Token de plataforma: acceso de operador, ve todas las empresas
    return {
        "user": {"id": None, "email": "operador@plataforma", "full_name": "Operador de plataforma"},
        "is_platform_admin": True,
        "memberships": [
            {"company_id": c.id, "name": c.name, "role": "owner"}
            for c in db.query(Company).order_by(Company.id)
        ],
    }
