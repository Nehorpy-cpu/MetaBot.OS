"""El motor determinístico: acá se calculan los números, y solo acá.

La IA interpreta la pregunta, elige una herramienta permitida y explica un
resultado YA calculado. No suma, no consulta libre, no define. Esa frontera
es lo único que hace que el número que sale por WhatsApp se pueda defender
frente a un contador.

Tres reglas:

1. **Guaraníes enteros.** Nunca float. `Decimal` para ratios y porcentajes.
2. **El resultado dice de dónde salió.** Fuentes, corte de actualización,
   completitud y advertencias viajan con el número, no aparte.
3. **Si falta una fuente, se dice.** Un cero por dato faltante es peor que
   una negativa: alguien decide con él.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from . import cfo_metricas
from .cfo_metricas import CATALOGO, Fuente
from .models import Appointment, Company, FinanceMetricState, Service

# Lo que el sistema tiene HOY sin conectar nada de afuera.
#
# Es poco a propósito de decirlo: MetaBot.OS no tiene tabla de facturas, de
# cobranzas, de gastos ni de metas. Lo único con forma de ingreso son las
# atenciones con su servicio y su precio. Fingir que hay más es lo que hace
# que un CFO conteste con seguridad un número que nadie puede sostener.
FUENTES_DISPONIBLES = frozenset({Fuente.INTERNA, Fuente.VENTAS})

# El estado de una atención que ya ocurrió. Igual que en las planillas de
# honorarios: un turno confirmado al que el paciente no vino no es plata.
ATENDIDA = "attended"


@dataclass(frozen=True)
class Resultado:
    """Un número con su procedencia. Nunca viaja solo."""

    clave: str
    nombre: str
    version: int
    desde: date
    hasta: date
    # None = no se pudo calcular. Es distinto de 0, y la diferencia importa:
    # cero es un dato, None es una fuente que falta.
    valor: int | None
    unidad: str
    # Cuándo se miró la base. El dueño necesita saber si el número es de
    # ahora o de anoche.
    corte: datetime
    fuentes: tuple[str, ...] = ()
    # 0.0 a 1.0. Qué proporción de lo que se necesitaba estaba realmente.
    completitud: float = 1.0
    advertencias: tuple[str, ...] = ()
    detalle: dict = field(default_factory=dict)

    @property
    def calculable(self) -> bool:
        return self.valor is not None


def _corte() -> datetime:
    """Cuándo se miró la base. `utcnow()` está deprecado y además devuelve un
    naive que después nadie sabe en qué reloj está."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _rango(desde: date, hasta: date) -> tuple[datetime, datetime]:
    """El período completo, incluyendo todo el último día.

    Con `<= hasta` a secas se pierde la jornada del último día. Ya pasó en
    las planillas de honorarios.
    """
    return datetime.combine(desde, time.min), datetime.combine(hasta, time.max)


def metrica_activa(db: Session, company_id: int, clave: str) -> FinanceMetricState | None:
    """La versión aprobada y vigente de esa métrica para esta empresa."""
    return (
        db.query(FinanceMetricState)
        .filter(
            FinanceMetricState.company_id == company_id,
            FinanceMetricState.clave == clave,
            FinanceMetricState.estado == "activa",
        )
        .first()
    )


def _no_calculable(clave: str, desde: date, hasta: date, motivo: str) -> Resultado:
    m = CATALOGO.get(clave)
    return Resultado(
        clave=clave,
        nombre=m.nombre if m else clave,
        version=m.version if m else 0,
        desde=desde, hasta=hasta, valor=None,
        unidad=m.unidad if m else "PYG",
        corte=_corte(),
        fuentes=tuple(f.value for f in m.fuentes) if m else (),
        completitud=0.0,
        advertencias=(motivo,),
    )


def calcular(db: Session, company: Company, clave: str,
             desde: date, hasta: date) -> Resultado:
    """El único camino por el que sale un número financiero.

    Antes de calcular verifica tres cosas, en este orden:
    la métrica existe, la empresa la tiene aprobada y vigente, y sus fuentes
    están conectadas. Cualquiera que falte devuelve un resultado NO calculable
    con el motivo, no un cero.
    """
    m = CATALOGO.get(clave)
    if not m:
        return _no_calculable(clave, desde, hasta, "Esa métrica no existe en el catálogo.")

    estado = metrica_activa(db, company.id, clave)
    if estado is None:
        return _no_calculable(
            clave, desde, hasta,
            f"{m.nombre} todavía no está aprobada para esta empresa. "
            "Se aprueba desde el panel, revisando su definición.",
        )
    if estado.vigente_desde and hasta < estado.vigente_desde:
        return _no_calculable(
            clave, desde, hasta,
            f"La definición vigente de {m.nombre.lower()} rige desde el "
            f"{estado.vigente_desde.strftime('%d/%m/%Y')}. Para un período "
            "anterior habría que decir con qué criterio se calculó entonces.",
        )

    faltan = cfo_metricas.faltantes(clave, FUENTES_DISPONIBLES)
    if faltan:
        return _no_calculable(
            clave, desde, hasta,
            cfo_metricas.explicar_faltante(clave, FUENTES_DISPONIBLES),
        )

    calculador = _CALCULADORES.get(clave)
    if calculador is None:
        return _no_calculable(
            clave, desde, hasta,
            f"{m.nombre} está definida y aprobada, pero su cálculo todavía no "
            "está implementado.",
        )
    return calculador(db, company, m, estado, desde, hasta)


# ─── Los cálculos ────────────────────────────────────────────────────────


def _atenciones(db: Session, company_id: int, desde: date, hasta: date):
    """Atenciones ocurridas en el período, con su servicio si lo tienen."""
    inicio, fin = _rango(desde, hasta)
    return (
        db.query(Appointment)
        .filter(
            Appointment.company_id == company_id,
            Appointment.scheduled_at >= inicio,
            Appointment.scheduled_at <= fin,
            Appointment.status == ATENDIDA,
        )
        .all()
    )


def _ventas(db: Session, company: Company, m, estado, desde: date,
            hasta: date) -> Resultado:
    """Lo facturado por atenciones, en guaraníes enteros.

    Hoy la única fuente de ingreso del sistema son las atenciones con su
    servicio y su precio. No hay tabla de facturas: esto NO es facturación
    contable y el resultado lo dice, para que nadie lo presente como tal.

    `ventas_brutas` y `ventas_netas` dan el mismo número mientras no haya
    fuente de descuentos, devoluciones ni anulaciones. Se informa: un neto
    que en realidad es bruto, presentado como neto, es una mentira prolija.
    """
    citas = _atenciones(db, company.id, desde, hasta)
    precios = {
        s.id: s.price_gs
        for s in db.query(Service).filter(Service.company_id == company.id).all()
    }
    total = 0
    sin_precio = 0
    for c in citas:
        precio = precios.get(c.service_id) if c.service_id else None
        if not precio:
            sin_precio += 1
            continue
        total += int(precio)

    advertencias: list[str] = [
        "Sale de las atenciones marcadas como realizadas y del precio de "
        "lista de cada prestación. No es facturación contable: el sistema "
        "todavía no tiene conectada una fuente de facturas.",
    ]
    if m.clave == "ventas_netas":
        advertencias.append(
            "Sin fuente de descuentos, devoluciones ni anulaciones conectada, "
            "este neto coincide con el bruto. No lo presentes como neto "
            "definitivo."
        )
    if sin_precio:
        advertencias.append(
            f"{sin_precio} atención(es) sin prestación cargada quedaron en "
            "cero: no hay precio del que sacar el monto."
        )

    # Cero SIN registros y cero CON registros no son lo mismo, y el modelo
    # necesita poder decir cuál es. Visto en producción: con cero atenciones
    # el bot escribió "₲ [valor pendiente]" —un marcador con forma de monto—
    # en vez de decir que no había nada registrado. Prefirió disimular antes
    # que contestar cero.
    if not citas:
        advertencias.insert(
            0,
            "No hay ninguna atención registrada como realizada en ese "
            "período. El cero no es una caída de ventas: es que no se cargó "
            "nada.",
        )

    completitud = 1.0
    if citas:
        # Proporción de atenciones que sí aportaron un monto. Un 0,7 acá
        # significa que tres de cada diez atenciones no se pudieron valorizar.
        completitud = float(
            Decimal(len(citas) - sin_precio) / Decimal(len(citas))
        )

    return Resultado(
        clave=m.clave, nombre=m.nombre, version=estado.version,
        desde=desde, hasta=hasta, valor=total, unidad=m.unidad,
        corte=_corte(),
        fuentes=("atenciones y prestaciones del propio sistema",),
        completitud=round(completitud, 4),
        advertencias=tuple(advertencias),
        detalle={"atenciones": len(citas), "sin_prestacion": sin_precio},
    )


# Solo las métricas que HOY se pueden calcular con datos propios. Las demás
# quedan definidas y aprobables, y devuelven "falta conectar la fuente".
_CALCULADORES = {
    "ventas_brutas": _ventas,
    "ventas_netas": _ventas,
}


def catalogo_para(db: Session, company: Company) -> list[dict]:
    """Cada métrica con su estado en esta empresa y qué le falta.

    Es lo que ve la administración para decidir qué aprobar, y lo que hace
    honesto al producto: se ve de un vistazo qué puede contestar el CFO y qué
    no, en vez de descubrirlo cuando el dueño pregunta.
    """
    estados = {
        e.clave: e
        for e in db.query(FinanceMetricState)
        .filter(FinanceMetricState.company_id == company.id)
        .all()
    }
    salida = []
    for clave, m in CATALOGO.items():
        e = estados.get(clave)
        faltan = cfo_metricas.faltantes(clave, FUENTES_DISPONIBLES)
        salida.append({
            "clave": clave,
            "nombre": m.nombre,
            "formula": m.formula,
            "version_catalogo": m.version,
            "version_aprobada": e.version if e else None,
            "estado": e.estado if e else "sin_definir",
            "vigente_desde": e.vigente_desde.isoformat() if e and e.vigente_desde else None,
            "unidad": m.unidad,
            "fuentes": [f.value for f in m.fuentes],
            "fuentes_faltantes": faltan,
            "dimensiones": list(m.dimensiones),
            "excluye": m.excluye,
            "notas_contables": m.notas_contables,
            "se_puede_calcular": bool(_CALCULADORES.get(clave)) and not faltan,
            # Aprobar una métrica cuya fuente no está conectada es prometer un
            # número que no va a llegar.
            "se_puede_aprobar": not faltan,
        })
    return sorted(salida, key=lambda x: x["nombre"])
