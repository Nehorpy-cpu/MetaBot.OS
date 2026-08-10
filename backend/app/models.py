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


class User(Base):
    """Persona. Global a la plataforma: no cuelga de una empresa.

    A qué empresas accede lo define Membership, nunca un dato del frontend.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(200), default="")
    # El operador de la plataforma (nosotros): ve todas las empresas.
    is_platform_admin: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(10), default="active")  # active|disabled
    failed_attempts: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None] = mapped_column(nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Membership(Base):
    """ÚNICA fuente de verdad de qué usuario accede a qué empresa."""

    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "company_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10), default="operator")
    status: Mapped[str] = mapped_column(String(10), default="active")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AuthSession(Base):
    """Sesión opaca y revocable. Se guarda el hash del token, nunca el token."""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    ip: Mapped[str] = mapped_column(String(45), default="")


class AuditLog(Base):
    """Bitácora append-only: quién hizo qué, sobre qué empresa."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    actor_kind: Mapped[str] = mapped_column(String(20), default="user")  # user|platform_token|system
    user_id: Mapped[int | None] = mapped_column(nullable=True)
    company_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(60))
    ok: Mapped[bool] = mapped_column(default=True)
    ip: Mapped[str] = mapped_column(String(45), default="")
    detail: Mapped[str] = mapped_column(Text, default="")


class Company(Base):
    """Tenant: una empresa, clínica o consultorio."""

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    # "medical" habilita el módulo de agenda; cualquier otro valor es un
    # rubro genérico detectado por el onboarding inteligente
    vertical: Mapped[str] = mapped_column(String(20))
    niche: Mapped[str] = mapped_column(String(200), default="")
    industry: Mapped[str] = mapped_column(String(200), default="")
    address: Mapped[str] = mapped_column(String(300), default="")  # para recordatorios de citas
    profile: Mapped[str] = mapped_column(Text, default="")  # JSON: productos, audiencia, tono
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


class Product(Base):
    """Producto del catálogo real, importado de la web del negocio.

    La imagen es SIEMPRE una foto real descargada del sitio (o vacía):
    los agentes nunca generan imágenes de producto.
    """

    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("company_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    brand: Mapped[str] = mapped_column(String(100), default="")
    category: Mapped[str] = mapped_column(String(100), default="")
    gender: Mapped[str] = mapped_column(String(30), default="")
    price_gs: Mapped[int] = mapped_column(default=0)
    in_stock: Mapped[bool] = mapped_column(default=True)
    image_url: Mapped[str] = mapped_column(String(500), default="")   # origen
    image_path: Mapped[str] = mapped_column(String(300), default="")  # copia local real
    notes: Mapped[str] = mapped_column(Text, default="")  # notas olfativas / ficha
    source_url: Mapped[str] = mapped_column(String(500), default="")
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Service(Base):
    """Servicio, estudio o prestación que ofrece el negocio (ecografías,
    limpiezas dentales, o cualquier servicio de cualquier rubro).
    Precio en Guaraníes como entero; 0 = 'consultar'."""

    __tablename__ = "services"
    __table_args__ = (UniqueConstraint("company_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(100), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    price_gs: Mapped[int] = mapped_column(default=0)
    duration_min: Mapped[int] = mapped_column(default=30)
    active: Mapped[bool] = mapped_column(default=True)


class DoctorService(Base):
    """Qué doctores/profesionales atienden cada servicio."""

    __tablename__ = "doctor_services"
    __table_args__ = (UniqueConstraint("doctor_id", "service_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"), index=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"), index=True)


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


class Report(Base):
    """Informe generado por el enjambre (Quant semanal, competencia, etc.)."""

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # "weekly" | "competitive"
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AuditFinding(Base):
    """Hallazgo del Auditor (Guard) sobre una conversación del CX Bot."""

    __tablename__ = "audit_findings"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    severity: Mapped[str] = mapped_column(String(10))  # "info" | "warning" | "critical"
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class CompetitorSource(Base):
    """URL de un competidor a escanear para inteligencia de mercado."""

    __tablename__ = "competitor_sources"
    __table_args__ = (UniqueConstraint("company_id", "url"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    url: Mapped[str] = mapped_column(String(500))
    label: Mapped[str] = mapped_column(String(200), default="")


class Creative(Base):
    """Creativo publicitario: copy del Director Creativo + imagen del Estudio Visual."""

    __tablename__ = "creatives"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    brief: Mapped[str] = mapped_column(Text)
    copy_text: Mapped[str] = mapped_column(Text, default="")
    image_prompt: Mapped[str] = mapped_column(Text, default="")
    image_path: Mapped[str] = mapped_column(String(300), default="")
    provider: Mapped[str] = mapped_column(String(30), default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class PromptSuggestion(Base):
    """Mejora de prompt propuesta por el agente Optimizador.

    Se aplica solo con aprobación humana (regla del proyecto: los cambios
    de comportamiento de los bots no se auto-aplican en silencio).
    """

    __tablename__ = "prompt_suggestions"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    old_prompt: Mapped[str] = mapped_column(Text)
    suggested_prompt: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending|applied|rejected
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Campaign(Base):
    """Campaña publicitaria en borrador: plan del CEO, copys del Creativo,
    imágenes del Estudio Visual y veredicto del Auditor. Cuando exista la
    Marketing API aprobada, de acá se publica."""

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    brief: Mapped[str] = mapped_column(Text)
    format: Mapped[str] = mapped_column(String(20))  # carousel | single | video_script
    title: Mapped[str] = mapped_column(String(300), default="")
    strategy: Mapped[str] = mapped_column(Text, default="")   # plan del CEO
    cards: Mapped[str] = mapped_column(Text, default="[]")     # JSON [{headline, copy, image_path,...}]
    audit_severity: Mapped[str] = mapped_column(String(10), default="")  # ok|info|warning|critical
    audit_note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(15), default="draft")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class GlossaryTerm(Base):
    """Glosario jopara/guaraní: correcciones human-in-the-loop para ASR y copys."""

    __tablename__ = "glossary_terms"
    __table_args__ = (UniqueConstraint("company_id", "heard"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    heard: Mapped[str] = mapped_column(String(200))      # lo que transcribió el ASR
    corrected: Mapped[str] = mapped_column(String(200))  # forma correcta
    meaning: Mapped[str] = mapped_column(String(500), default="")
