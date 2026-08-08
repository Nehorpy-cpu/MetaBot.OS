from fastapi import FastAPI

from .db import Base, engine
from .llm import available_providers
from pathlib import Path

from fastapi.staticfiles import StaticFiles

from .routers import agents, bridge, chat, companies, creatives, dashboard, glossary, intelligence, medical, whatsapp_webhook
from .scheduler import start_scheduler

Base.metadata.create_all(bind=engine)

app = FastAPI(title="MetaBot.OS", version="0.7.0")
for router in (companies.router, agents.router, medical.router, glossary.router, dashboard.router, chat.router, whatsapp_webhook.router, bridge.router, intelligence.router, creatives.router):
    app.include_router(router, prefix="/api")

_media_dir = Path(__file__).resolve().parents[1] / "media"
_media_dir.mkdir(exist_ok=True)
app.mount("/media", StaticFiles(directory=_media_dir), name="media")


@app.on_event("startup")
def _startup():
    start_scheduler()


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "llm_providers": [p["name"] for p in available_providers()],
    }
