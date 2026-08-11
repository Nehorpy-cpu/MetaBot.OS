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
    # Business Packs activos, separados por coma: "booking,healthcare" o
    # "commerce". Definen herramientas del bot, reglas y módulos del panel.
    packs: Mapped[str] = mapped_column(String(200), default="")
    address: Mapped[str] = mapped_column(String(300), default="")  # para recordatorios de citas
    # Supervisión del CEO: "off" (default, comportamiento intacto) |
    # "shadow" (analiza fuera del camino del cliente) | "inline" (además
    # puede reescribir la respuesta antes de enviarla).
    supervision: Mapped[str] = mapped_column(String(10), default="off")
    supervision_pct: Mapped[int] = mapped_column(default=100)  # % de conversaciones supervisadas
    profile: Mapped[str] = mapped_column(Text, default="")  # JSON: productos, audiencia, tono
    # Canal de WhatsApp del tenant: "none" | "meta" (Cloud API) | "qr" (Baileys)
    wa_mode: Mapped[str] = mapped_column(String(10), default="none")
    # phone_number_id de WhatsApp Cloud API: identifica a qué tenant llega
    # cada mensaje entrante del webhook (solo modo "meta")
    # Identificador del número en la Cloud API de Meta. ÚNICO a nivel motor: el
    # webhook resuelve a qué empresa pertenece un mensaje entrante SOLO por este
    # valor. Dos empresas con el mismo número harían que una reciba los mensajes
    # de los pacientes de la otra —y todas las filas quedarían perfectamente
    # consistentes, así que ningún chequeo de integridad lo detectaría.
    # Nulo (no cadena vacía) cuando no está configurado: en SQL varios NULL no
    # chocan entre sí, así que muchas empresas pueden no tenerlo.
    wa_phone_number_id: Mapped[str | None] = mapped_column(
        String(50), nullable=True, default=None, index=True, unique=True
    )
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
    reminder_status: Mapped[str] = mapped_column(String(15), default="scheduled")
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
    # Directiva que dejó el CEO para el próximo turno del CX (modo shadow).
    pending_directive: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    company: Mapped[Company] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"
    # Deduplicación: WhatsApp reentrega mensajes al reconectar. El id del
    # mensaje en el canal es único por empresa, así una reentrega no genera
    # otra respuesta (ni otra cita).
    __table_args__ = (UniqueConstraint("company_id", "external_id", name="uq_message_external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, default=0)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    direction: Mapped[str] = mapped_column(String(10))  # "in" | "out"
    body: Mapped[str] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class ChannelSession(Base):
    """Lease de sesión de canal: impide que dos workers usen la misma sesión
    de WhatsApp (que la corrompe) y da visibilidad de latido."""

    __tablename__ = "channel_sessions"
    __table_args__ = (UniqueConstraint("company_id", "channel"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp")
    worker_id: Mapped[str] = mapped_column(String(64), default="")
    lease_until: Mapped[datetime] = mapped_column(default=utcnow)
    last_heartbeat: Mapped[datetime] = mapped_column(default=utcnow)
    status: Mapped[str] = mapped_column(String(20), default="disconnected")
    phone: Mapped[str] = mapped_column(String(40), default="")


class Supervision(Base):
    """Una intervención del CEO sobre un turno del CX.

    Queda registrada siempre —incluso cuando decide no hacer nada— para
    poder medir si supervisar mejora los resultados o solo agrega costo.
    """

    __tablename__ = "supervisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    trigger_key: Mapped[str] = mapped_column(String(40), index=True)
    agent_slug: Mapped[str] = mapped_column(String(30))
    mode: Mapped[str] = mapped_column(String(10))       # shadow | inline
    arm: Mapped[str] = mapped_column(String(12), default="supervised")  # supervised | control
    action: Mapped[str] = mapped_column(String(15), default="keep")  # keep|rewrite|directive|escalate
    reason: Mapped[str] = mapped_column(String(500), default="")
    downgraded: Mapped[str] = mapped_column(String(120), default="")  # por qué se degradó, si pasó
    latency_ms: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class Job(Base):
    """Trabajo durable: lo que NO se puede perder.

    Un recordatorio, un cobro o un webhook pendiente no viven en memoria: si
    el servidor reinicia, el trabajo sigue acá y se ejecuta igual. Con
    reintentos, backoff y lease para que dos workers no lo corran a la vez.
    """

    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("dedup_key", name="uq_job_dedup_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    kind: Mapped[str] = mapped_column(String(50), index=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    # Idempotencia: encolar dos veces el mismo recordatorio no lo duplica.
    dedup_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    run_at: Mapped[datetime] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(15), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=5)
    last_error: Mapped[str] = mapped_column(String(500), default="")
    locked_by: Mapped[str] = mapped_column(String(64), default="")
    locked_until: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)


class AgentRun(Base):
    """Una ejecución de agente: la unidad de medida del Evaluator.

    Sin esto, 'el bot mejoró' es una opinión. Con esto se decide qué modelo
    entra por métricas y no por marca.
    """

    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    agent_slug: Mapped[str] = mapped_column(String(30), index=True)
    conversation_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    model: Mapped[str] = mapped_column(String(120), default="")
    question: Mapped[str] = mapped_column(Text, default="")
    answer: Mapped[str] = mapped_column(Text, default="")
    tools_used: Mapped[str] = mapped_column(String(300), default="")  # coma-separado
    latency_ms: Mapped[int] = mapped_column(default=0)
    tool_rounds: Mapped[int] = mapped_column(default=0)
    escalated: Mapped[bool] = mapped_column(default=False)
    booked: Mapped[bool] = mapped_column(default=False)   # cita concretada
    ok: Mapped[bool] = mapped_column(default=True)
    error: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


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
