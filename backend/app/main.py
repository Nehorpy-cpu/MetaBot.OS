from fastapi import FastAPI

from .db import Base, engine
from .llm import available_providers
from .routers import companies

Base.metadata.create_all(bind=engine)

app = FastAPI(title="MetaBot.OS", version="0.1.0")
app.include_router(companies.router)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "llm_providers": [p["name"] for p in available_providers()],
    }
