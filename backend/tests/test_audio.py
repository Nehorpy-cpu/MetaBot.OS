"""CFO — Fase 7: la nota de voz.

Existe por cómo se usa WhatsApp acá: mucha gente manda audios y no escribe.
Lo que se prueba no es que la API de OpenAI ande —eso es problema de ellos—
sino los límites y las traducciones que decidimos nosotros: que un audio
enorme no salga a cobrarse, que el modelo salga de la lista blanca, que la
credencial no termine en un log, y que un monto leído en voz alta se entienda.
"""
import pytest

from app import audio, config


# ─── Lo que se cobra ─────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_un_audio_enorme_no_llega_a_la_api(monkeypatch, anyio_backend):
    """Transcribir se cobra por minuto. Sin tope, alguien manda un audio de
    dos horas y la cuenta la paga el dueño del negocio."""
    llamadas = []
    monkeypatch.setattr(audio.httpx, "AsyncClient",
                        lambda **kw: llamadas.append(1))
    monkeypatch.setattr(audio, "OPENAI_API_KEY", "no-se-usa")

    with pytest.raises(audio.AudioError) as exc:
        await audio.transcribir(b"x" * (audio.MAXIMO_BYTES + 1))
    assert "MB" in str(exc.value)
    assert not llamadas, "salió a la API igual"


@pytest.mark.anyio
async def test_un_audio_vacio_no_llega_a_la_api(monkeypatch, anyio_backend):
    monkeypatch.setattr(audio, "OPENAI_API_KEY", "no-se-usa")
    with pytest.raises(audio.AudioError):
        await audio.transcribir(b"")


@pytest.mark.anyio
async def test_hablar_recorta_en_vez_de_rechazar(monkeypatch, anyio_backend):
    """Quedarse sin respuesta hablada por diez caracteres de más es peor que
    escuchar un resumen recortado."""
    enviado = {}

    class _R:
        content = b"OggS-falso"

        @staticmethod
        def raise_for_status():
            return None

    class _C:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kw):
            enviado.update(kw.get("json", {}))
            return _R()

    monkeypatch.setattr(audio, "OPENAI_API_KEY", "no-se-usa")
    monkeypatch.setattr(audio.httpx, "AsyncClient", lambda **kw: _C())

    salida = await audio.hablar("hola " * 1000)
    assert salida == b"OggS-falso"
    assert len(enviado["input"]) <= audio.MAXIMO_CARACTERES_TTS + 1


# ─── La lista blanca también rige acá ────────────────────────────────────


def test_los_modelos_de_audio_estan_en_la_lista_blanca():
    assert config.OPENAI_TRANSCRIPTION_MODEL in config.OPENAI_MODELOS_PERMITIDOS
    assert config.OPENAI_TTS_MODEL in config.OPENAI_MODELOS_PERMITIDOS


@pytest.mark.anyio
async def test_un_modelo_de_audio_no_autorizado_no_sale(monkeypatch, anyio_backend):
    """Defensa en profundidad: si alguien cambia la lista sin pensar, acá se
    frena igual."""
    monkeypatch.setattr(audio, "OPENAI_API_KEY", "no-se-usa")
    monkeypatch.setattr(audio, "OPENAI_TRANSCRIPTION_MODEL", "whisper-1")
    with pytest.raises(audio.AudioError) as exc:
        await audio.transcribir(b"audio")
    assert "no está autorizado" in str(exc.value)

    monkeypatch.setattr(audio, "OPENAI_TTS_MODEL", "tts-1-hd")
    with pytest.raises(audio.AudioError) as exc:
        await audio.hablar("hola")
    assert "no está autorizado" in str(exc.value)


@pytest.mark.anyio
async def test_sin_credencial_no_se_intenta(monkeypatch, anyio_backend):
    monkeypatch.setattr(audio, "OPENAI_API_KEY", "")
    with pytest.raises(audio.AudioError):
        await audio.transcribir(b"audio")
    with pytest.raises(audio.AudioError):
        await audio.hablar("hola")


def test_un_error_no_arrastra_la_credencial():
    """Un mensaje de error de la API a veces repite lo que se le mandó."""
    sucio = "Incorrect API key provided: sk-proj-ABCDEF123456. Check your key."
    assert "sk-proj-ABCDEF123456" not in audio._limpiar(sucio)
    assert "sk-<OCULTA>" in audio._limpiar(sucio)


# ─── Lo escrito y lo hablado no son lo mismo ─────────────────────────────


def test_un_monto_se_dice_como_lo_diria_una_persona():
    """`₲ 8.550.000` leído por un sintetizador sale como "guaraní ocho cinco
    cinco cero"."""
    dicho = audio.para_hablar("Vendiste ₲ 8.550.000 este mes.")
    assert "8 millones 550 mil de guaraníes" in dicho
    assert "8.550.000" not in dicho


def test_un_millon_se_dice_en_singular():
    assert "un millón" in audio.para_hablar("₲ 1.200.000")


def test_los_miles_solos_tambien():
    assert "180 mil guaraníes" in audio.para_hablar("₲ 180.000")


def test_el_enlace_no_se_dicta():
    """Dictar una URL carácter por carácter es medio minuto de ruido que
    además nadie va a poder anotar. El enlace va aparte, por escrito."""
    dicho = audio.para_hablar(
        "Te dejo el detalle acá: https://botscomercio.com/r/abc123XYZ"
    )
    assert "http" not in dicho
    assert "abc123XYZ" not in dicho
    assert "Te dejo el detalle acá" in dicho


def test_las_vinetas_no_se_leen():
    dicho = audio.para_hablar("- Ventas: ₲ 100.000\n- Gastos: ₲ 50.000")
    assert "-" not in dicho
    assert "Ventas" in dicho and "Gastos" in dicho


def test_no_quedan_saltos_de_linea_sueltos():
    dicho = audio.para_hablar("Primera línea.\n\nSegunda línea.")
    assert "\n" not in dicho


# ─── La nota de voz entrando por el canal ────────────────────────────────
#
# Lo que se prueba acá es que el audio NO abra una vía paralela: se vuelve
# texto y entra por el mismo camino, con los mismos permisos y los mismos
# guardias. Una segunda vía sería una segunda oportunidad de saltearse un
# control.

import base64  # noqa: E402

from tests.test_api import _create_company, client  # noqa: E402, I001
from app.db import SessionLocal  # noqa: E402
from app.models import Company, Message  # noqa: E402


def _empresa_qr(nombre: str) -> int:
    cid = _create_company(name=nombre)["id"]
    db = SessionLocal()
    try:
        db.get(Company, cid).wa_mode = "qr"
        db.commit()
    finally:
        db.close()
    return cid


def _mandar(cid: int, **extra):
    from app.config import BRIDGE_SECRET

    cuerpo = {"company_id": cid, "from": "+595981123456", "name": "Cliente",
              "text": "", **extra}
    return client.post("/api/webhooks/bridge", json=cuerpo,
                       headers={"X-Bridge-Secret": BRIDGE_SECRET})


def test_una_nota_de_voz_se_transcribe_y_sigue_el_camino_de_siempre(monkeypatch):
    vistos = {}

    async def _transcribir(datos, nombre="nota.ogg"):
        vistos["bytes"] = len(datos)
        return "quiero un turno para mañana"

    async def _handle(db, company, phone, texto, **kw):
        vistos["texto"] = texto
        return {"reply": "Listo.", "status": "ok"}

    monkeypatch.setattr("app.audio.transcribir", _transcribir)
    monkeypatch.setattr("app.chat.handle_incoming", _handle)

    cid = _empresa_qr("Audio Camino Feliz")
    r = _mandar(cid, audio_base64=base64.b64encode(b"OggS-falso").decode())
    assert r.status_code == 200, r.text
    assert vistos["texto"] == "quiero un turno para mañana"
    assert vistos["bytes"] == len(b"OggS-falso")


def test_un_audio_que_no_se_entiende_recibe_respuesta_igual(monkeypatch):
    """Del otro lado hay alguien esperando: el silencio del bot se lee como
    que el negocio no atiende."""
    from app import audio as _audio

    async def _falla(datos, nombre="nota.ogg"):
        raise _audio.AudioError("no se pudo transcribir")

    monkeypatch.setattr("app.audio.transcribir", _falla)
    cid = _empresa_qr("Audio Ilegible")
    r = _mandar(cid, audio_base64=base64.b64encode(b"ruido").decode())
    assert r.status_code == 200
    assert r.json()["status"] == "audio_ilegible"
    assert "repetís" in r.json()["reply"] or "escribís" in r.json()["reply"]


def test_un_audio_en_silencio_no_dispara_una_conversacion_vacia(monkeypatch):
    async def _vacio(datos, nombre="nota.ogg"):
        return "   "

    monkeypatch.setattr("app.audio.transcribir", _vacio)
    cid = _empresa_qr("Audio Silencio")
    r = _mandar(cid, audio_base64=base64.b64encode(b"silencio").decode())
    assert r.json()["status"] == "audio_vacio"


def test_un_base64_roto_se_rechaza_sin_llamar_a_la_api(monkeypatch):
    llamadas = []

    async def _no_deberia(datos, nombre="nota.ogg"):
        llamadas.append(1)
        return ""

    monkeypatch.setattr("app.audio.transcribir", _no_deberia)
    cid = _empresa_qr("Audio Base64 Roto")
    assert _mandar(cid, audio_base64="esto no es base64 %%%").status_code == 422
    assert not llamadas


def test_un_mensaje_sin_texto_ni_audio_se_rechaza():
    cid = _empresa_qr("Audio Nada")
    assert _mandar(cid).status_code == 422


def test_si_preguntaron_por_audio_se_contesta_tambien_por_audio(monkeypatch):
    async def _transcribir(datos, nombre="nota.ogg"):
        return "cuanto vendi"

    async def _handle(db, company, phone, texto, **kw):
        return {"reply": "Vendiste ₲ 8.550.000.", "status": "ok"}

    async def _hablar(texto):
        assert "8 millones" in texto, "no se preparó el texto para leerse"
        return b"OggS-respuesta"

    monkeypatch.setattr("app.audio.transcribir", _transcribir)
    monkeypatch.setattr("app.chat.handle_incoming", _handle)
    monkeypatch.setattr("app.audio.hablar", _hablar)

    cid = _empresa_qr("Audio Ida Y Vuelta")
    r = _mandar(cid, audio_base64=base64.b64encode(b"OggS").decode()).json()
    # El texto va SIEMPRE: un monto que se escucha una vez no se puede volver
    # a mirar.
    assert r["reply"] == "Vendiste ₲ 8.550.000."
    assert base64.b64decode(r["audio_base64"]) == b"OggS-respuesta"


def test_si_falla_la_voz_igual_llega_la_respuesta_escrita(monkeypatch):
    from app import audio as _audio

    async def _transcribir(datos, nombre="nota.ogg"):
        return "hola"

    async def _handle(db, company, phone, texto, **kw):
        return {"reply": "Hola, ¿en qué te ayudo?", "status": "ok"}

    async def _falla(texto):
        raise _audio.AudioError("sin cupo")

    monkeypatch.setattr("app.audio.transcribir", _transcribir)
    monkeypatch.setattr("app.chat.handle_incoming", _handle)
    monkeypatch.setattr("app.audio.hablar", _falla)

    cid = _empresa_qr("Audio Voz Caida")
    r = _mandar(cid, audio_base64=base64.b64encode(b"OggS").decode()).json()
    assert r["reply"] == "Hola, ¿en qué te ayudo?"
    assert "audio_base64" not in r


def test_un_mensaje_de_texto_no_genera_audio(monkeypatch):
    """Hablar se cobra. Quien escribe no pidió que le contesten hablando."""
    llamadas = []

    async def _handle(db, company, phone, texto, **kw):
        return {"reply": "Listo.", "status": "ok"}

    async def _hablar(texto):
        llamadas.append(1)
        return b""

    monkeypatch.setattr("app.chat.handle_incoming", _handle)
    monkeypatch.setattr("app.audio.hablar", _hablar)

    cid = _empresa_qr("Audio Solo Texto")
    r = _mandar(cid, text="hola").json()
    assert "audio_base64" not in r
    assert not llamadas
