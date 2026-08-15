"""Nota de voz que entra, resumen hablado que sale.

Existe por cómo se usa WhatsApp acá: mucha gente manda audios y no escribe.
Un bot que solo entiende texto deja afuera a una parte de sus clientes, y a
un dueño manejando que quiere saber cómo viene el mes.

Tres decisiones que valen más que el código:

1. **Se transcribe, y después sigue el camino de siempre.** El audio no abre
   una vía paralela: se vuelve texto y entra por `handle_incoming`, con las
   mismas herramientas, los mismos permisos y los mismos guardias. Una
   segunda vía sería una segunda oportunidad de saltearse un control.

2. **Los límites son de plata, no de prolijidad.** Transcribir se cobra por
   minuto. Sin tope, alguien manda un audio de dos horas —o mil de diez
   segundos— y la cuenta la paga el dueño del negocio.

3. **El modelo sale de la lista blanca de `config`.** Acá no se elige ninguno.

La clave nunca se registra, ni siquiera en un error: los mensajes de la API
se limpian antes de guardarse.
"""
import logging
import re

import httpx

from .config import (
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_MODELOS_PERMITIDOS,
    OPENAI_TRANSCRIPTION_MODEL,
    OPENAI_TTS_MODEL,
)

logger = logging.getLogger("metabot.audio")

# Una nota de voz de WhatsApp de un minuto pesa ~100 KB. 8 MB deja lugar de
# sobra para un audio largo y corta el archivo que no es una nota de voz.
MAXIMO_BYTES = 8 * 1024 * 1024

# Lo que se manda a hablar. Un resumen financiero por voz de más de esto ya
# no se escucha: se lee. Y cada carácter se cobra.
MAXIMO_CARACTERES_TTS = 1200

# La voz. `alloy` es neutra; una voz muy marcada le pone una personalidad al
# negocio que el negocio no eligió.
VOZ = "alloy"

_CREDENCIAL_RE = re.compile(r"sk-[A-Za-z0-9_\-]+")


class AudioError(Exception):
    """Falla al transcribir o al hablar. El motivo ya viene limpio."""


def _limpiar(texto: str) -> str:
    """Saca cualquier cosa con forma de credencial antes de que se registre."""
    return _CREDENCIAL_RE.sub("sk-<OCULTA>", texto or "")[:300]


def disponible() -> bool:
    return bool(OPENAI_API_KEY)


async def transcribir(datos: bytes, nombre: str = "nota.ogg") -> str:
    """Audio a texto. Devuelve lo dicho, o explota con el motivo.

    No adivina ni completa: si el audio no se entiende, el modelo devuelve
    poco o nada y quien llama decide qué hacer. Rellenar un audio inaudible
    con una suposición es cómo se agenda un turno que nadie pidió.
    """
    if not disponible():
        raise AudioError("No hay credencial de OpenAI configurada.")
    if not datos:
        raise AudioError("El audio llegó vacío.")
    if len(datos) > MAXIMO_BYTES:
        raise AudioError(
            f"El audio pesa más de {MAXIMO_BYTES // (1024 * 1024)} MB."
        )
    # Defensa en profundidad: el modelo ya sale de la lista blanca en config,
    # pero si alguien la cambia sin pensar, acá se frena igual.
    if OPENAI_TRANSCRIPTION_MODEL not in OPENAI_MODELOS_PERMITIDOS:
        raise AudioError("El modelo de transcripción no está autorizado.")

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{OPENAI_BASE_URL}/audio/transcriptions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                files={"file": (nombre, datos, "application/octet-stream")},
                data={
                    "model": OPENAI_TRANSCRIPTION_MODEL,
                    # Se fija el idioma: sin esto, un audio corto en castellano
                    # paraguayo con una palabra en guaraní a veces se detecta
                    # como portugués y vuelve traducido.
                    "language": "es",
                },
            )
            r.raise_for_status()
            return (r.json().get("text") or "").strip()
    except httpx.HTTPStatusError as exc:
        raise AudioError(
            f"La transcripción falló ({exc.response.status_code}): "
            f"{_limpiar(exc.response.text)}"
        )
    except httpx.HTTPError as exc:
        raise AudioError(f"No se pudo transcribir: {type(exc).__name__}")


async def hablar(texto: str) -> bytes:
    """Texto a audio. Devuelve un OGG/Opus, que es lo que manda WhatsApp."""
    if not disponible():
        raise AudioError("No hay credencial de OpenAI configurada.")
    limpio = (texto or "").strip()
    if not limpio:
        raise AudioError("No hay nada que decir.")
    if OPENAI_TTS_MODEL not in OPENAI_MODELOS_PERMITIDOS:
        raise AudioError("El modelo de voz no está autorizado.")

    # Se corta, no se rechaza: quedarse sin respuesta hablada por diez
    # caracteres de más es peor que escuchar un resumen recortado.
    if len(limpio) > MAXIMO_CARACTERES_TTS:
        limpio = limpio[:MAXIMO_CARACTERES_TTS].rsplit(" ", 1)[0] + "…"

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{OPENAI_BASE_URL}/audio/speech",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                json={
                    "model": OPENAI_TTS_MODEL,
                    "voice": VOZ,
                    "input": limpio,
                    "response_format": "opus",
                },
            )
            r.raise_for_status()
            return r.content
    except httpx.HTTPStatusError as exc:
        raise AudioError(
            f"La voz falló ({exc.response.status_code}): "
            f"{_limpiar(exc.response.text)}"
        )
    except httpx.HTTPError as exc:
        raise AudioError(f"No se pudo generar el audio: {type(exc).__name__}")


def para_hablar(texto: str) -> str:
    """Deja el texto listo para leerse en voz alta.

    Lo escrito y lo hablado no son lo mismo. `₲ 8.550.000` leído por un
    sintetizador sale como "guaraní ocho cinco cinco cero"; los guiones de una
    lista se leen; y un enlace dictado carácter por carácter es medio minuto
    de ruido que además nadie va a poder anotar.
    """
    t = texto or ""
    # El enlace no se dicta: se manda aparte, por escrito.
    t = re.sub(r"https?://\S+", "", t)
    # Montos: 8.550.000 → 8 millones 550 mil. Se dice como lo diría una
    # persona, no como lo escribiría una planilla.
    def _monto(m):
        crudo = m.group(1).replace(".", "")
        try:
            n = int(crudo)
        except ValueError:
            return m.group(0)
        if n >= 1_000_000:
            millones, resto = divmod(n, 1_000_000)
            miles = resto // 1000
            texto_m = f"{millones} millones" if millones != 1 else "un millón"
            if miles:
                texto_m += f" {miles} mil"
            return texto_m + " de guaraníes"
        if n >= 1000:
            return f"{n // 1000} mil guaraníes"
        return f"{n} guaraníes"

    t = re.sub(r"₲\s*([\d.]+)", _monto, t)
    t = t.replace("₲", "guaraníes ")
    # Viñetas y saltos dobles: se leen como pausas, no como caracteres.
    t = re.sub(r"^\s*[-*•]\s*", "", t, flags=re.MULTILINE)
    t = re.sub(r"\n{2,}", ". ", t)
    t = t.replace("\n", ". ")
    return re.sub(r"\s{2,}", " ", t).strip()
