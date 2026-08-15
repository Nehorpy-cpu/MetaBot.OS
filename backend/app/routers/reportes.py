"""El enlace público del informe: `/r/{token}`.

Va FUERA de `/api` a propósito. El middleware de `main.py` exige identidad y
membresía para todo lo que empieza con `/api`, y acá no hay sesión: el dueño
abre el enlace desde WhatsApp, en el navegador del teléfono, sin haber
entrado nunca al panel. La autorización es el token, y la hace este router.

Que esté fuera del middleware obliga a ser explícito: acá NO se lee ningún
`company_id` del path ni del query. Sale del informe que la llave desbloqueó,
y de ningún otro lado.
"""
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from .. import cfo_reportes
from ..db import get_db

router = APIRouter(tags=["reportes"])


_NO_EXISTE = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Enlace no disponible</title>
<style>body{margin:0;padding:2rem;font:16px/1.6 system-ui,sans-serif;
background:#0b0d12;color:#e7e9ee}div{max-width:28rem;margin:15vh auto;text-align:center}
h1{font-size:1.2rem}p{color:#98a1b3;font-size:.9rem}
@media(prefers-color-scheme:light){body{background:#f6f7f9;color:#1a1d24}p{color:#5b6472}}
</style></head><body><div>
<h1>Este enlace no está disponible</h1>
<p>Puede haber vencido, haber sido revocado, o no ser correcto.
Pedí uno nuevo por WhatsApp.</p>
</div></body></html>"""


def _rechazo() -> HTMLResponse:
    """Todos los rechazos devuelven la MISMA página y el mismo 404: una llave
    inventada, una vencida y una revocada son indistinguibles desde afuera.
    Decir "este enlace venció" le confirma a quien está probando tokens que
    acertó uno, que es justo lo que no hay que contarle.
    """
    return HTMLResponse(
        _NO_EXISTE, status_code=404, headers=cfo_reportes.ENCABEZADOS
    )


@router.get("/r/{token}", response_class=HTMLResponse)
def portada(token: str, db: Session = Depends(get_db)):
    """La portada. No muestra ni un número, y no gasta la llave.

    Cuando el enlace viaja por WhatsApp, WhatsApp lo busca para armar la
    miniatura. Ese robot hace un GET, así que un GET no puede ser lo que
    entrega el informe: gastaría un enlace de un solo uso antes de que el
    dueño lo abra, contaría una apertura que no ocurrió, y —lo peor— le
    mandaría los números de la empresa a los servidores de quien
    previsualiza.

    La llave se valida igual, para no mostrar una portada de algo que no
    existe, pero no se marca como usada.
    """
    informe, _ = cfo_reportes.validar(db, token)
    if informe is None:
        return _rechazo()
    return HTMLResponse(
        cfo_reportes.renderizar_portada(token),
        headers=cfo_reportes.ENCABEZADOS_PORTADA,
    )


@router.post("/r/{token}", response_class=HTMLResponse)
def ver_informe(token: str, db: Session = Depends(get_db)):
    """Los números. Esto sí gasta la llave y cuenta la apertura.

    Detrás de un envío de formulario, que es una acción de una persona: los
    robots de vista previa no lo hacen.
    """
    informe, _ = cfo_reportes.abrir(db, token)
    if informe is None:
        return _rechazo()
    return HTMLResponse(
        cfo_reportes.renderizar(informe), headers=cfo_reportes.ENCABEZADOS
    )
