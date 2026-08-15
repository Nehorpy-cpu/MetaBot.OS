"""De dónde salen los datos de cada empresa, y de cuándo son.

Este módulo contesta dos preguntas, y ninguna es "cuánto da":

1. **¿Qué fuentes tiene ESTA empresa?** Antes era una constante del motor que
   decía `{INTERNA, VENTAS}` para todo el mundo. Era mentira: no hay ninguna
   tabla de ventas conectada. Una constante global no puede describir a
   empresas distintas, y cuando miente, miente a favor del sistema — dice que
   puede calcular algo que no puede.

2. **¿De cuándo son?** Un número financiero sin la fecha de sus datos no
   sirve para decidir. "Vendiste ₲ 12.400.000" con datos de hace nueve días,
   sin avisar, es peor que no contestar: el dueño toma la decisión igual.

La regla que ordena todo lo demás: **conectado no es disponible**. Una fuente
cuenta cuando trajo filas al menos una vez. Un conector recién creado y
todavía vacío haría que el motor calcule sobre cero registros y conteste ₲ 0,
que es exactamente el cero mentiroso que este módulo existe para evitar.
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from .cfo_metricas import Fuente
from .models import FinanceConnector, FinanceRecord

# Los tres que se van a construir. El orden no es casual: CSV primero porque
# es el que un comercio paraguayo puede usar hoy —exporta de su sistema de
# facturación y sube el archivo— sin pedirle a nadie una API que no tiene.
TIPOS = ("csv", "rest", "postgres")

# A partir de acá los datos empiezan a envejecer lo suficiente como para que
# valga la pena decirlo junto al número.
HORAS_PARA_AVISAR = 48


def _ahora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def conectores(db: Session, company_id: int, solo_activos=True) -> list[FinanceConnector]:
    q = db.query(FinanceConnector).filter(FinanceConnector.company_id == company_id)
    if solo_activos:
        q = q.filter(FinanceConnector.activo.is_(True))
    return q.order_by(FinanceConnector.fuente, FinanceConnector.nombre).all()


def fuentes_disponibles(db: Session, company_id: int) -> frozenset[Fuente]:
    """Las fuentes sobre las que esta empresa REALMENTE puede calcular.

    `INTERNA` siempre está: son los turnos, los servicios con precio y los
    convenios que el propio MetaBot.OS ya tiene. Las demás entran solo si hay
    un conector activo que además trajo filas.
    """
    disponibles = {Fuente.INTERNA}
    for c in conectores(db, company_id):
        if c.filas_totales <= 0:
            continue
        try:
            disponibles.add(Fuente(c.fuente))
        except ValueError:
            # Una fuente que el catálogo ya no reconoce no habilita nada. Es
            # preferible no calcular a calcular con un significado perdido.
            continue
    return frozenset(disponibles)


def corte_de(db: Session, company_id: int, fuente: Fuente) -> datetime | None:
    """Hasta cuándo llegaron los datos de esa fuente. None si nunca llegaron.

    Es la sincronización MÁS VIEJA entre los conectores de esa fuente, no la
    más nueva: si son tres y uno quedó atrasado, los datos completos son los
    de ese. Quedarse con el más reciente sería contar la mejor mitad.
    """
    filas = [
        c.ultima_sync_at
        for c in conectores(db, company_id)
        if c.fuente == fuente.value and c.filas_totales > 0
    ]
    if not filas or any(f is None for f in filas):
        return None
    return min(filas)


def frescura(db: Session, company_id: int, fuentes) -> dict:
    """Qué tan viejos son los datos que sostienen un número.

    Devuelve el corte (el más viejo de las fuentes que se usaron) y, si hace
    falta, la advertencia ya redactada. La advertencia viaja PEGADA al número,
    no al pie del informe: una advertencia que llega después del número llega
    tarde.
    """
    cortes = {}
    for f in fuentes:
        if f == Fuente.INTERNA:
            # Lo interno no se sincroniza: se escribe en el momento.
            continue
        cortes[f] = corte_de(db, company_id, f)

    if not cortes:
        return {"corte": None, "advertencias": []}

    if any(c is None for c in cortes.values()):
        sin_datos = [f.value for f, c in cortes.items() if c is None]
        return {
            "corte": None,
            "advertencias": [
                "No hay datos cargados de: " + ", ".join(sorted(sin_datos)) + "."
            ],
        }

    corte = min(cortes.values())
    avisos = []
    atraso = _ahora() - corte
    if atraso > timedelta(hours=HORAS_PARA_AVISAR):
        dias = atraso.days
        cuanto = f"{dias} días" if dias >= 1 else f"{int(atraso.total_seconds() // 3600)} horas"
        avisos.append(
            f"Los datos más nuevos son de hace {cuanto} "
            f"({corte.strftime('%d/%m/%Y %H:%M')} UTC). "
            "Lo que pasó después todavía no está."
        )
    return {"corte": corte, "advertencias": avisos}


def sumar(db: Session, company_id: int, fuente: Fuente, desde: date, hasta: date,
          categorias: list[str] | None = None) -> tuple[int, int]:
    """Suma los montos de una fuente en el período. Devuelve (total, filas).

    Las filas se devuelven aparte a propósito: un total de 0 con 0 filas
    significa "no hay datos" y uno con 40 filas significa "vendiste y
    gastaste lo mismo". El motor necesita distinguirlos para no contestar un
    cero que no es cero.
    """
    q = db.query(
        func.coalesce(func.sum(FinanceRecord.monto_gs), 0), func.count()
    ).filter(
        FinanceRecord.company_id == company_id,
        FinanceRecord.fuente == fuente.value,
        FinanceRecord.fecha >= desde,
        FinanceRecord.fecha <= hasta,
    )
    if categorias:
        q = q.filter(FinanceRecord.categoria.in_(categorias))
    total, filas = q.one()
    return int(total or 0), int(filas or 0)


def anotar_sync(db: Session, conector: FinanceConnector, filas_nuevas: int,
                error: str = "") -> None:
    """Deja escrito cómo salió la última sincronización.

    Un error se guarda en castellano y SIN credenciales adentro: este texto se
    muestra en el panel, y un mensaje de conexión de PostgreSQL trae el
    usuario y a veces la contraseña.
    """
    conector.ultima_sync_at = _ahora()
    conector.ultima_sync_ok = not error
    conector.ultimo_error = error[:500]
    conector.filas_ultima_sync = filas_nuevas
    if not error:
        conector.filas_totales = (
            db.query(func.count())
            .select_from(FinanceRecord)
            .filter(
                FinanceRecord.company_id == conector.company_id,
                FinanceRecord.connector_id == conector.id,
            )
            .scalar()
        ) or 0
    db.commit()


def estado(db: Session, conector: FinanceConnector) -> dict:
    """Lo que ve quien administra. Nunca incluye configuración con secretos."""
    return {
        "id": conector.id,
        "fuente": conector.fuente,
        "tipo": conector.tipo,
        "nombre": conector.nombre,
        "activo": conector.activo,
        "ultima_sync": (
            conector.ultima_sync_at.isoformat() if conector.ultima_sync_at else None
        ),
        "ultima_sync_ok": conector.ultima_sync_ok,
        "ultimo_error": conector.ultimo_error,
        "filas_ultima_sync": conector.filas_ultima_sync,
        "filas_totales": conector.filas_totales,
        # La distinción que importa: conectado no es disponible.
        "habilita_la_fuente": conector.activo and conector.filas_totales > 0,
    }
