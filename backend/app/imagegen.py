"""Generación de imágenes con proveedores conmutables.

Orden: NVIDIA (Flux.1-schnell vía NVCF, requiere créditos de imagen en la
cuenta) → Pollinations (gratuito, sin API key). Si NVIDIA falla o no está
habilitado, el sistema sigue funcionando con el proveedor gratuito.
"""
import asyncio
import urllib.parse

import httpx

from .config import LLM_PROVIDERS

NVIDIA_FLUX_URL = "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-schnell"
NVCF_STATUS_URL = "https://api.nvcf.nvidia.com/v2/nvcf/pexec/status"


class ImageGenError(Exception):
    pass


async def _nvidia_generate(prompt: str, width: int, height: int) -> bytes:
    key = LLM_PROVIDERS[0]["api_key"]
    if not key:
        raise ImageGenError("NVIDIA_API_KEY no configurada")
    headers = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "NVCF-POLL-SECONDS": "20",
    }
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(
            NVIDIA_FLUX_URL,
            headers=headers,
            json={
                "prompt": prompt,
                "mode": "base",
                "cfg_scale": 0,
                "width": width,
                "height": height,
                "seed": 0,
                "steps": 4,
            },
        )
        data = None
        if resp.status_code == 200:
            data = resp.json()
        elif resp.status_code in (202, 504) and resp.headers.get("NVCF-REQID"):
            reqid = resp.headers["NVCF-REQID"]
            for _ in range(20):
                poll = await client.get(
                    f"{NVCF_STATUS_URL}/{reqid}",
                    headers={"Authorization": f"Bearer {key}", "NVCF-POLL-SECONDS": "10"},
                )
                if poll.status_code == 200:
                    data = poll.json()
                    break
                if poll.status_code not in (202, 302):
                    raise ImageGenError(f"NVCF status {poll.status_code}")
                await asyncio.sleep(3)
        if not data:
            raise ImageGenError(f"NVIDIA imagen: HTTP {resp.status_code}")
        artifacts = data.get("artifacts") or []
        b64 = artifacts[0].get("base64") if artifacts else data.get("image")
        if not b64:
            raise ImageGenError("NVIDIA imagen: respuesta sin artifacts")
        import base64 as b64mod

        return b64mod.b64decode(b64)


async def _pollinations_generate(prompt: str, width: int, height: int) -> bytes:
    url = (
        f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}"
        f"?width={width}&height={height}&model=flux&nologo=true&seed=7"
    )
    async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
        resp = await client.get(url)
        if resp.status_code != 200 or not resp.headers.get("content-type", "").startswith("image"):
            raise ImageGenError(f"Pollinations: HTTP {resp.status_code}")
        return resp.content


async def generate_image(prompt: str, width: int = 1024, height: int = 1024) -> tuple[bytes, str]:
    """Devuelve (bytes de imagen, proveedor usado)."""
    errors = []
    for name, fn in (("nvidia", _nvidia_generate), ("pollinations", _pollinations_generate)):
        try:
            return await fn(prompt, width, height), name
        except (ImageGenError, httpx.HTTPError) as exc:
            errors.append(f"{name}: {exc}")
    raise ImageGenError("Todos los proveedores de imagen fallaron: " + "; ".join(errors))
