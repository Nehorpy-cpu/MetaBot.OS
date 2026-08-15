"""Capa de abstracción LLM con fallback entre proveedores OpenAI-compatibles.

Se usa el primer proveedor con API key configurada; si falla (error de red,
rate limit, 5xx), se intenta el siguiente. Así el sistema no queda atado a
NVIDIA NIM: sirve Groq u OpenRouter con el mismo código.
"""
import logging

import httpx

from .config import LLM_PROVIDERS, OPENAI_MODELOS_PERMITIDOS, OPENAI_TEXT_MODEL

logger = logging.getLogger("metabot.llm")


class LLMError(Exception):
    pass


# --- Model Router: se elige modelo por TAREA, no por marca ---
#
# Regla explícita del proyecto: quien audita no debe ser el mismo modelo que
# produjo la salida. Un proveedor entra o sale según resultados, cambiando
# solo esta tabla.
#
# Cada modelo declara EN QUÉ PROVEEDOR vive. Sin esto el router era
# decorativo: `chat_raw` recorría los proveedores en orden fijo y, si el
# primero no conocía el modelo, reintentaba con el modelo por defecto de ESE
# MISMO proveedor antes de pasar al siguiente. Medido en el VPS el
# 11-ago-2026: pedir "openai/gpt-oss-120b" (que solo existe en Groq, donde
# responde en 0,8s) tardaba 58,9s porque terminaba corriendo el modelo de
# NVIDIA, y nadie se enteraba.
PROVEEDOR_DE_MODELO: dict[str, str] = {
    "openai/gpt-oss-120b": "groq",
    "openai/gpt-oss-20b": "groq",
    "llama-3.3-70b-versatile": "groq",
    "llama-3.1-8b-instant": "groq",
    "qwen/qwen3.6-27b": "groq",
    "nvidia/llama-3.3-nemotron-super-49b-v1.5": "nvidia",
    "meta/llama-3.3-70b-instruct": "nvidia",
    "meta/llama-3.1-70b-instruct": "nvidia",
    "meta/llama-3.1-8b-instruct": "nvidia",
    "mistralai/mistral-large-2-instruct": "nvidia",
    OPENAI_TEXT_MODEL: "openai",
}

# Cadena de candidatos por tarea, en orden de preferencia. Si el primero no
# está disponible (sin API key, caído, o sin cupo) se pasa al siguiente, que
# es un modelo DISTINTO en otro proveedor —no el default silencioso de antes.
TASK_MODELS: dict[str, list[str]] = {
    # Conversación con cliente: manda la latencia. Medido en producción con el
    # prompt real y las 7 herramientas, turno completo (rondas + respuesta):
    #   groq/gpt-oss-120b            0,8s – 2,2s
    #   nvidia/nemotron-super-49b   17,3s – 71,4s   (el que estaba)
    #   nvidia/llama-3.1-70b        82,2s – 164,6s
    # El nemotron es un modelo de razonamiento: gasta el presupuesto pensando
    # antes de contestar "¿te refieres a una consulta?". En WhatsApp eso es
    # medio minuto mirando el celular.
    # El orden importa por el cupo, no solo por la velocidad. Medido en los
    # headers x-ratelimit del free tier de Groq el 11-ago-2026:
    #   gpt-oss-120b y gpt-oss-20b COMPARTEN un bucket de 8.000 tokens/minuto
    #     (los dos devuelven el mismo `remaining`), así que encadenarlos no
    #     sirve de nada: cuando uno da 429, el otro también.
    #   llama-3.3-70b-versatile tiene bucket PROPIO de 12.000 tokens/minuto.
    # Por eso el respaldo inmediato es el 70b y no el 20b, aunque el 70b a
    # veces rechace el esquema de herramientas con un 400: si lo rechaza se
    # pasa al siguiente, y sale mucho más barato que caer al de 40 segundos.
    #
    # Un turno gasta ~2.500 tokens, o sea ~3 turnos por minuto por bucket. Para
    # una clínica arrancando alcanza; para varias en paralelo hay que pasar al
    # tier pago de Groq.
    "cx": ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "openai/gpt-oss-20b",
           "nvidia/llama-3.3-nemotron-super-49b-v1.5"],
    # Razonamiento/planificación: acá sí conviene el que piensa.
    "reasoning": ["nvidia/llama-3.3-nemotron-super-49b-v1.5", "openai/gpt-oss-120b"],
    # Auditoría: modelo DISTINTO al que produce, para no auto-aprobarse.
    "audit": ["meta/llama-3.3-70b-instruct", "llama-3.3-70b-versatile"],
    # Supervisión de turnos: también distinto al del CX. Corre fuera de la
    # espera del cliente, pero comparte el worker con los recordatorios.
    "supervision": ["meta/llama-3.1-70b-instruct", "llama-3.3-70b-versatile"],
    # Redacción creativa
    "creative": ["mistralai/mistral-large-2-instruct", "openai/gpt-oss-120b"],
    # Extracción estructurada de datos (catálogo, perfiles)
    "extraction": ["meta/llama-3.3-70b-instruct", "openai/gpt-oss-120b"],
    # Finanzas. Va aparte de "cx" por una razón medida, no por prolijidad:
    # los modelos gratuitos de Groq no llaman a la herramienta de forma
    # confiable. El 15-ago-2026, ante "cuánto vendí este mes", gpt-oss-120b
    # no la llamó en ninguna prueba y contestó de memoria. Sin llamada
    # tampoco corre la verificación de permiso — o sea que ahí no se pierde
    # un número, se pierde el control de acceso.
    #
    # Por eso acá se paga: el modelo de OpenAI va primero, y los gratuitos
    # quedan de respaldo por si la clave falla o se acaba el crédito. Es la
    # única tarea del sistema que arranca con un modelo pago.
    "finanzas": [OPENAI_TEXT_MODEL, "openai/gpt-oss-120b",
                 "llama-3.3-70b-versatile"],
}


def model_for(task: str, override: str | None = None) -> str | None:
    """Modelo a usar para una tarea. `override` (config del agente) gana."""
    if override:
        return override
    candidatos = TASK_MODELS.get(task) or []
    return candidatos[0] if candidatos else None


def cadena_para(task: str, override: str | None = None) -> list[str]:
    """Modelos a intentar, en orden. El override del agente va primero pero NO
    anula la cadena: si ese modelo falla, se sigue con los de la tarea."""
    candidatos = list(TASK_MODELS.get(task) or [])
    if override and override not in candidatos:
        candidatos.insert(0, override)
    elif override:
        candidatos.remove(override)
        candidatos.insert(0, override)
    return candidatos


def available_providers() -> list[dict]:
    return [p for p in LLM_PROVIDERS if p["api_key"]]


async def chat_raw(
    messages: list[dict],
    *,
    tools: list[dict] | None = None,
    model: str | None = None,
    models: list[str] | None = None,
    temperature: float = 0.3,
    max_tokens: int = 1024,
    # 120s: los modelos serverless de NIM pueden tardar ~1 min en arrancar
    # en frío; mejor esperar que caer en fallback innecesario.
    timeout: float = 120.0,
    json_mode: bool = False,
) -> dict:
    """Devuelve el mensaje completo del asistente (puede incluir tool_calls).

    `models` es la cadena de candidatos en orden; `model` es el atajo de uno
    solo. El mensaje devuelto trae `_modelo_usado` y `_proveedor_usado`: si
    hubo fallback, hay que registrar quién contestó de verdad.
    """
    providers = available_providers()
    if not providers:
        raise LLMError(
            "Ningún proveedor LLM configurado. Definí NVIDIA_API_KEY, "
            "GROQ_API_KEY u OPENROUTER_API_KEY en .env"
        )
    por_nombre = {p["name"]: p for p in providers}
    # Un intento = (proveedor, modelo). Cada modelo va a SU proveedor; si no
    # sabemos dónde vive, se prueba en todos. Lo que ya no pasa es sustituirlo
    # en silencio por el modelo por defecto de otro proveedor.
    pedidos = models or ([model] if model else [])
    intentos: list[tuple[dict, str]] = []
    for candidato in pedidos:
        duenio = PROVEEDOR_DE_MODELO.get(candidato)
        if duenio and duenio in por_nombre:
            intentos.append((por_nombre[duenio], candidato))
        elif duenio:
            continue  # su proveedor no tiene API key: ni lo intentamos
        else:
            intentos.extend((p, candidato) for p in providers)
    if not intentos:
        if pedidos:
            # Se pidieron modelos concretos y ninguno tiene proveedor
            # disponible. Caer al modelo por defecto de cualquiera sería la
            # sustitución silenciosa que este módulo dejó de hacer: el
            # llamador cree que corrió lo que pidió y las métricas mienten.
            raise LLMError(
                "Ningún proveedor configurado tiene los modelos pedidos "
                f"({', '.join(pedidos)}). Configurá su API key o cambiá la "
                "cadena en TASK_MODELS."
            )
        intentos = [(p, p["default_model"]) for p in providers]

    # El punto único por donde pasa TODA llamada a un modelo. Acá se aplica la
    # lista blanca de OpenAI, y acá sola: repartida por el código, un camino
    # nuevo se olvidaría de mirarla.
    #
    # La clave de OpenAI habilita 124 modelos, entre ellos `sora-2`,
    # `gpt-image-2` y los `-pro`. El sistema tiene autorizados tres —texto,
    # voz a texto, texto a voz— y ninguno de los otros sale de acá aunque
    # alguien lo pida por config, por override de agente o por un descuido.
    intentos = [
        (p, m) for p, m in intentos
        if p["name"] != "openai" or m in OPENAI_MODELOS_PERMITIDOS
    ]
    if not intentos:
        raise LLMError(
            "Los modelos pedidos no están autorizados. En OpenAI solo se "
            f"permiten: {', '.join(sorted(OPENAI_MODELOS_PERMITIDOS))}."
        )

    errors: list[str] = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        for p, modelo in intentos:
            payload: dict = {
                "model": modelo,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if tools:
                payload["tools"] = tools
            if json_mode:
                # Salida JSON forzada (OpenAI-compatible). Si el proveedor no
                # lo soporta, se reintenta sin el parámetro más abajo.
                payload["response_format"] = {"type": "json_object"}
            try:
                resp = await client.post(
                    f"{p['base_url']}/chat/completions",
                    headers={"Authorization": f"Bearer {p['api_key']}"},
                    json=payload,
                )
                if json_mode and resp.status_code in (400, 422):
                    payload.pop("response_format", None)
                    resp = await client.post(
                        f"{p['base_url']}/chat/completions",
                        headers={"Authorization": f"Bearer {p['api_key']}"},
                        json=payload,
                    )
                resp.raise_for_status()
                mensaje = resp.json()["choices"][0]["message"]
                # Un modelo de razonamiento puede gastar todo `max_tokens`
                # pensando y devolver contenido VACÍO sin tool_calls. Al
                # llamador eso le llega como "no supo qué contestar" y el
                # paciente recibe "¿me repetís eso último?". Si hay otro
                # candidato, se prueba con ese en vez de dar por buena una
                # respuesta que no existe.
                vacio = not (mensaje.get("content") or "").strip() and not mensaje.get("tool_calls")
                if vacio and (p, modelo) != intentos[-1]:
                    errors.append(f"{p['name']}/{modelo}: respondió vacío")
                    continue
                # Quién contestó DE VERDAD. Antes se guardaba en agent_runs el
                # modelo pedido, así que si hubo fallback la métrica mentía y
                # las decisiones de latencia se tomaban sobre datos falsos.
                mensaje["_modelo_usado"] = modelo
                mensaje["_proveedor_usado"] = p["name"]
                if errors:
                    logger.warning(
                        "LLM: respondió %s/%s tras fallar %s",
                        p["name"], modelo, "; ".join(errors),
                    )
                return mensaje
            except (httpx.HTTPError, KeyError, IndexError) as exc:
                # type(exc) SIEMPRE visible: str(ReadTimeout) es vacío y
                # ocultaba la causa real en producción.
                detalle = f"{type(exc).__name__}: {exc}"
                # Y el CUERPO de la respuesta cuando el proveedor rechaza el
                # pedido. Un 400 sin cuerpo no se puede diagnosticar: se veía
                # "Client error '400'" en el log y había que adivinar qué de
                # lo que mandamos no le gustó. El proveedor lo dice ahí.
                respuesta = getattr(exc, "response", None)
                if respuesta is not None:
                    try:
                        cuerpo = respuesta.json()
                        motivo = (
                            cuerpo.get("error", {}).get("message")
                            if isinstance(cuerpo.get("error"), dict)
                            else cuerpo.get("error") or cuerpo.get("detail")
                        )
                    except Exception:  # noqa: BLE001 — el cuerpo puede no ser JSON
                        motivo = (getattr(respuesta, "text", "") or "")[:300]
                    if motivo:
                        detalle = (
                            f"{type(exc).__name__} "
                            f"{getattr(respuesta, 'status_code', '?')}: {motivo}"
                        )
                errors.append(f"{p['name']}/{modelo}: {detalle}")
    raise LLMError("Todos los proveedores fallaron: " + "; ".join(errors))


async def complete(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 1024,
    timeout: float = 60.0,
    json_mode: bool = False,
) -> str:
    """Devuelve solo el texto de respuesta."""
    message = await chat_raw(
        messages, model=model, temperature=temperature, max_tokens=max_tokens,
        timeout=timeout, json_mode=json_mode,
    )
    return message.get("content") or ""
