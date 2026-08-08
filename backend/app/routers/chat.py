from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import chat as chat_engine
from ..db import get_db
from ..llm import LLMError
from ..models import Company, Conversation, Message

router = APIRouter(tags=["chat"])


class ChatIn(BaseModel):
    contact_phone: str = Field(min_length=3, max_length=50)
    contact_name: str = ""
    text: str = Field(min_length=1, max_length=4000)


class ConversationOut(BaseModel):
    id: int
    channel: str
    contact_phone: str
    contact_name: str
    status: str

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: int
    direction: str
    body: str
    created_at: str

    model_config = {"from_attributes": True}


@router.post("/companies/{company_id}/chat")
async def send_chat(company_id: int, payload: ChatIn, db: Session = Depends(get_db)):
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Empresa no encontrada")
    try:
        return await chat_engine.handle_incoming(
            db, company, payload.contact_phone, payload.text, payload.contact_name
        )
    except LLMError as exc:
        raise HTTPException(503, f"LLM no disponible: {exc}")


@router.get("/companies/{company_id}/conversations", response_model=list[ConversationOut])
def list_conversations(company_id: int, db: Session = Depends(get_db)):
    if not db.get(Company, company_id):
        raise HTTPException(404, "Empresa no encontrada")
    return (
        db.query(Conversation)
        .filter(Conversation.company_id == company_id)
        .order_by(Conversation.id.desc())
        .all()
    )


@router.get("/companies/{company_id}/conversations/{conv_id}/messages")
def list_messages(company_id: int, conv_id: int, db: Session = Depends(get_db)):
    conv = db.get(Conversation, conv_id)
    if not conv or conv.company_id != company_id:
        raise HTTPException(404, "Conversación no encontrada")
    msgs = db.query(Message).filter(Message.conversation_id == conv_id).order_by(Message.id).all()
    return [
        {"id": m.id, "direction": m.direction, "body": m.body, "created_at": m.created_at.isoformat()}
        for m in msgs
    ]
