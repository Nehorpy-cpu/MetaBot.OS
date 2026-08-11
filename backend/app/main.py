import hmac
import os
import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db as db_module
from . import evaluator
from . import medication  # noqa: F401  — registra el handler de tomas en la cola
from .auth import resolve_identity
from .config import ADMIN_TOKEN
from .llm import available_providers
from .models import Membership
from .routers import agents, auth, bridge, campaigns, catalog, chat, companies, creatives, clinical, dashboard, glossary, intelligence, medical, services, whatsapp_webhook
from .scheduler import _start_job_worker, start_scheduler

# El esquema lo gestiona Alembic (entrypoint.sh corre `alembic upgrade head`).
# Una sola fuente de verdad para la estructura de la base.

app = FastAPI(title="MetaBot.OS", version="0.12.0")
for router in (auth.router, companies.router, agents.router, medical.router, glossary.router, dashboard.router, chat.router, whatsapp_webhook.router, bridge.router, intelligence.router, creatives.router, campaigns.router, services.router, catalog.router, clinical.router):
    app.include_router(router, prefix="/api")


# Rutas /api que NO requieren identidad: salud, login y webhooks entrantes
# (los webhooks validan su propia firma/secreto de Meta o del bridge).
_PUBLIC_API_PREFIXES = ("/api/health", "/api/webhooks/", "/api/auth/login")

# Toda ruta de datos de un tenant tiene esta forma. El aislamiento se aplica
# acá, en UN solo lugar: un endpoint nuevo queda protegido sin que nadie
# tenga que acordarse de nada.
# Captura el segmento CRUDO, no solo dígitos: FastAPI acepta como int cosas
# como "+7", " 7" o "007", y un regex de \d+ las dejaba pasar sin verificar
# la membresía. Acá se exige forma canónica y, si no lo es, se rechaza.
_TENANT_PATH = re.compile(r"^/api/companies/([^/]+)(?:/|$)")
# Rutas de /api/companies que NO son un id de empresa
_NON_TENANT_SEGMENTS = {"smart"}


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

    Fail-closed: un segmento de empresa que no sea un entero canónico se
    rechaza en vez de saltear la verificación.
    """
    path = request.url.path
    if not path.startswith("/api") or path.startswith(_PUBLIC_API_PREFIXES):
        return await call_next(request)

    if not ADMIN_TOKEN:
        return JSONResponse(
            {"detail": "Servidor sin ADMIN_TOKEN configurado: API cerrada."}, status_code=503
        )

    db = db_module.SessionLocal()
    try:
        identity = resolve_identity(request, db)
    finally:
        db.close()
    if not identity:
        return JSONResponse({"detail": "No autorizado"}, status_code=401)

    if not identity.is_platform:  # usuario normal: se valida la empresa del path
        match = _TENANT_PATH.match(path)
        if match:
            raw = match.group(1)
            if raw not in _NON_TENANT_SEGMENTS:
                # Forma canónica obligatoria: "7" sí, "+7"/" 7"/"007" no.
                if not raw.isdigit() or str(int(raw)) != raw:
                    return JSONResponse({"detail": "Empresa no encontrada"}, status_code=404)
                if not _can_access_company(identity.user_id, int(raw)):
                    return JSONResponse({"detail": "Empresa no encontrada"}, status_code=404)

    return await call_next(request)


@app.on_event("startup")
async def _startup():
    # El conjunto dorado se siembra al arrancar. Sin casos, `correr` aprueba
    # todo por vacuidad (0 de 0 fallaron) — el mismo modo de falla que el
    # auditor que aprobaba en silencio.
    _db = db_module.SessionLocal()
    try:
        nuevos = evaluator.sembrar_casos(_db)
        if nuevos:
            print(f"conjunto dorado: {nuevos} casos sembrados")
    except Exception:  # noqa: BLE001 — no impedir el arranque por esto
        pass
    finally:
        _db.close()
    start_scheduler()
    # Trabajos durables: al arrancar retoma lo que quedó pendiente (un
    # recordatorio no se pierde porque el servidor se haya reiniciado).
    await _start_job_worker()


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
