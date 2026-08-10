import hmac
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import ADMIN_TOKEN
from .db import Base, engine
from .llm import available_providers
from .routers import agents, bridge, campaigns, catalog, chat, companies, creatives, dashboard, glossary, intelligence, medical, services, whatsapp_webhook
from .scheduler import start_scheduler

Base.metadata.create_all(bind=engine)

app = FastAPI(title="MetaBot.OS", version="0.11.0")
for router in (companies.router, agents.router, medical.router, glossary.router, dashboard.router, chat.router, whatsapp_webhook.router, bridge.router, intelligence.router, creatives.router, campaigns.router, services.router, catalog.router):
    app.include_router(router, prefix="/api")


# Rutas /api que NO requieren token de admin: salud y webhooks entrantes
# (estos validan su propia firma/secreto de Meta o del bridge).
_PUBLIC_API_PREFIXES = ("/api/health", "/api/webhooks/")


@app.middleware("http")
async def require_admin_token(request: Request, call_next):
    """Autenticación transversal: todo /api exige Authorization: Bearer <ADMIN_TOKEN>,
    salvo salud y webhooks. Cierra el acceso público multi-tenant (BOLA/IDOR)."""
    path = request.url.path
    if path.startswith("/api") and not path.startswith(_PUBLIC_API_PREFIXES):
        if not ADMIN_TOKEN:
            return JSONResponse(
                {"detail": "Servidor sin ADMIN_TOKEN configurado: API cerrada."}, status_code=503
            )
        header = request.headers.get("Authorization", "")
        token = header[7:] if header.startswith("Bearer ") else ""
        if not token or not hmac.compare_digest(token, ADMIN_TOKEN):
            return JSONResponse({"detail": "No autorizado"}, status_code=401)
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
