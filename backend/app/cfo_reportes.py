"""El informe privado: snapshot, llave opaca y HTML que no filtra nada.

El dueño recibe el resumen por WhatsApp y un enlace. Ese enlace es lo único
que hay entre un tercero y los números de una empresa, así que:

- la llave es opaca —no lleva adentro la empresa, ni el teléfono, ni la
  fecha—, porque un enlace interceptado no tiene por qué contar de quién es;
- de la llave se guarda el HASH, nunca el valor: con acceso de lectura a un
  respaldo, alguien podría abrir los informes de todos los clientes;
- vence, se puede revocar, y para lo sensible sirve una sola vez;
- el HTML se arma en el servidor con todo escapado, sin JavaScript y sin una
  sola petición a otro dominio.

Y el informe es un SNAPSHOT. El dueño reenvía el enlace a su contador tres
días después y los dos tienen que ver el mismo número.
"""
import hashlib
import html
import json
import secrets
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from . import cfo_motor
from .models import Company, FinanceReport, FinanceReportToken
from .textos import formato_gs

# Un enlace que dura para siempre es una filtración esperando su momento.
HORAS_DE_VIGENCIA = 24
LARGO_DEL_TOKEN = 32  # bytes de entropía real


def _ahora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def armar(db: Session, company: Company, metricas: list[str], desde: date,
          hasta: date, pedido_por: str = "", titulo: str = "") -> FinanceReport:
    """Calcula todo AHORA y lo congela. El informe no vuelve a mirar la base."""
    resultados = []
    for clave in metricas:
        r = cfo_motor.calcular(db, company, clave, desde, hasta)
        resultados.append({
            "clave": r.clave,
            "nombre": r.nombre,
            "version": r.version,
            "valor": r.valor,
            "unidad": r.unidad,
            "calculable": r.calculable,
            "fuentes": list(r.fuentes),
            "completitud": r.completitud,
            "advertencias": list(r.advertencias),
            "detalle": r.detalle,
        })

    informe = FinanceReport(
        company_id=company.id,
        titulo=titulo or f"Informe {desde.strftime('%d/%m/%Y')} – {hasta.strftime('%d/%m/%Y')}",
        pedido_por=pedido_por,
        desde=desde,
        hasta=hasta,
        snapshot=json.dumps(
            {
                "empresa": company.name,
                "corte": _ahora().isoformat(),
                "metricas": resultados,
            },
            ensure_ascii=False,
        ),
    )
    db.add(informe)
    db.flush()
    return informe


def emitir_token(db: Session, informe: FinanceReport, horas=HORAS_DE_VIGENCIA,
                 un_solo_uso=False) -> str:
    """Devuelve el token EN CLARO una sola vez. Después solo queda su hash."""
    token = secrets.token_urlsafe(LARGO_DEL_TOKEN)
    db.add(FinanceReportToken(
        company_id=informe.company_id,
        report_id=informe.id,
        token_hash=_hash(token),
        expira_at=_ahora() + timedelta(hours=horas),
        un_solo_uso=un_solo_uso,
    ))
    db.commit()
    return token


def validar(db: Session, token: str) -> tuple[FinanceReport | None, str]:
    """¿Esta llave sirve? Sin gastarla ni contar la apertura.

    Todos los rechazos son indistinguibles desde afuera a propósito: una
    llave inventada, una vencida y una revocada devuelven lo mismo. Decir
    "este enlace venció" le confirma a quien lo está probando que acertó un
    token, que es exactamente lo que no hay que contarle.
    """
    if not token or len(token) < 20:
        return None, "invalido"
    fila = (
        db.query(FinanceReportToken)
        .filter(FinanceReportToken.token_hash == _hash(token))
        .first()
    )
    if fila is None:
        return None, "invalido"
    if fila.revocado_at is not None:
        return None, "invalido"
    if fila.expira_at < _ahora():
        return None, "invalido"
    if fila.un_solo_uso and fila.aperturas >= 1:
        return None, "invalido"

    informe = db.get(FinanceReport, fila.report_id)
    # La FK es compuesta, pero se vuelve a verificar: si esto alguna vez
    # dejara de coincidir sería un informe de otra empresa abriéndose con
    # esta llave, y prefiero que no cargue a que cargue de más.
    if informe is None or informe.company_id != fila.company_id:
        return None, "invalido"
    return informe, ""


def abrir(db: Session, token: str) -> tuple[FinanceReport | None, str]:
    """Valida la llave, la marca como usada y devuelve el informe.

    Esto es lo que gasta un enlace de un solo uso, así que lo llama
    únicamente la confirmación explícita de una persona — nunca un GET. Un
    robot de vista previa (WhatsApp busca todo enlace que se envía para armar
    la miniatura) haría un GET, y el dueño encontraría muerto su enlace antes
    de abrirlo.
    """
    informe, motivo = validar(db, token)
    if informe is None:
        return None, motivo

    fila = (
        db.query(FinanceReportToken)
        .filter(FinanceReportToken.token_hash == _hash(token))
        .first()
    )
    fila.aperturas += 1
    fila.ultima_apertura_at = _ahora()
    if fila.primera_apertura_at is None:
        fila.primera_apertura_at = _ahora()
    db.commit()
    return informe, ""


def revocar(db: Session, company_id: int, report_id: int) -> int:
    """Mata todos los enlaces de un informe. Devuelve cuántos."""
    filas = (
        db.query(FinanceReportToken)
        .filter(
            FinanceReportToken.company_id == company_id,
            FinanceReportToken.report_id == report_id,
            FinanceReportToken.revocado_at.is_(None),
        )
        .all()
    )
    for f in filas:
        f.revocado_at = _ahora()
    db.commit()
    return len(filas)


# ─── El HTML ─────────────────────────────────────────────────────────────
#
# Se arma acá, en el servidor, escapando todo. Sin JavaScript, sin fuentes
# externas, sin imágenes remotas: un informe financiero no tiene por qué
# hacerle una petición a otro dominio, y cada una de esas peticiones le
# cuenta a un tercero que alguien abrió un reporte.

_ESTILO = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin:0; padding:1rem; font:16px/1.5 system-ui,-apple-system,sans-serif;
       background:#0b0d12; color:#e7e9ee; }
.hoja { max-width:46rem; margin:0 auto; }
h1 { font-size:1.35rem; margin:0 0 .25rem; }
.sub { color:#98a1b3; font-size:.85rem; margin:0 0 1.5rem; }
.kpi { background:#141821; border:1px solid #232838; border-radius:.9rem;
       padding:1rem; margin-bottom:.75rem; }
.kpi h2 { font-size:.75rem; text-transform:uppercase; letter-spacing:.08em;
          color:#98a1b3; margin:0 0 .4rem; font-weight:700; }
.monto { font-size:1.75rem; font-weight:800; margin:0; letter-spacing:-.02em; }
.monto.sin { font-size:1rem; font-weight:600; color:#f0b429; }
.aviso { margin:.6rem 0 0; padding:.55rem .7rem; background:#2a2312;
         border-left:3px solid #f0b429; border-radius:.3rem;
         font-size:.8rem; color:#f5d78e; }
.meta { margin:.5rem 0 0; font-size:.72rem; color:#6d7688; }
.pie { margin-top:2rem; padding-top:1rem; border-top:1px solid #232838;
       font-size:.72rem; color:#6d7688; }
button { width:100%; padding:.9rem 1rem; font:inherit; font-weight:700;
         color:#0b0d12; background:#e7e9ee; border:0; border-radius:.9rem;
         cursor:pointer; }
@media (prefers-color-scheme: light) {
  body { background:#f6f7f9; color:#1a1d24; }
  .kpi { background:#fff; border-color:#e3e6ec; }
  .sub, .kpi h2, .meta, .pie { color:#5b6472; }
  .aviso { background:#fdf6e3; color:#7a5c00; }
  button { color:#f6f7f9; background:#1a1d24; }
}
"""


def _e(valor) -> str:
    """Todo lo que entra al HTML pasa por acá.

    El nombre de una empresa o de una métrica es texto que alguien cargó: si
    contiene `<script>`, tiene que verse como `<script>` y no ejecutarse.
    """
    return html.escape(str(valor), quote=True)


def renderizar(informe: FinanceReport) -> str:
    datos = json.loads(informe.snapshot or "{}")
    metricas = datos.get("metricas", [])

    tarjetas = []
    for m in metricas:
        if m.get("calculable"):
            monto = (
                formato_gs(m["valor"]) if m.get("unidad") == "PYG"
                else f"{m.get('valor')} {m.get('unidad', '')}"
            )
            cuerpo = f'<p class="monto">{_e(monto)}</p>'
        else:
            cuerpo = '<p class="monto sin">No se pudo calcular</p>'

        avisos = "".join(
            f'<p class="aviso">{_e(a)}</p>' for a in m.get("advertencias", [])
        )
        pie = []
        if m.get("fuentes"):
            pie.append("Fuente: " + ", ".join(_e(f) for f in m["fuentes"]))
        if m.get("completitud") is not None and m.get("calculable"):
            pie.append(f"Completitud: {int(float(m['completitud']) * 100)}%")
        if m.get("version"):
            pie.append(f"Definición v{_e(m['version'])}")
        meta = f'<p class="meta">{" · ".join(pie)}</p>' if pie else ""

        tarjetas.append(
            f'<section class="kpi"><h2>{_e(m.get("nombre", ""))}</h2>'
            f"{cuerpo}{avisos}{meta}</section>"
        )

    corte = datos.get("corte", "")
    return (
        "<!doctype html><html lang=\"es\"><head>"
        "<meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<meta name=\"robots\" content=\"noindex,nofollow,noarchive\">"
        f"<title>{_e(informe.titulo)}</title>"
        f"<style>{_ESTILO}</style></head><body><div class=\"hoja\">"
        f"<h1>{_e(datos.get('empresa', ''))}</h1>"
        f"<p class=\"sub\">{_e(informe.titulo)}</p>"
        + "".join(tarjetas)
        + '<div class="pie">'
        f"Datos al {_e(corte[:16].replace('T', ' '))} UTC. "
        "Este enlace es privado y vence. Si llegó a alguien que no debía, "
        "se puede revocar desde el panel."
        "</div></div></body></html>"
    )


def renderizar_portada(token: str) -> str:
    """La página que ve cualquiera que pida el enlace: no dice nada.

    Ni la empresa, ni el período, ni un solo número. Es lo único que recibe
    el robot que arma la vista previa cuando el enlace viaja por WhatsApp —
    y ese robot manda una copia de lo que descarga a los servidores de quien
    previsualiza. Un informe financiero privado no puede ser eso.

    Los números están del otro lado de un envío, que un robot no hace.
    """
    return (
        "<!doctype html><html lang=\"es\"><head>"
        "<meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<meta name=\"robots\" content=\"noindex,nofollow,noarchive\">"
        "<title>Informe privado</title>"
        f"<style>{_ESTILO}</style></head><body><div class=\"hoja\">"
        "<h1>Informe privado</h1>"
        "<p class=\"sub\">Este enlace es personal y vence. "
        "No lo reenvíes: quien lo tenga puede ver los datos.</p>"
        f"<form method=\"post\" action=\"/r/{_e(token)}\">"
        "<button type=\"submit\">Ver el informe</button></form>"
        "<div class=\"pie\">Algunos enlaces se pueden abrir una sola vez.</div>"
        "</div></body></html>"
    )


# Encabezados que van en TODA respuesta del informe. Un reporte financiero no
# se guarda en caché, no se indexa, no se embebe en un iframe ajeno y no le
# cuenta a otro sitio de dónde vino el visitante.
ENCABEZADOS = {
    "Cache-Control": "no-store, private, max-age=0",
    "Pragma": "no-cache",
    "X-Robots-Tag": "noindex, nofollow, noarchive",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    # Sin scripts, sin conexiones, sin nada de afuera. El estilo va en línea
    # y por eso 'unsafe-inline' en style-src; no hay `script-src` permitido.
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
        "form-action 'none'; frame-ancestors 'none'; base-uri 'none'"
    ),
}

# La portada es lo único que tiene un formulario, y solo puede enviarse a este
# mismo sitio. El informe ya no tiene ninguno: sigue con form-action 'none'.
ENCABEZADOS_PORTADA = {
    **ENCABEZADOS,
    "Content-Security-Policy": ENCABEZADOS["Content-Security-Policy"].replace(
        "form-action 'none'", "form-action 'self'"
    ),
}
