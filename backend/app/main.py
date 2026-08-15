import hmac
import os
import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db as db_module
from . import evaluator
from . import medication  # noqa: F401  — registra el handler de tomas en la cola
from . import packs
from .auth import resolve_identity
from .config import ADMIN_TOKEN
from .llm import available_providers
from .models import Company, Membership
from .permissions import Role
from .routers import agents, auth, blocks, bridge, campaigns, catalog, cfo, chat, companies, creatives, clinical, dashboard, glossary, intelligence, medical, planes as planes_router, portal, reportes, services, whatsapp_webhook
from .scheduler import _start_job_worker, start_scheduler

# El esquema lo gestiona Alembic (entrypoint.sh corre `alembic upgrade head`).
# Una sola fuente de verdad para la estructura de la base.

app = FastAPI(title="MetaBot.OS", version="0.12.0")
for router in (auth.router, blocks.router, companies.router, agents.router, medical.router, glossary.router, dashboard.router, chat.router, whatsapp_webhook.router, bridge.router, intelligence.router, creatives.router, campaigns.router, services.router, catalog.router, clinical.router, portal.router, cfo.router, planes_router.router):
    app.include_router(router, prefix="/api")


# Rutas /api que NO requieren identidad: salud, login y webhooks entrantes
# (los webhooks validan su propia firma/secreto de Meta o del bridge).
_PUBLIC_API_PREFIXES = ("/api/health", "/api/webhooks/", "/api/auth/login")

# Toda ruta de datos de un tenant tiene esta forma. El aislamiento se aplica
# acá, en UN solo lugar: un endpoint nuevo queda protegido sin que nadie
# tenga que acordarse de nada.
# Captura el segmento CRUDO, no solo dígitos: FastAPI acepta como int cosas
# como "+7", " 7" o "007", y un regex de \d+ las dejaba pasar sin verificar
# la membresía. Acá se exige forma canónica y, si no lo es, se rechaza.
_TENANT_PATH = re.compile(r"^/api/companies/([^/]+)(?:/|$)")
# Rutas de /api/companies que NO son un id de empresa
_NON_TENANT_SEGMENTS = {"smart"}
# Lo único que un usuario con rol `professional` puede tocar de su empresa.
_PORTAL_PATH = re.compile(r"^/portal(/|$)")


def _acceso_y_modulos(
    user_id: int | None, company_id: int, es_plataforma: bool
) -> tuple[bool, set[str] | None, str]:
    """Membresía + módulos contratados + rol, en una sola sesión.

    Devuelve (puede_entrar, módulos, rol). `módulos` es None cuando la empresa
    no existe: ahí el gate de bloques se hace a un lado y deja que el endpoint
    conteste 404, que es lo que corresponde.
    """
    db = db_module.SessionLocal()
    rol = ""
    try:
        if not es_plataforma:
            miembro = (
                db.query(Membership)
                .filter(
                    Membership.user_id == user_id,
                    Membership.company_id == company_id,
                    Membership.status == "active",
                )
                .first()
            )
            if miembro is None:
                return False, None, ""
            rol = miembro.role
        company = db.get(Company, company_id)
        return True, (set(company.modules) if company else None), rol
    finally:
        db.close()


@app.middleware("http")
async def enforce_auth_and_tenant(request: Request, call_next):
    """Autenticación + aislamiento de tenant, transversal a toda la API.

    1. Todo /api exige identidad (sesión de usuario o token de plataforma),
       salvo salud, login y webhooks.
    2. Si la ruta apunta a una empresa concreta, se exige membresía activa.
       El tenant se valida contra la identidad, nunca se confía en el path.
    3. Se exige que la empresa tenga contratado el bloque de esa ruta. El
       panel esconde lo que no compraste; esto es lo que además lo impide.

    Fail-closed en los tres pasos: un segmento de empresa que no sea un
    entero canónico se rechaza en vez de saltear la verificación, y una
    ruta que nadie clasificó se rechaza en vez de regalarse.
    """
    path = request.url.path
    if not path.startswith("/api") or path.startswith(_PUBLIC_API_PREFIXES):
        return await call_next(request)

    if not ADMIN_TOKEN:
        return JSONResponse(
            {"detail": "Servidor sin ADMIN_TOKEN configurado: API cerrada."}, status_code=503
        )

    db = db_module.SessionLocal()
    try:
        identity = resolve_identity(request, db)
    finally:
        db.close()
    if not identity:
        return JSONResponse({"detail": "No autorizado"}, status_code=401)

    match = _TENANT_PATH.match(path)
    if not match:
        return await call_next(request)
    raw = match.group(1)
    if raw in _NON_TENANT_SEGMENTS:
        return await call_next(request)
    # Forma canónica obligatoria: "7" sí, "+7"/" 7"/"007" no.
    if not raw.isdigit() or str(int(raw)) != raw:
        return JSONResponse({"detail": "Empresa no encontrada"}, status_code=404)
    company_id = int(raw)

    entra, modulos, rol = _acceso_y_modulos(
        identity.user_id, company_id, identity.is_platform
    )
    if not entra:
        return JSONResponse({"detail": "Empresa no encontrada"}, status_code=404)

    sufijo = path[match.end(1):]

    # El profesional vive encerrado en su portal. La lista blanca va acá y no
    # endpoint por endpoint a propósito: así el que se agregue mañana nace
    # cerrado para él. Al revés —permitir todo salvo lo que uno se acuerde de
    # cerrar— el primer olvido le muestra a un médico los pacientes de sus
    # colegas, que es exactamente lo que este bloque vende que no pasa.
    if rol == Role.PROFESSIONAL.value and not _PORTAL_PATH.match(sufijo):
        return JSONResponse(
            {"detail": {
                "motivo": "Tu usuario es de profesional: solo accede a su portal.",
                "codigo": "solo_portal",
            }},
            status_code=403,
        )

    # 3. Bloques contratados. Acá también, en UN solo lugar y por PATH: el
    #    archivo `medical.py` mezcla agenda, padrón y pre-visita, así que
    #    gatear por router le regalaría bloques enteros a quien compró uno.
    modulo = packs.modulo_de_ruta(sufijo)
    if modulo is None:
        # Ruta que nadie clasificó. No se regala: se rechaza. El test
        # `test_bloques` recorre todas las rutas y falla si queda alguna
        # sin bloque, así que esto no debería verse nunca en producción.
        return JSONResponse(
            {"detail": {"motivo": "Ruta sin bloque asignado", "codigo": "ruta_sin_bloque"}},
            status_code=403,
        )
    if modulo and modulos is not None and modulo not in modulos:
        pack = packs.pack_del_modulo(modulo)
        return JSONResponse(
            {
                # Detalle ESTRUCTURADO, como el 409 de agenda: el panel
                # decide por `codigo` y nunca por el texto. Ya se desarmó
                # una guardia sola porque alguien mejoró una redacción.
                "detail": {
                    "motivo": (
                        "Esta empresa no tiene contratado el bloque "
                        f"«{pack.name if pack else modulo}»."
                    ),
                    "codigo": "modulo_no_contratado",
                    "modulo": modulo,
                    "bloque": pack.key if pack else "",
                    "bloque_nombre": pack.name if pack else "",
                }
            },
            status_code=402,  # Payment Required: el panel muestra la oferta
        )

    return await call_next(request)


@app.on_event("startup")
async def _startup():
    # El conjunto dorado se siembra al arrancar. Sin casos, `correr` aprueba
    # todo por vacuidad (0 de 0 fallaron) — el mismo modo de falla que el
    # auditor que aprobaba en silencio.
    _db = db_module.SessionLocal()
    try:
        nuevos = evaluator.sembrar_casos(_db)
        if nuevos:
            print(f"conjunto dorado: {nuevos} casos sembrados")
    except Exception:  # noqa: BLE001 — no impedir el arranque por esto
        pass
    finally:
        _db.close()
    start_scheduler()
    # Trabajos durables: al arrancar retoma lo que quedó pendiente (un
    # recordatorio no se pierde porque el servidor se haya reiniciado).
    await _start_job_worker()


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "llm_providers": [p["name"] for p in available_providers()],
    }


# El informe privado vive FUERA de /api: el dueño lo abre desde WhatsApp, en
# el navegador del teléfono, sin haber entrado nunca al panel. Su autorización
# es el token opaco, no una sesión. Va antes de los mounts estáticos porque en
# Starlette las rutas se evalúan en orden.
app.include_router(reportes.router)

# Los mounts van al FINAL: en Starlette las rutas se evalúan en orden y un
# mount en "/" taparía la API si se registrara antes.
_media_dir = Path(__file__).resolve().parents[1] / "media"
_media_dir.mkdir(exist_ok=True)
app.mount("/media", StaticFiles(directory=_media_dir), name="media")

# En producción el backend sirve también el panel compilado (SPA).
# En desarrollo el panel corre con vite en :5173 y este mount igual existe
# si hay un build local; la API no se ve afectada por el orden.
_panel_dist = Path(os.environ.get("PANEL_DIST", Path(__file__).resolve().parents[2] / "frontend" / "panel" / "dist"))
if (_panel_dist / "index.html").exists():
    app.mount("/", StaticFiles(directory=_panel_dist, html=True), name="panel")
