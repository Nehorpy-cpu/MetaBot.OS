"""Esquema multi-tenant: toda entidad de negocio cuelga de una Company (tenant).

Los montos monetarios se guardan como enteros en Guaraníes (₲ no tiene
decimales). El formato con puntos de miles es responsabilidad del frontend.
"""
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Company(Base):
    """Tenant: una empresa, clínica o consultorio."""

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    vertical: Mapped[str] = mapped_column(String(20))  # "medical" | "ecommerce"
    niche: Mapped[str] = mapped_column(String(200), default="")
    # Canal de WhatsApp del tenant: "none" | "meta" (Cloud API) | "qr" (Baileys)
    wa_mode: Mapped[str] = mapped_column(String(10), default="none")
    # phone_number_id de WhatsApp Cloud API: identifica a qué tenant llega
    # cada mensaje entrante del webhook (solo modo "meta")
    wa_phone_number_id: Mapped[str] = mapped_column(String(50), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    agents: Mapped[list["Agent"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    doctors: Mapped[list["Doctor"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="company", cascade="all, delete-orphan")


class Agent(Base):
    """Un agente del enjambre. El system prompt vive acá, nunca en el frontend."""

    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("company_id", "slug"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    slug: Mapped[str] = mapped_column(String(50))  # "ceo", "quant", "guard", "creative", "visual", "cx"
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(200), default="")
    model: Mapped[str] = mapped_column(String(100), default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    temperature: Mapped[float] = mapped_column(default=0.3)
    active: Mapped[bool] = mapped_column(default=True)

    company: Mapped[Company] = relationship(back_populates="agents")


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    specialty: Mapped[str] = mapped_column(String(200), default="")
    schedule: Mapped[str] = mapped_column(String(100), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    email: Mapped[str] = mapped_column(String(200), default="")

    company: Mapped[Company] = relationship(back_populates="doctors")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="doctor")


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"), index=True)
    patient_name: Mapped[str] = mapped_column(String(200))
    patient_phone: Mapped[str] = mapped_column(String(50), default="")
    scheduled_at: Mapped[datetime] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|confirmed|cancelled|attended|no_show
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    company: Mapped[Company] = relationship(back_populates="appointments")
    doctor: Mapped[Doctor] = relationship(back_populates="appointments")


class Conversation(Base):
    """Hilo de chat con un cliente/paciente por un canal (whatsapp, instagram)."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp")
    contact_phone: Mapped[str] = mapped_column(String(50), index=True)
    contact_name: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | needs_human
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    company: Mapped[Company] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    direction: Mapped[str] = mapped_column(String(10))  # "in" | "out"
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class GlossaryTerm(Base):
    """Glosario jopara/guaraní: correcciones human-in-the-loop para ASR y copys."""

    __tablename__ = "glossary_terms"
    __table_args__ = (UniqueConstraint("company_id", "heard"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    heard: Mapped[str] = mapped_column(String(200))      # lo que transcribió el ASR
    corrected: Mapped[str] = mapped_column(String(200))  # forma correcta
    meaning: Mapped[str] = mapped_column(String(500), default="")
