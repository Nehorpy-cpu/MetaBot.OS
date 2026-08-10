"""Supervisión del CEO sobre los turnos del CX.

PRINCIPIO: el CEO nunca corre ANTES del CX. Corre DESPUÉS, y solo si el
propio resultado del CX muestra que el turno salió mal. Así la ruta rápida
—la del cliente que espera en WhatsApp— no paga absolutamente nada.

Clasificar la intención del cliente antes de responder era la trampa: obliga
a mirar el mensaje, y ahí es donde se duplica la latencia (la línea base
medida de una respuesta con herramientas es ~61 segundos). En cambio,
detectar que un turno salió mal es determinístico y gratis: se lee de las
variables que `handle_incoming` ya tiene en la mano.

Tres modos por empresa (`Company.supervision`):

- ``off``    — default de toda empresa, existente y nueva. Comportamiento
               byte a byte el de hoy: `detect()` ni se llama.
- ``shadow`` — el CEO analiza FUERA del camino del cliente. Nunca toca la
               respuesta de este turno ni escala. Puede dejar una directiva
               para el próximo turno y queda todo registrado para medir.
- ``inline`` — además puede reescribir la respuesta antes de enviarla y
               escalar a humano.

Anti-bucle, por construcción y no por promesa: el supervisor es un asesor
SIN herramientas (`tools=None`), así que estructuralmente no puede volver a
entrar al motor; corre una sola vez por turno; hay presupuesto por
conversación y por empresa; y `supervision="off"` lo apaga entero.

Los disparadores se expresan sobre HERRAMIENTAS y PACKS, nunca sobre
`company.vertical`: una inmobiliaria y una perfumería comparten
`catalog_miss` porque ambas usan `search_catalog`.
"""
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from . import packs
from .llm import chat_raw
from .models import Agent, Company, Conversation, Supervision

logger = logging.getLogger("metabot.supervisor")

# Presupuestos: la supervisión cuesta una llamada al modelo, así que tiene
# techo. Sin esto, una conversación en bucle podría gastar sin límite.
MAX_POR_CONVERSACION = 3      # en 24h
MAX_POR_EMPRESA_DIA = 200
MAX_REPLY_CHARS = 1200
MAX_DIRECTIVA_CHARS = 500

ACCIONES = ("keep", "rewrite", "directive", "escalate")


@dataclass(frozen=True)
class Trigger:
    key: str
    agent_slug: str   # qué agente supervisa: "guard" (cumplimiento) o "ceo"
    mode: str         # modo MÍNIMO que requiere: "shadow" | "inline"
    priority: int     # mayor gana; se dispara como mucho UNO por turno
    reason: str


# Riesgo de cumplimiento primero: es el único caso donde intervenir importa
# más que la latencia. Después, lo que el cliente sufre; al final, lo que
# solo cuesta plata.
TRIGGERS: tuple[Trigger, ...] = (
    Trigger("compliance_risk", "guard", "inline", 100,
            "La respuesta roza indicación clínica (dosis o diagnóstico)."),
    Trigger("escalation_requested", "ceo", "inline", 90,
            "El bot escaló a humano: el mensaje de traspaso es lo último que lee el cliente."),
    Trigger("catalog_miss", "ceo", "shadow", 70,
            "La búsqueda en catálogo no devolvió nada: se pierde una venta."),
    Trigger("booking_clash", "ceo", "shadow", 60,
            "El horario pedido chocaba: hay que ofrecer alternativas que sirvan."),
    Trigger("dead_end", "ceo", "shadow", 50,
            "El turno terminó sin respuesta útil."),
    Trigger("stalled_sale", "ceo", "shadow", 30,
            "Conversación larga sin cerrar ni escalar."),
)

_POR_KEY = {t.key: t for t in TRIGGERS}

# Señales de indicación clínica en la respuesta del PROPIO bot. Solo aplican
# a empresas con el pack healthcare, donde dar posología es un riesgo real.
_CLINICO_RE = re.compile(
    r"\b\d+\s?(mg|ml|mcg|g)\b"
    r"|\bcada\s+\d+\s+horas?\b"
    r"|\b(tom[aá]|tomate|tom[aá]s|ingerí|aplicate|inyect)\w*\b.{0,40}\b(pastilla|comprimido|jarabe|dosis|antibi[oó]tic|ibuprofen|paracetamol|amoxicilin)"
    r"|\b(ten[eé]s|sufr[ií]s|es)\b.{0,15}\b(un cuadro de|una infecci[oó]n|covid|dengue|neumon[ií]a|gastritis)\b",
    re.IGNORECASE,
)

# Respuestas de relleno: el bot no aportó nada.
_SIN_CONTENIDO_RE = re.compile(
    r"^\s*(perdon[aá],?\s*¿?me repet[ií]s|no entend[ií]|disculp\w+,?\s*no)", re.IGNORECASE
)

_CIFRA_RE = re.compile(r"\d[\d.,]*")
# Sintaxis de herramienta que el modelo a veces escribe como texto plano.
_TOOL_TEXT_RE = re.compile(
    r"<\/?\s*(?:escalate_to_human|book_appointment|check_agenda|list_doctors|"
    r"search_catalog|list_services|function|tool)[^>]*>.*",
    re.DOTALL,
)

STALL_TURNOS = 6  # mensajes del cliente antes de considerar la venta estancada


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def detect(
    company: Company,
    *,
    actions: list[dict],
    reply_text: str,
    turnos_cliente: int,
    rondas_agotadas: bool,
) -> Trigger | None:
    """Decide, sin costo ni latencia, si este turno merece supervisión.

    Todo lo que mira son variables que el motor ya tiene resueltas cuando
    termina de responder. Devuelve como mucho UN disparador —el de mayor
    prioridad— porque supervisar dos cosas a la vez duplicaría el gasto sin
    duplicar el valor.
    """
    usadas = [a.get("tool", "") for a in actions]
    disparados: list[Trigger] = []

    activos = {p.key for p in packs.active_packs(company)}
    if "healthcare" in activos and _CLINICO_RE.search(reply_text or ""):
        disparados.append(_POR_KEY["compliance_risk"])

    if "escalate_to_human" in usadas:
        disparados.append(_POR_KEY["escalation_requested"])

    for a in actions:
        resultado = a.get("result") or {}
        if a.get("tool") == "search_catalog":
            # Ni resultados, o resultados que no son lo que el cliente pidió
            # (el catálogo devolvió "lo que hay" por no dejarlo sin respuesta).
            if not resultado.get("products") or not resultado.get("exact_match"):
                disparados.append(_POR_KEY["catalog_miss"])
        if a.get("tool") == "book_appointment" and "solapa" in str(resultado.get("error", "")):
            disparados.append(_POR_KEY["booking_clash"])

    if rondas_agotadas or not (reply_text or "").strip() or _SIN_CONTENIDO_RE.match(reply_text or ""):
        disparados.append(_POR_KEY["dead_end"])

    vendedora = bool({"search_catalog", "book_appointment"} & set(packs.tools_for(company)))
    cerro = any(t in usadas for t in ("book_appointment", "escalate_to_human"))
    # `==` y no `>=`: si se disparara en cada turno a partir del sexto, este
    # disparador —el menos grave de todos— se comería el presupuesto de la
    # conversación y dejaría sin cupo a un riesgo clínico posterior.
    if vendedora and turnos_cliente == STALL_TURNOS and not cerro:
        disparados.append(_POR_KEY["stalled_sale"])

    if not disparados:
        return None
    return max(disparados, key=lambda t: t.priority)


def arm_for(conversation_id: int, pct: int) -> str:
    """Reparte conversaciones entre supervisadas y control, de forma estable.

    La misma conversación cae siempre en el mismo brazo (si no, el cliente
    vería un turno supervisado y el siguiente no). Sin `random`: la decisión
    es reproducible y auditable.
    """
    if pct >= 100:
        return "supervised"
    if pct <= 0:
        return "control"
    return "supervised" if (conversation_id * 2654435761) % 100 < pct else "control"


def should_supervise(
    db: Session, company: Company, conversation: Conversation, trigger: Trigger
) -> tuple[bool, str, str]:
    """Puertas duras antes de gastar una llamada al modelo.

    Devuelve `(procede, modo_efectivo, motivo_degradación)`. El modo efectivo
    nunca supera al configurado en la empresa: un disparador que pide
    `inline` en una empresa en `shadow` se degrada a `shadow`, no se descarta
    —igual queda el registro para medir si convenía.
    """
    modo = (company.supervision or "off").strip().lower()
    if modo not in ("shadow", "inline"):
        return False, "", "supervisión apagada"

    if conversation.status == "needs_human" and trigger.key != "escalation_requested":
        # Ya está en manos de una persona: el bot no vuelve a opinar. La
        # excepción es el disparador que la escalación acaba de causar —el CX
        # marca `needs_human` durante este mismo turno, así que sin esta
        # excepción `escalation_requested` nunca podría dispararse.
        return False, "", "conversación ya escalada"

    agente = (
        db.query(Agent)
        .filter(Agent.company_id == company.id, Agent.slug == trigger.agent_slug)
        .first()
    )
    if agente and not agente.active:
        # Pausar el agente en el panel es el interruptor de emergencia.
        return False, "", f"agente {trigger.agent_slug} pausado"

    desde = _now() - timedelta(hours=24)
    por_conversacion = (
        db.query(Supervision)
        .filter(
            Supervision.conversation_id == conversation.id,
            Supervision.created_at >= desde,
            Supervision.arm == "supervised",
        )
        .count()
    )
    if por_conversacion >= MAX_POR_CONVERSACION:
        return False, "", "presupuesto de la conversación agotado"

    hoy = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    por_empresa = (
        db.query(Supervision)
        .filter(
            Supervision.company_id == company.id,
            Supervision.created_at >= hoy,
            Supervision.arm == "supervised",
        )
        .count()
    )
    if por_empresa >= MAX_POR_EMPRESA_DIA:
        return False, "", "presupuesto diario de la empresa agotado"

    degradacion = ""
    efectivo = trigger.mode
    if trigger.mode == "inline" and modo == "shadow":
        efectivo, degradacion = "shadow", "empresa en modo shadow"
    return True, efectivo, degradacion


def _prompt(company: Company, trigger: Trigger, cliente: str, respuesta: str, actions: list[dict]) -> list[dict]:
    resumen = "; ".join(
        f"{a.get('tool')}→{'ok' if (a.get('result') or {}).get('ok') else (a.get('result') or {}).get('error', 'sin datos')}"
        for a in actions
    ) or "no usó herramientas"
    sistema = (
        f"Sos el supervisor de calidad de {company.name} ({company.industry or company.niche}). "
        "Un agente de atención ya le respondió a un cliente por WhatsApp y detectamos "
        f"un problema: {trigger.reason}\n\n"
        "Tu trabajo es decidir qué hacer, con criterio comercial y humano. "
        "NO tenés herramientas: no podés consultar el catálogo, la agenda ni la base. "
        "Solo podés trabajar con lo que ves acá.\n\n"
        "REGLA DURA: no inventes precios, stock, horarios, promociones ni datos que no "
        "estén literalmente en la respuesta del agente o en el resultado de las herramientas. "
        "Si te falta un dato, no lo supongas: pedí que lo pregunte o escalá.\n\n"
        "Respondé SOLO un JSON con esta forma:\n"
        '{"action": "keep|rewrite|directive|escalate", "reply": "...", "directive": "...", "reason": "..."}\n'
        "- keep: la respuesta está bien, no la toques.\n"
        "- rewrite: devolvé en 'reply' el mensaje mejorado, listo para enviar tal cual.\n"
        "- directive: la respuesta se envía igual, pero en 'directive' dejás una "
        "instrucción breve para que el agente maneje mejor el PRÓXIMO mensaje.\n"
        "- escalate: esto necesita una persona; en 'reply' va qué se le dice al cliente mientras espera.\n"
        "'reason' es para nosotros, no para el cliente: una frase."
    )
    usuario = (
        f"Último mensaje del cliente:\n{cliente[:1500]}\n\n"
        f"Respuesta que dio el agente:\n{respuesta[:1500]}\n\n"
        f"Herramientas que usó: {resumen}"
    )
    return [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]


def _sanear(texto: str) -> str:
    return _TOOL_TEXT_RE.sub("", texto or "").strip()


def _cifras_inventadas(propuesta: str, fuentes: str) -> list[str]:
    """Números en la reescritura que no aparecen en el material de origen.

    Misma idea que el guard de campañas: el supervisor puede redactar mejor,
    pero no puede traer un precio nuevo de la nada.
    """
    permitidas = set(_CIFRA_RE.findall(fuentes))
    permitidas_planas = {c.replace(".", "").replace(",", "") for c in permitidas}
    inventadas = []
    for cifra in _CIFRA_RE.findall(propuesta or ""):
        plana = cifra.replace(".", "").replace(",", "")
        if len(plana) < 3:
            continue  # "2 opciones", "1 día": no es un dato duro
        if cifra not in permitidas and plana not in permitidas_planas:
            inventadas.append(cifra)
    return list(dict.fromkeys(inventadas))


def _parse_veredicto(crudo: str, respuesta_cx: str, fuentes: str) -> dict:
    """Convierte la salida del modelo en un veredicto seguro.

    Todo lo que no se pueda validar termina en `keep`: ante la duda, se envía
    lo que el CX ya había producido, que es lo que pasaría sin supervisión.
    """
    match = re.search(r"\{.*\}", crudo or "", re.DOTALL)
    if not match:
        return {"action": "keep", "reason": "el supervisor no devolvió JSON"}
    try:
        datos = json.loads(match.group())
    except json.JSONDecodeError:
        return {"action": "keep", "reason": "JSON inválido del supervisor"}
    if not isinstance(datos, dict):
        return {"action": "keep", "reason": "JSON inesperado del supervisor"}

    accion = str(datos.get("action", "")).strip().lower()
    if accion not in ACCIONES:
        return {"action": "keep", "reason": f"acción desconocida: {accion or 'vacía'}"}

    veredicto: dict = {"action": accion, "reason": str(datos.get("reason", ""))[:400]}
    directiva = _sanear(str(datos.get("directive", "")))[:MAX_DIRECTIVA_CHARS]
    if directiva:
        veredicto["directive"] = directiva

    if accion in ("rewrite", "escalate"):
        propuesta = _sanear(str(datos.get("reply", "")))
        if not propuesta:
            # Pidió reescribir pero no escribió nada: se queda lo del CX.
            veredicto["action"] = "escalate" if accion == "escalate" else "keep"
            veredicto["reason"] = (veredicto["reason"] + " | sin texto de reemplazo").strip(" |")
            veredicto.pop("reply", None)
            return veredicto
        if len(propuesta) > MAX_REPLY_CHARS:
            propuesta = propuesta[:MAX_REPLY_CHARS].rsplit(" ", 1)[0] + "…"
        inventadas = _cifras_inventadas(propuesta, f"{respuesta_cx}\n{fuentes}")
        if inventadas:
            veredicto["action"] = "escalate" if accion == "escalate" else "keep"
            veredicto["reason"] = f"cifras inventadas: {', '.join(inventadas[:3])}"
            veredicto.pop("reply", None)
            return veredicto
        veredicto["reply"] = propuesta

    if accion == "directive" and not veredicto.get("directive"):
        veredicto["action"] = "keep"
        veredicto["reason"] = "directiva vacía"
    return veredicto


async def review(
    db: Session,
    company: Company,
    conversation: Conversation,
    *,
    cliente: str,
    respuesta: str,
    actions: list[dict],
    turnos_cliente: int,
    rondas_agotadas: bool,
) -> dict:
    """Punto de entrada único. Devuelve qué cambia (si algo) en este turno.

    Contrato con el motor: `{"reply": str|None, "escalate": bool,
    "trigger": str, "action": str}`. `reply=None` significa "no toques nada".
    Nunca lanza: si la supervisión falla, el cliente igual recibe la
    respuesta del CX.
    """
    vacio = {"reply": None, "escalate": False, "trigger": "", "action": "keep"}
    if (company.supervision or "off").strip().lower() not in ("shadow", "inline"):
        return vacio  # ruta rápida: ni siquiera se evalúan los disparadores

    try:
        trigger = detect(
            company,
            actions=actions,
            reply_text=respuesta,
            turnos_cliente=turnos_cliente,
            rondas_agotadas=rondas_agotadas,
        )
        if not trigger:
            return vacio

        procede, modo, degradacion = should_supervise(db, company, conversation, trigger)
        if not procede:
            return vacio

        brazo = arm_for(conversation.id, company.supervision_pct or 0)
        if brazo == "control":
            # Rama de control: se registra el disparo para poder comparar, pero
            # no se gasta una llamada ni se toca nada.
            db.add(Supervision(
                company_id=company.id, conversation_id=conversation.id,
                trigger_key=trigger.key, agent_slug=trigger.agent_slug, mode=modo,
                arm="control", action="keep", reason=trigger.reason[:500],
            ))
            db.commit()
            return vacio

        agente = (
            db.query(Agent)
            .filter(Agent.company_id == company.id, Agent.slug == trigger.agent_slug)
            .first()
        )
        fuentes = json.dumps([a.get("result") for a in actions], ensure_ascii=False)
        empezo = time.monotonic()
        salida = await chat_raw(
            _prompt(company, trigger, cliente, respuesta, actions),
            tools=None,  # asesor sin herramientas: no puede reentrar al motor
            model=(agente.model if agente else None),
            temperature=0.2,
            max_tokens=700,
        )
        veredicto = _parse_veredicto(salida.get("content") or "", respuesta, fuentes)
        latencia = int((time.monotonic() - empezo) * 1000)

        aplicado = veredicto["action"]
        nueva_respuesta = None
        escalar = False
        if modo == "inline":
            if veredicto["action"] == "rewrite":
                nueva_respuesta = veredicto.get("reply")
            elif veredicto["action"] == "escalate":
                escalar = True
                nueva_respuesta = veredicto.get("reply")
        elif veredicto["action"] in ("rewrite", "escalate"):
            # En shadow nada toca al cliente en este turno: solo se registra.
            aplicado = "keep"
            degradacion = (degradacion or "modo shadow") + f" (propuso {veredicto['action']})"

        # La directiva sí vale en ambos modos: mejora el PRÓXIMO turno, que es
        # exactamente lo que shadow puede aportar sin arriesgar nada.
        if veredicto.get("directive"):
            conversation.pending_directive = veredicto["directive"][:MAX_DIRECTIVA_CHARS]

        db.add(Supervision(
            company_id=company.id, conversation_id=conversation.id,
            trigger_key=trigger.key, agent_slug=trigger.agent_slug, mode=modo,
            arm="supervised", action=aplicado, reason=veredicto.get("reason", "")[:500],
            downgraded=degradacion[:120], latency_ms=latencia,
        ))
        db.commit()
        logger.info(
            "supervisión %s/%s: %s → %s (%sms)",
            company.id, trigger.key, veredicto["action"], aplicado, latencia,
        )
        return {
            "reply": nueva_respuesta,
            "escalate": escalar,
            "trigger": trigger.key,
            "action": aplicado,
        }
    except Exception:
        # Supervisar es una mejora, no un requisito: si falla, el cliente
        # recibe igual la respuesta del CX.
        logger.exception("falló la supervisión de la empresa %s", company.id)
        db.rollback()
        return vacio
