"""Esquema multi-tenant: toda entidad de negocio cuelga de una Company (tenant).

Los montos monetarios se guardan como enteros en Guaraníes (₲ no tiene
decimales). El formato con puntos de miles es responsabilidad del frontend.
"""
from datetime import date, datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
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
    __table_args__ = (
        UniqueConstraint("user_id", "company_id"),
        # Compuesta con company_id: sin esto, un usuario de la clínica A
        # podría quedar apuntado al doctor de la clínica B con un id suelto,
        # y el portal le mostraría los pacientes de otro tenant.
        ForeignKeyConstraint(
            ["company_id", "doctor_id"], ["doctors.company_id", "doctors.id"],
            name="fk_memberships_doctor_tenant",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(14), default="operator")
    # Solo para el rol `professional`: a qué profesional corresponde este
    # usuario. Es lo que hace que un médico vea SUS pacientes y no los del
    # colega de al lado.
    doctor_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
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
    # Teléfono de contacto del negocio. Sin esto cargado el modelo INVENTA uno
    # —observado en producción: le dio a un paciente "021 214-400", que no
    # existe en ninguna parte de la base.
    phone: Mapped[str] = mapped_column(String(50), default="")
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

    @property
    def modules(self) -> list[str]:
        """Módulos habilitados por los Business Packs activos.

        El panel decide qué vistas mostrar con esto y no con `vertical`: un
        sanatorio, una odontológica y una veterinaria son verticales distintas
        con la misma agenda. Import tardío para no acoplar el esquema a packs.
        """
        from . import packs

        return sorted(packs.modules_for(self))

    agents: Mapped[list["Agent"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    doctors: Mapped[list["Doctor"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="company", cascade="all, delete-orphan")


class Agent(Base):
    """Un agente del enjambre. El system prompt vive acá, nunca en el frontend."""

    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("company_id", "slug"),
        UniqueConstraint("company_id", "id", name="uq_agent_company_id"),
    )

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
    # Necesario para que otras tablas puedan referenciar (company_id, id) como
    # clave foránea compuesta: sin este UNIQUE, PostgreSQL no lo permite.
    __table_args__ = (UniqueConstraint("company_id", "id", name="uq_doctor_company_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    specialty: Mapped[str] = mapped_column(String(200), default="")
    # Horario en texto libre, como lo carga la clínica: "Lun a Vie 08:00-14:00".
    # Sirve para MOSTRAR. No se parsea nunca para decidir si hay turno: eso lo
    # dice `doctor_schedules`, que es consultable con SQL.
    schedule: Mapped[str] = mapped_column(String(100), default="")
    # "libre" = no cargó horario estructurado. Se le sigue agendando —hay
    # clínicas operando así y bloquearlas les rompe el negocio— pero la cita
    # queda como PEDIDO y el bot no promete disponibilidad.
    # "estructurado" = tiene franjas cargadas; el servidor valida contra ellas.
    agenda_mode: Mapped[str] = mapped_column(String(15), default="libre")
    phone: Mapped[str] = mapped_column(String(50), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    # Qué porcentaje de lo facturado le corresponde al profesional. En un
    # sanatorio cobra una parte y la institución retiene el resto; en su
    # propio consultorio, 100. Es por profesional y no por clínica porque no
    # todos arreglan igual.
    honorario_pct: Mapped[int] = mapped_column(default=100)
    # Verificación contra el padrón público de especialistas certificados.
    # "unverified" = todavía no se buscó; "not_found" = se buscó y no figura.
    # La diferencia importa: no es lo mismo no haber mirado que haber mirado
    # y no encontrar nada.
    verification: Mapped[str] = mapped_column(String(15), default="unverified")
    cert_number: Mapped[str] = mapped_column(String(30), default="")
    cert_specialty: Mapped[str] = mapped_column(String(120), default="")
    cert_expires_at: Mapped[date | None] = mapped_column(nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(nullable=True)

    company: Mapped[Company] = relationship(back_populates="doctors")
    # viewonly: con la clave foránea COMPUESTA, company_id quedaría gobernado
    # por esta relación y `cita.doctor = otro` movería la fila entera de
    # empresa en silencio. De solo lectura no se puede: quien escribe pone los
    # ids explícitos y el motor valida que sean de la misma empresa.
    appointments: Mapped[list["Appointment"]] = relationship(
        back_populates="doctor", viewonly=True
    )


# Nota sobre las claves foráneas de acá en adelante: las columnas que apuntan
# a otra entidad del tenant NO llevan ForeignKey suelto. Llevan una
# ForeignKeyConstraint COMPUESTA con company_id en __table_args__, para que sea
# el motor —y no el programador— quien impida cruzar datos entre empresas.
# Dejar además la simple crearía DOS caminos entre las mismas tablas y
# SQLAlchemy no podría resolver el join.
class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        # Habilita que la planilla de honorarios cite una atención con clave
        # compuesta, y así una planilla no pueda apuntar a la atención de
        # otra empresa.
        UniqueConstraint("company_id", "id", name="uq_appointment_company_id"),
        ForeignKeyConstraint(
            ["company_id", "doctor_id"], ["doctors.company_id", "doctors.id"],
            name="fk_appointments_doctor_tenant",
        ),
        ForeignKeyConstraint(
            ["company_id", "insurer_id"], ["insurers.company_id", "insurers.id"],
            name="fk_appointments_insurer_tenant",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    doctor_id: Mapped[int] = mapped_column(index=True)
    patient_name: Mapped[str] = mapped_column(String(200))
    patient_phone: Mapped[str] = mapped_column(String(50), default="")
    scheduled_at: Mapped[datetime] = mapped_column(index=True)
    # Qué se va a hacer en el turno. Sin esto la cita era un punto de 30
    # minutos fijos: una ecografía de 45 y una consulta de 20 ocupaban lo
    # mismo, y dos pacientes reales quedaban solapados.
    service_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    duration_min: Mapped[int] = mapped_column(default=30)
    # Si el servidor pudo confirmar contra el horario cargado del profesional.
    # "sin_verificar" = el doctor no tiene horario estructurado; la cita vale
    # como PEDIDO de turno y recepción lo confirma. El bot no promete.
    verificacion: Mapped[str] = mapped_column(String(20), default="sin_verificar")
    # Por qué convenio vino. NULL = particular, que no es un dato faltante:
    # es la mitad de los pacientes y va en su propia planilla.
    insurer_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|confirmed|cancelled|attended|no_show
    reminder_status: Mapped[str] = mapped_column(String(15), default="scheduled")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    company: Mapped[Company] = relationship(back_populates="appointments")
    doctor: Mapped[Doctor] = relationship(back_populates="appointments", viewonly=True)


class DoctorSchedule(Base):
    """Una franja de atención del profesional, consultable con SQL.

    Existe porque `Doctor.schedule` es texto libre y la única forma de saber
    si el doctor atiende un martes a las 10 era que el MODELO interpretara ese
    string. Medido en producción: un paciente podía quedar agendado un domingo
    a las 23:00 con un doctor que atiende lunes a viernes de mañana, y el
    sistema le mandaba el recordatorio de una cita que no existía.

    `doctor_id` nulo = horario de la INSTITUCIÓN. Sirve para que una clínica
    con 40 médicos mate el "domingo a las 23:00" con cinco filas, sin cargar
    el horario de cada uno. Acota, no habilita: un turno dentro del horario de
    la clínica pero con un doctor sin franjas propias sigue siendo un pedido.

    `service_id` nulo = la franja vale para todo. Con servicio, vale SOLO para
    ese: es como se representa al profesional que atiende consulta toda la
    semana pero hace ecocardiogramas solo los martes a la tarde.
    """

    __tablename__ = "doctor_schedules"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "doctor_id"], ["doctors.company_id", "doctors.id"],
            name="fk_doctor_schedules_doctor_tenant", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["company_id", "service_id"], ["services.company_id", "services.id"],
            name="fk_doctor_schedules_service_tenant", ondelete="CASCADE",
        ),
        CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_schedule_weekday"),
        CheckConstraint("hora_fin > hora_inicio", name="ck_schedule_rango"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    doctor_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    service_id: Mapped[int | None] = mapped_column(nullable=True)
    weekday: Mapped[int] = mapped_column()  # 0=lunes … 6=domingo (como Python)
    # Minutos desde medianoche. Enteros y no `time` porque toda la aritmética
    # de huecos y solapes se hace en minutos.
    hora_inicio: Mapped[int] = mapped_column()
    hora_fin: Mapped[int] = mapped_column()
    lugar: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class DoctorAbsence(Base):
    """Licencia, vacaciones o cierre por feriado. Fechas, no recurrencia.

    `doctor_id` nulo = cierra la clínica entera ese día, para todos.
    """

    __tablename__ = "doctor_absences"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "doctor_id"], ["doctors.company_id", "doctors.id"],
            name="fk_doctor_absences_doctor_tenant", ondelete="CASCADE",
        ),
        CheckConstraint("hasta >= desde", name="ck_absence_rango"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    doctor_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    desde: Mapped[date] = mapped_column(index=True)
    hasta: Mapped[date] = mapped_column()  # inclusive
    motivo: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


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
    __table_args__ = (
        UniqueConstraint("company_id", "name"),
        # Igual que en doctors: habilita la clave foránea compuesta desde
        # doctor_services.
        UniqueConstraint("company_id", "id", name="uq_service_company_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(100), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    price_gs: Mapped[int] = mapped_column(default=0)
    duration_min: Mapped[int] = mapped_column(default=30)
    active: Mapped[bool] = mapped_column(default=True)
    specialty: Mapped[str] = mapped_column(String(100), default="")
    # Preparación previa: lo que hay que avisarle al paciente ANTES de que
    # viaje (ayuno, vejiga llena, suspender medicación). Sin esto el paciente
    # viene al vicio y hay que reprogramarlo.
    prep: Mapped[str] = mapped_column(Text, default="")
    sample: Mapped[str] = mapped_column(String(80), default="")  # sangre, orina…
    # Código del nomenclador de la ASEGURADORA del cliente. Vacío a propósito
    # en el catálogo curado: CPT y CDT son propietarios y cada aseguradora usa
    # el suyo; es el único que le sirve al cliente para facturar.
    code: Mapped[str] = mapped_column(String(50), default="")


class DoctorService(Base):
    """Qué doctores/profesionales atienden cada servicio.

    Las claves foráneas son COMPUESTAS con `company_id`: el motor mismo impide
    ligar el doctor de una empresa con el servicio de otra. Antes esta tabla
    ni siquiera tenía dueño, así que era imposible preguntar de qué empresa
    era una fila —y el bot podía terminar diciéndole a un cliente el nombre
    del profesional de otra clínica.
    """

    __tablename__ = "doctor_services"
    __table_args__ = (
        UniqueConstraint("doctor_id", "service_id"),
        ForeignKeyConstraint(
            ["company_id", "doctor_id"], ["doctors.company_id", "doctors.id"],
            name="fk_doctor_services_doctor_tenant",
        ),
        ForeignKeyConstraint(
            ["company_id", "service_id"], ["services.company_id", "services.id"],
            name="fk_doctor_services_service_tenant",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(index=True)
    doctor_id: Mapped[int] = mapped_column(index=True)
    service_id: Mapped[int] = mapped_column(index=True)


class Conversation(Base):
    """Hilo de chat con un cliente/paciente por un canal (whatsapp, instagram)."""

    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("company_id", "id", name="uq_conversation_company_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp")
    contact_phone: Mapped[str] = mapped_column(String(50), index=True)
    # Nombre del PERFIL de WhatsApp. Sirve para el panel, no para agendar: la
    # gente pone "Mami", el nombre del comercio o un emoji.
    contact_name: Mapped[str] = mapped_column(String(200), default="")
    # Nombre que la persona DIJO en la conversación, que es otra cosa. Se
    # persiste para no volver a preguntárselo en el turno siguiente: el
    # historial se corta a 20 mensajes y el nombre se perdía.
    stated_name: Mapped[str] = mapped_column(String(200), default="")
    # A quién le corresponde el turno cuando no es quien escribe. Mucha gente
    # agenda para el hijo, la madre o la pareja, y confundirlos en salud
    # significa mandarle a alguien los datos clínicos de otra persona.
    patient_name: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | needs_human
    # Directiva que dejó el CEO para el próximo turno del CX (modo shadow).
    pending_directive: Mapped[str] = mapped_column(String(500), default="")
    # El paciente escribió "STOP"/"BAJA": no recibe más avisos proactivos.
    # Seguir mandándole después de que pidió parar es lo que termina con el
    # número del cliente reportado.
    opted_out: Mapped[bool] = mapped_column(default=False)
    opted_out_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    company: Mapped[Company] = relationship(back_populates="conversations")
    # viewonly por el mismo motivo que en citas. El borrado en cascada pasa a
    # resolverlo la base (ON DELETE CASCADE en la clave compuesta), que es
    # donde tiene que estar.
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", viewonly=True
    )


class Message(Base):
    __tablename__ = "messages"
    # Deduplicación: WhatsApp reentrega mensajes al reconectar. El id del
    # mensaje en el canal es único por empresa, así una reentrega no genera
    # otra respuesta (ni otra cita).
    __table_args__ = (
        UniqueConstraint("company_id", "external_id", name="uq_message_external_id"),
        ForeignKeyConstraint(
            ["company_id", "conversation_id"], ["conversations.company_id", "conversations.id"],
            name="fk_messages_conversation_tenant", ondelete="CASCADE",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, default=0)
    conversation_id: Mapped[int] = mapped_column(index=True)
    direction: Mapped[str] = mapped_column(String(10))  # "in" | "out"
    body: Mapped[str] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages", viewonly=True)


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


class MedicalRegistry(Base):
    """Registro público de especialistas certificados (CPM, Paraguay).

    NO es de ningún tenant: es una tabla de referencia de la plataforma, como
    un padrón. Sirve para UNA cosa: cuando una clínica carga un profesional,
    verificar que su certificación existe y sigue vigente. Ese es el motivo
    por el que la certificación médica es pública.

    Lo que NO hace: poblar plantillas de clínicas. Estos son profesionales
    reales e identificables; afirmar que trabajan en una clínica donde nunca
    pisaron sería fabricar un dato sobre una persona.
    """

    __tablename__ = "medical_registry"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200), index=True)
    # Nombre normalizado con los tokens ORDENADOS: el padrón mezcla
    # "Nombre Apellido" con "Apellido, Nombre", así que ordenar las palabras
    # hace que las dos formas colisionen en la misma clave.
    match_key: Mapped[str] = mapped_column(String(200), index=True)
    specialty: Mapped[str] = mapped_column(String(120), index=True)
    # La misma especialidad viene escrita de varias formas: "Cirugía General"
    # (327 filas) y "Cirugia General" (19), "Pediatría General" (335),
    # "Pediatria General" (23) y "Pediátria General" (1). Buscar por el texto
    # tal cual dejaría fuera a esas decenas de profesionales sin avisar, así
    # que se guarda también la forma normalizada y se busca por ella.
    specialty_key: Mapped[str] = mapped_column(String(120), default="", index=True)
    cert_number: Mapped[str] = mapped_column(String(30), default="")
    accredited_at: Mapped[date | None] = mapped_column(nullable=True)
    expires_at: Mapped[date | None] = mapped_column(nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(40), default="CPM")
    imported_at: Mapped[datetime] = mapped_column(default=utcnow)


class Insurer(Base):
    """Convenio de la empresa con una aseguradora o prepaga.

    Es del tenant: cada clínica carga los convenios que ELLA tiene. No es una
    base de aseguradoras compartida —eso sería inventar acuerdos comerciales
    que no existen— sino lo que este cliente firmó y puede facturar.
    """

    __tablename__ = "insurers"
    __table_args__ = (
        UniqueConstraint("company_id", "name", "plan"),
        UniqueConstraint("company_id", "id", name="uq_insurer_company_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    plan: Mapped[str] = mapped_column(String(80), default="")  # "Plan Oro", "Básico"
    coverage_pct: Mapped[int] = mapped_column(default=0)   # cobertura por defecto 0-100
    copay_gs: Mapped[int] = mapped_column(default=0)       # copago fijo por defecto
    active: Mapped[bool] = mapped_column(default=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ServiceCoverage(Base):
    """Cobertura distinta a la del convenio para un servicio puntual."""

    __tablename__ = "service_coverages"
    __table_args__ = (
        UniqueConstraint("insurer_id", "service_id"),
        ForeignKeyConstraint(
            ["company_id", "insurer_id"], ["insurers.company_id", "insurers.id"],
            name="fk_coverage_insurer_tenant",
        ),
        ForeignKeyConstraint(
            ["company_id", "service_id"], ["services.company_id", "services.id"],
            name="fk_coverage_service_tenant",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    insurer_id: Mapped[int] = mapped_column(index=True)
    service_id: Mapped[int] = mapped_column(index=True)
    coverage_pct: Mapped[int] = mapped_column(default=0)
    copay_gs: Mapped[int] = mapped_column(default=0)
    # LO QUE LA ASEGURADORA PAGA POR ESTA PRÁCTICA, en guaraníes.
    #
    # Es como funciona de verdad: cada aseguradora tiene su nomenclador con un
    # monto fijo por práctica, que rara vez es un porcentaje redondo del precio
    # de lista de la clínica. Cargado a mano por quien tiene el convenio en la
    # mano; si está, gana sobre `coverage_pct`.
    #
    # 0 = no configurado, y ahí sí se calcula por porcentaje. No se usa NULL
    # para no tener dos formas de decir lo mismo en una columna que decide
    # plata.
    arancel_gs: Mapped[int] = mapped_column(default=0)
    # Hay estudios que el convenio directamente no cubre: decirlo es mejor que
    # que el paciente se entere en la caja.
    excluded: Mapped[bool] = mapped_column(default=False)


class FinanceIdentity(Base):
    """Quién puede preguntarle plata al CFO por WhatsApp, y hasta dónde.

    El número NO alcanza como identidad. Un WhatsApp se clona, se hereda con
    un chip reciclado y se pierde en un taxi; del otro lado se contestan
    saldos bancarios. Así que el número es solo la primera llave: para lo
    sensible hace falta el PIN, que se guarda hasheado como cualquier
    contraseña.

    Es POR EMPRESA: el mismo número puede ser dueño de tres negocios y ver
    distinto en cada uno. La fila que manda es la de la empresa que se está
    consultando, nunca "la del número".
    """

    __tablename__ = "finance_identities"
    __table_args__ = (
        UniqueConstraint("company_id", "phone", name="uq_finance_identity_phone"),
        UniqueConstraint("company_id", "id", name="uq_finance_identity_company_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    # Solo dígitos, sin +, espacios ni guiones: es lo que se compara contra lo
    # que manda el bridge, y dos formatos del mismo número son dos identidades
    # distintas para una restricción de unicidad.
    phone: Mapped[str] = mapped_column(String(30), index=True)
    nombre: Mapped[str] = mapped_column(String(200), default="")
    # Usuario del panel, si además entra por la web. Opcional: hay dueños que
    # solo usan WhatsApp.
    user_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    # Hasta qué nivel puede preguntar: "baja" | "media" | "alta".
    sensibilidad_max: Mapped[str] = mapped_column(String(6), default="baja")
    # scrypt, como las contraseñas. Vacío = todavía no configuró PIN, y ahí
    # NO puede consultar nada de riesgo medio o alto.
    pin_hash: Mapped[str] = mapped_column(String(255), default="")
    pin_intentos: Mapped[int] = mapped_column(default=0)
    pin_bloqueado_hasta: Mapped[datetime | None] = mapped_column(nullable=True)
    activo: Mapped[bool] = mapped_column(default=True)
    ultimo_uso_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class FinanceSession(Base):
    """Lo que el CFO está esperando de esta persona, ahora.

    Existe por una razón concreta: cuando la consulta es sensible el bot pide
    el PIN, y el dueño lo escribe en el chat. Sin esta tabla, ese mensaje se
    guarda en `messages` y viaja al historial del modelo — el PIN termina
    escrito en el WhatsApp de un teléfono que se puede perder, y en la base.

    Con la consulta pendiente guardada acá, el servidor reconoce el mensaje
    siguiente como un PIN, lo tacha antes de guardarlo, resuelve la consulta
    original por su cuenta y NUNCA se lo pasa al modelo.

    Es por (empresa, teléfono) y no por conversación: la misma persona puede
    tener una conversación abierta hace semanas y la pregunta pendiente es de
    ahora.
    """

    __tablename__ = "finance_sessions"
    __table_args__ = (
        UniqueConstraint("company_id", "phone", name="uq_finance_session_phone"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    phone: Mapped[str] = mapped_column(String(30), index=True)
    # Qué se estaba preguntando cuando se pidió el PIN.
    metrica: Mapped[str] = mapped_column(String(60), default="")
    desde: Mapped[date | None] = mapped_column(nullable=True)
    hasta: Mapped[date | None] = mapped_column(nullable=True)
    # Hasta cuándo vale ese pedido. Una espera de PIN que no vence convierte
    # cualquier número de cuatro cifras que la persona escriba mañana en un
    # intento de PIN.
    pin_pedido_hasta: Mapped[datetime | None] = mapped_column(nullable=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


class FinanceMetricState(Base):
    """En qué estado está una métrica PARA ESTA EMPRESA.

    La fórmula vive en código (`cfo_metricas.CATALOGO`), porque cambiar qué
    significa "venta" tiene que verse en el diff de un commit. Esta tabla
    guarda lo que sí es de cada empresa: qué versión está vigente, quién la
    aprobó y desde cuándo rige.

    Sin una fila en `activa`, el CFO NO usa esa métrica. Deny by default: una
    métrica que nadie aprobó no puede contestarle un número al dueño.
    """

    __tablename__ = "finance_metric_states"
    __table_args__ = (
        UniqueConstraint("company_id", "clave", name="uq_metric_state_clave"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    clave: Mapped[str] = mapped_column(String(60), index=True)
    # La versión del catálogo que se aprobó. Si el código publica una versión
    # nueva, ESTA sigue siendo la vigente hasta que alguien apruebe la otra:
    # una definición no cambia sola por un deploy.
    version: Mapped[int] = mapped_column(default=1)
    estado: Mapped[str] = mapped_column(String(12), default="borrador", index=True)
    aprobada_por: Mapped[int | None] = mapped_column(nullable=True)
    aprobada_at: Mapped[datetime | None] = mapped_column(nullable=True)
    vigente_desde: Mapped[date | None] = mapped_column(nullable=True)
    notas: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class FeeBatch(Base):
    """Planilla de honorarios: lo que una aseguradora le debe a un profesional.

    En Paraguay el profesional no cobra atención por atención: junta las del
    período, las separa POR ASEGURADORA —cada una recibe su propia planilla,
    con su formato y su circuito—, la firma y la entrega. Recién ahí cobra.

    Por eso la planilla no es una consulta que se recalcula cada vez que se
    abre: es un documento. Los montos quedan congelados en sus ítems al
    armarla. Si mañana cambia el precio de la ecografía o el convenio pasa
    de 80% a 70%, lo que ya se firmó y se entregó no puede moverse.

    `insurer_id` NULL significa "particulares": no es un dato faltante, es la
    planilla de lo que el profesional cobró de bolsillo del paciente.
    """

    __tablename__ = "fee_batches"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_fee_batch_company_id"),
        ForeignKeyConstraint(
            ["company_id", "doctor_id"], ["doctors.company_id", "doctors.id"],
            name="fk_fee_batch_doctor_tenant",
        ),
        ForeignKeyConstraint(
            ["company_id", "insurer_id"], ["insurers.company_id", "insurers.id"],
            name="fk_fee_batch_insurer_tenant",
        ),
        CheckConstraint("desde <= hasta", name="ck_fee_batch_periodo"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    doctor_id: Mapped[int] = mapped_column(index=True)
    insurer_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    # Se guarda el nombre además del id: una aseguradora que se da de baja no
    # puede dejar una planilla firmada sin saber a quién se le entregó.
    insurer_nombre: Mapped[str] = mapped_column(String(200), default="Particulares")
    desde: Mapped[date]
    hasta: Mapped[date]
    # borrador → firmada → entregada → cobrada. Solo un borrador se puede
    # borrar o rearmar; lo firmado es un documento.
    estado: Mapped[str] = mapped_column(String(12), default="borrador", index=True)
    total_facturado_gs: Mapped[int] = mapped_column(default=0)
    total_honorario_gs: Mapped[int] = mapped_column(default=0)
    honorario_pct: Mapped[int] = mapped_column(default=100)
    # "Firmar" acá NO es una firma digital: es que el profesional dio por
    # buena la planilla y la congeló. La firma de puño va en el papel que se
    # imprime. Decirle firma digital a esto sería mentir sobre su valor legal.
    firmada_at: Mapped[datetime | None] = mapped_column(nullable=True)
    firmada_por: Mapped[int | None] = mapped_column(nullable=True)
    entregada_at: Mapped[datetime | None] = mapped_column(nullable=True)
    cobrada_at: Mapped[datetime | None] = mapped_column(nullable=True)
    notas: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class FeeBatchItem(Base):
    """Una atención dentro de una planilla, con los montos congelados.

    La restricción única sobre (company_id, appointment_id) es la que sostiene
    todo: una atención se cobra UNA vez. Sin ella, rearmar una planilla o
    superponer dos períodos factura dos veces la misma consulta, y eso no es
    un error de software: es una nota de crédito y una discusión con la
    aseguradora.
    """

    __tablename__ = "fee_batch_items"
    __table_args__ = (
        UniqueConstraint("company_id", "appointment_id", name="uq_fee_item_atencion"),
        ForeignKeyConstraint(
            ["company_id", "batch_id"], ["fee_batches.company_id", "fee_batches.id"],
            name="fk_fee_item_batch_tenant", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["company_id", "appointment_id"],
            ["appointments.company_id", "appointments.id"],
            name="fk_fee_item_appointment_tenant",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    batch_id: Mapped[int] = mapped_column(index=True)
    appointment_id: Mapped[int] = mapped_column(index=True)
    # Copias, no referencias: la planilla tiene que poder leerse dentro de un
    # año aunque el paciente se haya borrado o el estudio cambiado de nombre.
    atendido_at: Mapped[datetime]
    paciente: Mapped[str] = mapped_column(String(200))
    servicio: Mapped[str] = mapped_column(String(200), default="")
    precio_lista_gs: Mapped[int] = mapped_column(default=0)
    facturado_gs: Mapped[int] = mapped_column(default=0)
    honorario_gs: Mapped[int] = mapped_column(default=0)
    # Por qué el monto es ese. Un profesional que ve un número que no espera
    # tiene que poder saber si salió del convenio, de una excepción, del
    # arancel cargado a mano, o de un ajuste puntual.
    origen_arancel: Mapped[str] = mapped_column(String(60), default="")
    # Alguien corrigió este renglón a mano antes de firmar. Se guarda lo que
    # el sistema había calculado: un monto cambiado que no deja rastro es
    # indistinguible de un error de cálculo, y acá alguien firma abajo.
    ajustado_a_mano: Mapped[bool] = mapped_column(default=False)
    facturado_calculado_gs: Mapped[int] = mapped_column(default=0)
    honorario_calculado_gs: Mapped[int] = mapped_column(default=0)
    ajuste_motivo: Mapped[str] = mapped_column(String(200), default="")


class Prescription(Base):
    """Receta cargada POR EL DOCTOR. El sistema la relata, nunca la genera.

    El bot puede entregársela al paciente palabra por palabra cuando el
    paciente la pide. Lo que NO hace es redactarla, resumirla, interpretarla
    ni sugerir cambios: eso sería ejercicio de la medicina por un modelo de
    lenguaje.
    """

    __tablename__ = "prescriptions"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_prescription_company_id"),
        ForeignKeyConstraint(
            ["company_id", "doctor_id"], ["doctors.company_id", "doctors.id"],
            name="fk_prescriptions_doctor_tenant",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    doctor_id: Mapped[int] = mapped_column(index=True)
    patient_name: Mapped[str] = mapped_column(String(120))
    patient_phone: Mapped[str] = mapped_column(String(30), index=True)
    diagnosis: Mapped[str] = mapped_column(Text, default="")
    indications: Mapped[str] = mapped_column(Text, default="")  # reposo, dieta, control
    issued_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    status: Mapped[str] = mapped_column(String(15), default="active")  # active|completed|cancelled
    # Recordatorios de toma: apagados salvo que el paciente los pida. El
    # consentimiento se registra con quién y cuándo, no como un booleano suelto.
    reminders_enabled: Mapped[bool] = mapped_column(default=False)
    consent_by: Mapped[str] = mapped_column(String(120), default="")
    consent_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # Sube en cada edición. Las tomas ya programadas llevan la versión con la
    # que se crearon: si la receta cambia, las viejas se descartan solas en
    # vez de mandarle al paciente la dosis nueva en los horarios viejos.
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class PrescriptionItem(Base):
    """Un medicamento de la receta, tal cual lo escribió el doctor."""

    __tablename__ = "prescription_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "prescription_id"], ["prescriptions.company_id", "prescriptions.id"],
            name="fk_prescription_items_tenant", ondelete="CASCADE",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    prescription_id: Mapped[int] = mapped_column(index=True)
    medication: Mapped[str] = mapped_column(String(200))
    dose: Mapped[str] = mapped_column(String(120))          # "1 comprimido", "5 ml"
    route: Mapped[str] = mapped_column(String(60), default="vía oral")
    frequency: Mapped[str] = mapped_column(String(120), default="")  # texto del doctor
    # `every_hours` = 0 significa que NO es un horario fijo (ej. "si tenés
    # dolor"). Nunca se convierte una pauta a demanda en tomas programadas.
    every_hours: Mapped[int] = mapped_column(default=0)
    duration_days: Mapped[int] = mapped_column(default=0)
    instructions: Mapped[str] = mapped_column(Text, default="")


class AgentPromptVersion(Base):
    """Historial del system prompt de un agente. Fuente de verdad ÚNICA.

    `Agent.system_prompt` pasa a ser una proyección de solo lectura que
    escribe SOLO la activación. Un rollback deja de ser "pegar el texto viejo
    que ojalá alguien haya guardado" y pasa a ser cambiar un rol.

    Los índices únicos parciales garantizan en el MOTOR que hay a lo sumo una
    versión activa y una candidata por agente. Con dos activas, cuál gana
    dependería del orden de las filas.
    """

    __tablename__ = "agent_prompt_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "agent_id"], ["agents.company_id", "agents.id"],
            name="fk_prompt_versions_agent_tenant",
        ),
        UniqueConstraint("company_id", "agent_id", "version", name="uq_prompt_version_num"),
        Index(
            "uq_prompt_version_active", "company_id", "agent_id", unique=True,
            sqlite_where=text("role = 'active'"), postgresql_where=text("role = 'active'"),
        ),
        Index(
            "uq_prompt_version_candidate", "company_id", "agent_id", unique=True,
            sqlite_where=text("role = 'candidate'"), postgresql_where=text("role = 'candidate'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    agent_id: Mapped[int] = mapped_column(index=True)
    version: Mapped[int]                      # monotónico por agente
    body: Mapped[str] = mapped_column(Text)
    body_sha: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(10), default="archived")  # active|candidate|archived
    source: Mapped[str] = mapped_column(String(12), default="human")   # human|optimizer|seed
    suggestion_id: Mapped[int | None] = mapped_column(nullable=True)
    # Corrida de evaluación que habilitó esta versión. Sin evidencia, nulo.
    eval_run_id: Mapped[int | None] = mapped_column(nullable=True)
    note: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    activated_at: Mapped[datetime | None] = mapped_column(nullable=True)


class GoldenCase(Base):
    """Un caso con respuesta VERIFICABLE, sin que opine ningún modelo.

    Cada caso dice qué tiene que pasar en términos comprobables: qué
    herramienta hay que llamar, cuál está prohibida, qué texto tiene que
    aparecer y cuál no. Nada de "¿está bien la respuesta?" preguntado a otro
    LLM, que es como este proyecto ya se comió un auditor que aprobaba todo.

    `critical=True` marca los casos que son GUARDRAIL: si uno falla, el
    candidato se rechaza aunque el resto haya mejorado. Una urgencia que no se
    deriva no se compensa con mejor tono.
    """

    __tablename__ = "golden_cases"
    __table_args__ = (UniqueConstraint("company_id", "slug", name="uq_golden_case_slug"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # company_id = 0 → caso de plataforma, aplica a todos los tenants del pack.
    company_id: Mapped[int] = mapped_column(default=0, index=True)
    slug: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(200))
    # Qué pack tiene que tener la empresa para que el caso aplique.
    pack: Mapped[str] = mapped_column(String(20), default="")
    agent_slug: Mapped[str] = mapped_column(String(30), default="cx")
    user_message: Mapped[str] = mapped_column(Text)
    setup: Mapped[str] = mapped_column(Text, default="{}")   # JSON: datos previos
    # Comprobaciones determinísticas, JSON:
    #   expect_tools / forbid_tools: nombres de herramientas
    #   expect_patterns / forbid_patterns: regex sobre la respuesta
    checks: Mapped[str] = mapped_column(Text, default="{}")
    critical: Mapped[bool] = mapped_column(default=False)
    rationale: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default="regresion")
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class EvalRun(Base):
    """Una corrida del conjunto dorado contra una versión de prompt."""

    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    agent_id: Mapped[int] = mapped_column(index=True)
    prompt_version_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    total: Mapped[int] = mapped_column(default=0)
    passed: Mapped[int] = mapped_column(default=0)
    critical_failed: Mapped[int] = mapped_column(default=0)
    # El veredicto lo calcula el servidor con una regla fija, no un modelo.
    verdict: Mapped[str] = mapped_column(String(12), default="pending")  # pass|fail|pending
    reason: Mapped[str] = mapped_column(String(300), default="")
    latency_ms: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class EvalResult(Base):
    """Resultado de UN caso dorado dentro de una corrida."""

    __tablename__ = "eval_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    eval_run_id: Mapped[int] = mapped_column(index=True)
    case_slug: Mapped[str] = mapped_column(String(80), index=True)
    passed: Mapped[bool] = mapped_column(default=False)
    critical: Mapped[bool] = mapped_column(default=False)
    # Qué comprobación falló, en texto legible. Sin esto, "falló" no sirve.
    failures: Mapped[str] = mapped_column(Text, default="")
    tools_used: Mapped[str] = mapped_column(String(300), default="")
    reply: Mapped[str] = mapped_column(Text, default="")
    latency_ms: Mapped[int] = mapped_column(default=0)


class Supervision(Base):
    """Una intervención del CEO sobre un turno del CX.

    Queda registrada siempre —incluso cuando decide no hacer nada— para
    poder medir si supervisar mejora los resultados o solo agrega costo.
    """

    __tablename__ = "supervisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "conversation_id"], ["conversations.company_id", "conversations.id"],
            name="fk_supervisions_conversation_tenant",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    conversation_id: Mapped[int] = mapped_column(index=True)
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
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "conversation_id"], ["conversations.company_id", "conversations.id"],
            name="fk_audit_findings_conversation_tenant",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    conversation_id: Mapped[int] = mapped_column(index=True)
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
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "agent_id"], ["agents.company_id", "agents.id"],
            name="fk_prompt_suggestions_agent_tenant",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    agent_id: Mapped[int] = mapped_column(index=True)
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
