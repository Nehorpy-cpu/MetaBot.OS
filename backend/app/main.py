from fastapi import FastAPI

from .db import Base, engine
from .llm import available_providers
from .routers import agents, companies, dashboard, glossary, medical

Base.metadata.create_all(bind=engine)

app = FastAPI(title="MetaBot.OS", version="0.2.0")
for router in (companies.router, agents.router, medical.router, glossary.router, dashboard.router):
    app.include_router(router, prefix="/api")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "llm_providers": [p["name"] for p in available_providers()],
    }
