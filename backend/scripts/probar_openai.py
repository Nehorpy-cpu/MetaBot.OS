"""Comprobación de acceso a OpenAI. No imprime la clave ni datos del negocio.

Distingue dos cosas que se confunden todo el tiempo:

- que un modelo EXISTA en el catálogo de OpenAI;
- que ESTA clave, en ESTE proyecto, tenga acceso efectivo a él.

Lo segundo es lo único que sirve para decidir, y solo se sabe llamándolo.

Uso:
    OPENAI_API_KEY=... python scripts/probar_openai.py
    # o, en local:
    python scripts/probar_openai.py --env-file ../GPTAPI.env
"""
import argparse
import io
import os
import sys
import time

import httpx

BASE = "https://api.openai.com/v1"

# Los identificadores que el CFO tiene configurados. Se prueban de a uno: un
# proyecto puede tener acceso a unos y no a otros.
CHAT = [
    ("OPENAI_CFO_ROUTER_MODEL", "gpt-5.6-luna"),
    ("OPENAI_CFO_DEFAULT_MODEL", "gpt-5.6-terra"),
    ("OPENAI_CFO_DEEP_MODEL", "gpt-5.6-sol"),
]
OTROS = [
    ("OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe"),
    ("OPENAI_TRANSCRIPTION_HIGH_ACCURACY_MODEL", "gpt-4o-transcribe"),
    ("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
]

# Frase neutra, sin un solo dato de ninguna empresa.
SONDA = "Prueba tecnica de disponibilidad."


def _clave(env_file: str | None) -> str:
    if env_file:
        for linea in io.open(env_file, encoding="utf-8"):
            linea = linea.strip()
            if linea.startswith("OPENAI_API_KEY="):
                return linea.split("=", 1)[1].strip()
            # Tolera el archivo con el token suelto, sin nombre de variable.
            if linea and not linea.startswith("#") and "=" not in linea:
                return linea
    return os.environ.get("OPENAI_API_KEY", "")


def _sanitizar(exc: Exception) -> str:
    """El motivo del error SIN encabezados, cuerpo crudo ni la clave."""
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            cuerpo = exc.response.json().get("error", {})
            return f"{exc.response.status_code} {cuerpo.get('code') or cuerpo.get('type') or ''}".strip()
        except Exception:  # noqa: BLE001
            return str(exc.response.status_code)
    return type(exc).__name__


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", default=None)
    args = ap.parse_args()

    clave = _clave(args.env_file)
    if not clave:
        print("OPENAI_API_KEY no configurada. No se probó nada.")
        return 2

    cabeceras = {"Authorization": f"Bearer {clave}"}
    with httpx.Client(timeout=45.0, headers=cabeceras) as cli:
        # 1. Autenticación + catálogo visible para ESTE proyecto.
        try:
            r = cli.get(f"{BASE}/models")
            r.raise_for_status()
            catalogo = {m["id"] for m in r.json().get("data", [])}
            print(f"OpenAI authentication: OK  ({len(catalogo)} modelos visibles)")
        except Exception as exc:  # noqa: BLE001
            print(f"OpenAI authentication: FALLA ({_sanitizar(exc)})")
            return 1

        # 2. Los de chat, con una llamada real mínima: figurar en el catálogo
        #    no garantiza que el proyecto pueda invocarlo.
        for var, modelo in CHAT:
            en_catalogo = modelo in catalogo
            t0 = time.time()
            try:
                r = cli.post(
                    f"{BASE}/responses",
                    json={"model": modelo, "input": SONDA, "max_output_tokens": 16,
                          "store": False},
                )
                r.raise_for_status()
                ms = int((time.time() - t0) * 1000)
                print(f"{modelo}: DISPONIBLE ({ms} ms, en catálogo: {en_catalogo})")
            except Exception as exc:  # noqa: BLE001
                print(f"{modelo}: NO DISPONIBLE ({_sanitizar(exc)}, "
                      f"en catálogo: {en_catalogo})")

        # 3. Transcripción y TTS: solo presencia en el catálogo. Invocarlos
        #    exige subir audio o generar audio, y no hace falta gastar eso
        #    para saber si el proyecto los tiene habilitados.
        for var, modelo in OTROS:
            print(f"{modelo}: {'en catálogo' if modelo in catalogo else 'NO figura en el catálogo'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
