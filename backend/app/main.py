import hmac
import os
import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db as db_module
from .auth import SESSION_COOKIE, _token_hash
from .config import ADMIN_TOKEN
from .llm import available_providers
from .models import AuthSession, Membership, User
from .routers import agents, auth, bridge, campaigns, catalog, chat, companies, creatives, dashboard, glossary, intelligence, medical, services, whatsapp_webhook
from .scheduler import start_scheduler

# El esquema lo gestiona Alembic (entrypoint.sh corre `alembic upgrade head`).
# Una sola fuente de verdad para la estructura de la base.

app = FastAPI(title="MetaBot.OS", version="0.12.0")
for router in (auth.router, companies.router, agents.router, medical.router, glossary.router, dashboard.router, chat.router, whatsapp_webhook.router, bridge.router, intelligence.router, creatives.router, campaigns.router, services.router, catalog.router):
    app.include_router(router, prefix="/api")


# Rutas /api que NO requieren identidad: salud, login y webhooks entrantes
# (los webhooks validan su propia firma/secreto de Meta o del bridge).
_PUBLIC_API_PREFIXES = ("/api/health", "/api/webhooks/", "/api/auth/login")

# Toda ruta de datos de un tenant tiene esta forma. El aislamiento se aplica
# acá, en UN solo lugar: un endpoint nuevo queda protegido sin que nadie
# tenga que acordarse de nada.
_TENANT_PATH = re.compile(r"^/api/companies/(\d+)(?:/|$)")


def _resolve_identity(request: Request) -> tuple[bool, int | None, str]:
    """(autenticado, user_id, motivo). user_id None = token de plataforma."""
    token = request.cookies.get(SESSION_COOKIE, "")
    if token:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        db = db_module.SessionLocal()
        try:
            session = (
                db.query(AuthSession)
                .filter(AuthSession.token_hash == _token_hash(token), AuthSession.revoked_at.is_(None))
                .first()
            )
            if session and session.expires_at > now:
                user = db.get(User, session.user_id)
                if user and user.status == "active":
                    return True, (None if user.is_platform_admin else user.id), ""
        finally:
            db.close()

    header = request.headers.get("Authorization", "")
    bearer = header[7:] if header.startswith("Bearer ") else ""
    if ADMIN_TOKEN and bearer and hmac.compare_digest(bearer, ADMIN_TOKEN):
        return True, None, ""
    return False, None, "No autorizado"


def _can_access_company(user_id: int, company_id: int) -> bool:
    db = db_module.SessionLocal()
    try:
        return (
            db.query(Membership)
            .filter(
                Membership.user_id == user_id,
                Membership.company_id == company_id,
                Membership.status == "active",
            )
            .first()
            is not None
        )
    finally:
        db.close()


@app.middleware("http")
async def enforce_auth_and_tenant(request: Request, call_next):
    """Autenticación + aislamiento de tenant, transversal a toda la API.

    1. Todo /api exige identidad (sesión de usuario o token de plataforma),
       salvo salud, login y webhooks.
    2. Si la ruta apunta a una empresa concreta, se exige membresía activa.
       El tenant se valida contra la identidad, nunca se confía en el path.
    """
    path = request.url.path
    if not path.startswith("/api") or path.startswith(_PUBLIC_API_PREFIXES):
        return await call_next(request)

    if not ADMIN_TOKEN:
        return JSONResponse(
            {"detail": "Servidor sin ADMIN_TOKEN configurado: API cerrada."}, status_code=503
        )

    authenticated, user_id, reason = _resolve_identity(request)
    if not authenticated:
        return JSONResponse({"detail": reason}, status_code=401)

    if user_id is not None:  # usuario normal: se valida la empresa del path
        match = _TENANT_PATH.match(path)
        if match and not _can_access_company(user_id, int(match.group(1))):
            # 404 y no 403: no se confirma que la empresa exista.
            return JSONResponse({"detail": "Empresa no encontrada"}, status_code=404)

    return await call_next(request)


@app.on_event("startup")
def _startup():
    start_scheduler()


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "llm_providers": [p["name"] for p in available_providers()],
    }


# Los mounts van al FINAL: en Starlette las rutas se evalúan en orden y un
# mount en "/" taparía la API si se registrara antes.
_media_dir = Path(__file__).resolve().parents[1] / "media"
_media_dir.mkdir(exist_ok=True)
app.mount("/media", StaticFiles(directory=_media_dir), name="media")

# En producción el backend sirve también el panel compilado (SPA).
# En desarrollo el panel corre con vite en :5173 y este mount igual existe
# si hay un build local; la API no se ve afectada por el orden.
_panel_dist = Path(os.environ.get("PANEL_DIST", Path(__file__).resolve().parents[2] / "frontend" / "panel" / "dist"))
if (_panel_dist / "index.html").exists():
    app.mount("/", StaticFiles(directory=_panel_dist, html=True), name="panel")
