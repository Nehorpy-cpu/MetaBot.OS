"""Los dos conectores que salen a buscar datos afuera: REST y PostgreSQL.

Es la superficie de más riesgo del módulo, y no por el código que trae filas
sino por dos cosas:

**Una.** El cliente elige a dónde nos conectamos. Sin freno, alguien carga un
DSN apuntando a `db:5432` —o sea, a NUESTRA base— y el sistema se conecta
desde adentro de la red y le devuelve los datos de todos los demás clientes.
Por eso todo host pasa por `netguard`: tiene que resolver a una IP pública.
Un conector legítimo apunta al ERP del cliente, que está en internet.

**Dos.** Guardamos su contraseña. Va cifrada con Fernet y descifrada solo en
el momento de conectarse; no sale nunca por la API.

Sobre PostgreSQL: la consulta la escribe el cliente porque su esquema lo
conoce él, no nosotros. Pero se ejecuta con todo cerrado — una sola sentencia,
que empiece con SELECT, en una transacción de SOLO LECTURA, con timeout y con
un tope de filas puesto por nosotros. Nada de eso protege al cliente de sí
mismo; protege de que un `UPDATE` escrito por error o por maldad le toque su
propio sistema desde acá.
"""
import json
import logging
import re
from datetime import date

import httpx
from sqlalchemy.orm import Session

from . import cfo_secretos
from .cfo_csv import leer_fecha, leer_monto
from .models import FinanceConnector, FinanceRecord
from .netguard import BlockedURLError, assert_public_host, assert_public_url

logger = logging.getLogger("metabot.cfo.fuentes")

# Tope de filas por sincronización. Un ERP con diez años de historia no se
# trae de un saque: se trae por período.
MAXIMO_FILAS = 20_000
# Un JSON de más de esto no es una lista de ventas, es un error.
MAXIMO_BYTES_REST = 12 * 1024 * 1024
SEGUNDOS_DE_TIMEOUT = 30

# La consulta tiene que empezar con SELECT o WITH, y ser UNA sola. El `;`
# está prohibido entero: separar sentencias es exactamente el mecanismo.
_EMPIEZA_BIEN_RE = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
_COMENTARIO_RE = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)


class FuenteInvalida(Exception):
    """Configuración que no se acepta. El motivo se le muestra a quien la cargó."""


class FalloDeSincronizacion(Exception):
    """No se pudo traer. El motivo ya viene limpio de credenciales."""


def _limpiar(texto: str) -> str:
    """Saca contraseñas de un mensaje de error antes de que se guarde.

    Un error de conexión de PostgreSQL trae el usuario y a veces el DSN
    entero, y ese texto se muestra en el panel.
    """
    sin_dsn = re.sub(r"://[^@\s]+@", "://<credencial>@", texto or "")
    return re.sub(r"(?i)(password|token|authorization)[=:]\s*\S+",
                  r"\1=<oculto>", sin_dsn)[:400]


# ─── Validación de la configuración ──────────────────────────────────────


def validar_rest(config: dict) -> dict:
    url = str(config.get("url", "")).strip()
    if not url:
        raise FuenteInvalida("Falta la URL.")
    if not url.lower().startswith("https://"):
        # El token viaja en el encabezado. Sobre http lo lee cualquiera en el
        # camino.
        raise FuenteInvalida("La URL tiene que ser https: el token viaja ahí.")

    campos = config.get("campos") or {}
    for obligatorio in ("fecha", "monto"):
        if not campos.get(obligatorio):
            raise FuenteInvalida(
                f"Falta decir qué campo del JSON es '{obligatorio}'."
            )

    # La red, al final. Igual que en postgres.
    try:
        assert_public_url(url)
    except BlockedURLError as exc:
        raise FuenteInvalida(str(exc))

    return {
        "url": url,
        "campos": {
            "fecha": str(campos["fecha"]),
            "monto": str(campos["monto"]),
            "categoria": str(campos.get("categoria", "")),
            "referencia": str(campos.get("referencia", "")),
        },
        # Dónde está la lista dentro del JSON: "" = la raíz es la lista.
        "raiz": str(config.get("raiz", "")),
        "encabezado": str(config.get("encabezado", "Authorization")),
    }


def validar_postgres(config: dict) -> dict:
    # Todo lo que se puede rechazar SIN red se rechaza primero. Resolver un
    # DNS para después descubrir que la consulta era un DELETE es trabajo de
    # red al pedo, y además hace que el motivo del rechazo dependa de si el
    # servidor tiene internet en ese momento.
    host = str(config.get("host", "")).strip()
    puerto = int(config.get("puerto") or 5432)
    if not host:
        raise FuenteInvalida("Falta el host.")

    consulta = str(config.get("consulta", "")).strip()
    if not consulta:
        raise FuenteInvalida("Falta la consulta SQL.")
    sin_comentarios = _COMENTARIO_RE.sub(" ", consulta)
    if not _EMPIEZA_BIEN_RE.match(sin_comentarios):
        raise FuenteInvalida("La consulta tiene que empezar con SELECT o WITH.")
    if ";" in sin_comentarios:
        raise FuenteInvalida(
            "La consulta no puede llevar punto y coma: tiene que ser una sola "
            "sentencia."
        )
    if not config.get("base") or not config.get("usuario"):
        raise FuenteInvalida("Faltan la base y el usuario.")

    columnas = config.get("columnas") or {}
    for obligatorio in ("fecha", "monto"):
        if not columnas.get(obligatorio):
            raise FuenteInvalida(
                f"Falta decir qué columna del resultado es '{obligatorio}'."
            )

    # Recién ahora la red: el host tiene que resolver a una IP pública.
    try:
        assert_public_host(host, puerto)
    except BlockedURLError as exc:
        raise FuenteInvalida(str(exc))

    return {
        "host": host,
        "puerto": puerto,
        "base": str(config["base"]),
        "usuario": str(config["usuario"]),
        "consulta": consulta,
        "columnas": {
            "fecha": str(columnas["fecha"]),
            "monto": str(columnas["monto"]),
            "categoria": str(columnas.get("categoria", "")),
            "referencia": str(columnas.get("referencia", "")),
        },
    }


VALIDADORES = {"rest": validar_rest, "postgres": validar_postgres}


# ─── Traer los datos ─────────────────────────────────────────────────────


def _por_camino(datos, raiz: str):
    """Busca la lista dentro del JSON. `raiz` puede ser "data.items"."""
    actual = datos
    for parte in [p for p in raiz.split(".") if p]:
        if not isinstance(actual, dict) or parte not in actual:
            raise FalloDeSincronizacion(
                f"La respuesta no tiene '{raiz}'. Revisá dónde está la lista."
            )
        actual = actual[parte]
    if not isinstance(actual, list):
        raise FalloDeSincronizacion(
            "Lo que llegó no es una lista de registros."
        )
    return actual


def _normalizar(crudas: list, campos: dict, etiqueta: str) -> list[dict]:
    """De filas ajenas a filas nuestras. Explota con el renglón que falla.

    Misma regla que la planilla: si una fila no se entiende no se carga
    NINGUNA. Un total armado con el 98% de los datos se ve bien y cierra mal.
    """
    filas, problemas = [], []
    for numero, cruda in enumerate(crudas[:MAXIMO_FILAS], start=1):
        if not isinstance(cruda, dict):
            problemas.append(f"Registro {numero}: no es un objeto.")
            continue
        try:
            filas.append({
                "fecha": leer_fecha(str(cruda.get(campos["fecha"], ""))),
                "monto_gs": leer_monto(str(cruda.get(campos["monto"], ""))),
                "categoria": str(cruda.get(campos["categoria"], ""))[:120]
                if campos["categoria"] else "",
                "referencia": str(cruda.get(campos["referencia"], ""))[:120]
                if campos["referencia"] else "",
            })
        except ValueError as exc:
            problemas.append(f"{etiqueta} {numero}: {exc}")
            if len(problemas) >= 20:
                problemas.append("… y puede haber más.")
                break
    if problemas:
        raise FalloDeSincronizacion(
            "Hay registros que no se entienden, así que no se cargó ninguno: "
            + " | ".join(problemas[:5])
        )
    if not filas:
        raise FalloDeSincronizacion("No llegó ningún registro.")
    return filas


async def traer_rest(config: dict, secreto: str) -> list[dict]:
    cfg = validar_rest(config)
    encabezados = {"Accept": "application/json"}
    if secreto:
        encabezados[cfg["encabezado"]] = secreto
    try:
        # `safe_client` no sirve acá porque necesitamos el cuerpo; se vuelve a
        # validar la URL igual, y el guardia corre también en los redirects.
        async with httpx.AsyncClient(timeout=SEGUNDOS_DE_TIMEOUT,
                                     follow_redirects=True) as client:
            r = await client.get(cfg["url"], headers=encabezados)
            r.raise_for_status()
            if len(r.content) > MAXIMO_BYTES_REST:
                raise FalloDeSincronizacion("La respuesta es demasiado grande.")
            datos = r.json()
    except httpx.HTTPStatusError as exc:
        raise FalloDeSincronizacion(
            f"El servidor contestó {exc.response.status_code}."
        )
    except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
        raise FalloDeSincronizacion(_limpiar(f"No se pudo leer: {exc}"))

    return _normalizar(_por_camino(datos, cfg["raiz"]), cfg["campos"], "Registro")


def traer_postgres(config: dict, secreto: str) -> list[dict]:
    cfg = validar_postgres(config)
    import psycopg

    # El tope de filas lo ponemos NOSOTROS, envolviendo la consulta del
    # cliente. Pedírselo en su SQL sería confiar en que se acuerde.
    envuelta = f"SELECT * FROM ({cfg['consulta']}) AS _cfo LIMIT {MAXIMO_FILAS}"
    try:
        with psycopg.connect(
            host=cfg["host"], port=cfg["puerto"], dbname=cfg["base"],
            user=cfg["usuario"], password=secreto,
            connect_timeout=10,
            # Solo lectura y con timeout, del lado del servidor del cliente.
            # Si su usuario tiene permisos de escritura, esto impide igual que
            # un UPDATE escrito por error salga desde acá.
            options=f"-c default_transaction_read_only=on "
                    f"-c statement_timeout={SEGUNDOS_DE_TIMEOUT * 1000}",
        ) as conn:
            conn.read_only = True
            with conn.cursor() as cur:
                cur.execute(envuelta)
                columnas = [d.name for d in cur.description or []]
                crudas = [dict(zip(columnas, fila)) for fila in cur.fetchall()]
    except Exception as exc:  # psycopg tiene su propia jerarquía
        raise FalloDeSincronizacion(_limpiar(f"No se pudo consultar: {exc}"))

    return _normalizar(crudas, cfg["columnas"], "Fila")


async def sincronizar(db: Session, conector: FinanceConnector) -> dict:
    """Trae y guarda. Idempotente por referencia, igual que la planilla."""
    config = json.loads(conector.config or "{}")
    secreto = cfo_secretos.descifrar(conector.secreto_cifrado or "")

    if conector.tipo == "rest":
        filas = await traer_rest(config, secreto)
    elif conector.tipo == "postgres":
        filas = traer_postgres(config, secreto)
    else:
        raise FalloDeSincronizacion(f"Tipo de conector desconocido: {conector.tipo}")

    nuevas = actualizadas = 0
    for fila in filas:
        referencia = fila["referencia"] or (
            f"{fila['fecha'].isoformat()}|{fila['monto_gs']}|{fila['categoria']}"
        )
        existente = (
            db.query(FinanceRecord)
            .filter(
                FinanceRecord.company_id == conector.company_id,
                FinanceRecord.connector_id == conector.id,
                FinanceRecord.referencia == referencia,
            )
            .first()
        )
        if existente:
            existente.fecha = fila["fecha"]
            existente.monto_gs = fila["monto_gs"]
            existente.categoria = fila["categoria"]
            actualizadas += 1
            continue
        db.add(FinanceRecord(
            company_id=conector.company_id,
            connector_id=conector.id,
            fuente=conector.fuente,
            fecha=fila["fecha"],
            monto_gs=fila["monto_gs"],
            categoria=fila["categoria"],
            referencia=referencia,
            detalle=json.dumps({"origen": conector.tipo}),
        ))
        nuevas += 1
    db.commit()
    return {"nuevas": nuevas, "actualizadas": actualizadas, "leidas": len(filas)}


def resumen_config(conector: FinanceConnector) -> dict:
    """Lo que se le muestra a quien administra. Sin la credencial, nunca.

    Se informa si TIENE credencial, no cuál es. Igual que el PIN.
    """
    config = json.loads(conector.config or "{}")
    if conector.tipo == "rest":
        publico = {"url": config.get("url", ""), "raiz": config.get("raiz", "")}
    elif conector.tipo == "postgres":
        publico = {
            "host": config.get("host", ""), "puerto": config.get("puerto", 5432),
            "base": config.get("base", ""), "usuario": config.get("usuario", ""),
            "consulta": config.get("consulta", ""),
        }
    else:
        publico = {}
    publico["tiene_credencial"] = bool(conector.secreto_cifrado)
    return publico


__all__ = [
    "FalloDeSincronizacion", "FuenteInvalida", "MAXIMO_FILAS", "VALIDADORES",
    "date", "resumen_config", "sincronizar", "traer_postgres", "traer_rest",
    "validar_postgres", "validar_rest",
]
