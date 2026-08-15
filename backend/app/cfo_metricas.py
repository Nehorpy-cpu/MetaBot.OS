"""Capa semántica financiera: qué significa cada número, y quién lo decidió.

El problema que resuelve es viejo y caro: "ventas" no quiere decir lo mismo
para el dueño, para el contador y para la aseguradora. Si el bot contesta
"vendimos 486 millones" y el contador dice 431, la discusión no es sobre el
software: es sobre qué se contó.

Por eso una métrica no es una función suelta. Es una DEFINICIÓN con:

- fórmula escrita en castellano, para que la lea quien firma;
- versión, porque las definiciones cambian y lo dicho ayer sigue valiendo;
- fuentes, para poder responder "¿de dónde salió?";
- vigencia, porque un cambio de criterio arranca una fecha, no retroactivo;
- aprobación de una persona.

Y una regla que sostiene todo lo demás: **el modelo no define métricas**. Las
lee. Cambiarlas es un acto administrativo con nombre y fecha, no una frase en
una conversación.

Los números los calcula `cfo_motor.py`. Acá solo vive el contrato.
"""
from dataclasses import dataclass, field
from enum import Enum


class EstadoMetrica(str, Enum):
    """El camino de una definición hasta que el CFO la puede usar.

    Solo `ACTIVA` sirve en producción, y solo puede haber UNA activa por
    clave: dos versiones activas de "ventas netas" es exactamente el problema
    que esto viene a resolver.
    """

    BORRADOR = "borrador"
    EN_PRUEBA = "en_prueba"
    VALIDADA = "validada"
    APROBADA = "aprobada"
    ACTIVA = "activa"
    DEPRECADA = "deprecada"
    RECHAZADA = "rechazada"


# De dónde puede salir un dato. Mientras una fuente no esté conectada y
# aprobada, las métricas que la necesitan NO se habilitan.
class Fuente(str, Enum):
    VENTAS = "ventas"                  # facturación / pedidos
    COBRANZAS = "cobranzas"            # pagos recibidos y conciliados
    COMPRAS = "compras"                # costo de mercadería
    GASTOS = "gastos"                  # gastos operativos
    INVENTARIO = "inventario"
    CAJA_Y_BANCOS = "caja_y_bancos"
    IMPUESTOS = "impuestos"
    METAS = "metas"
    NOMINA = "nomina"
    # Lo que el propio MetaBot.OS ya tiene: turnos, servicios con precio,
    # convenios, planillas de honorarios. Es la única fuente que hoy está
    # conectada de verdad, y con eso alcanza para las primeras métricas.
    INTERNA = "interna"


@dataclass(frozen=True)
class Metrica:
    """Una definición versionada. Inmutable: cambiarla crea otra versión."""

    clave: str
    nombre: str
    # En castellano y sin jerga: esto es lo que lee quien aprueba, y quien
    # después discute el número con su contador.
    formula: str
    version: int
    fuentes: tuple[Fuente, ...]
    unidad: str = "PYG"
    # Por qué dimensión se puede abrir: sucursal, vendedor, producto…
    dimensiones: tuple[str, ...] = ()
    # Qué NO entra. Es la mitad de la definición y la que se olvida.
    excluye: str = ""
    notas_contables: str = ""


# ─────────────────────────────────────────────────────────────────────────
# El catálogo. Las definiciones viven en código —igual que los permisos y la
# clasificación de riesgo— porque un cambio en "qué es una venta" tiene que
# verse en el diff de un commit y pasar por revisión. La tabla de la base
# guarda el ESTADO de cada una por empresa (quién la aprobó, desde cuándo
# rige), no su fórmula.
# ─────────────────────────────────────────────────────────────────────────

CATALOGO: dict[str, Metrica] = {
    "ventas_brutas": Metrica(
        clave="ventas_brutas",
        nombre="Ventas brutas",
        formula="Suma de todo lo facturado, antes de descuentos, devoluciones y anulaciones.",
        version=1,
        fuentes=(Fuente.VENTAS,),
        dimensiones=("sucursal", "vendedor", "producto", "servicio"),
        excluye="Presupuestos y pedidos no facturados.",
    ),
    "ventas_netas": Metrica(
        clave="ventas_netas",
        nombre="Ventas netas",
        formula=(
            "Ventas brutas, menos descuentos, menos devoluciones, menos "
            "anulaciones."
        ),
        version=1,
        fuentes=(Fuente.VENTAS,),
        dimensiones=("sucursal", "vendedor", "producto", "servicio"),
        excluye="Impuestos que se cobran por cuenta del fisco.",
        notas_contables=(
            "Es el número que la mayoría de la gente quiere decir cuando dice "
            "'ventas'. No es lo mismo que lo cobrado: se puede facturar en "
            "agosto y cobrar en octubre."
        ),
    ),
    "cobrado": Metrica(
        clave="cobrado",
        nombre="Cobrado",
        formula=(
            "Pagos efectivamente recibidos y conciliados, menos los pagos "
            "revertidos o rechazados."
        ),
        version=1,
        fuentes=(Fuente.COBRANZAS,),
        dimensiones=("sucursal", "medio_de_pago"),
        excluye="Cheques no acreditados y pagos pendientes de conciliación.",
        notas_contables=(
            "Vender no es cobrar. La diferencia entre esta métrica y ventas "
            "netas es la pregunta que más se hace un dueño: 'vendí más y "
            "tengo menos plata'."
        ),
    ),
    "cuentas_por_cobrar": Metrica(
        clave="cuentas_por_cobrar",
        nombre="Cuentas por cobrar",
        formula=(
            "Facturas válidas emitidas, menos pagos aplicados, menos notas de "
            "crédito."
        ),
        version=1,
        fuentes=(Fuente.VENTAS, Fuente.COBRANZAS),
        dimensiones=("cliente", "sucursal", "antiguedad"),
        excluye="Facturas anuladas.",
    ),
    "margen_bruto": Metrica(
        clave="margen_bruto",
        nombre="Margen bruto",
        formula="Ventas netas, menos el costo de la mercadería vendida.",
        version=1,
        fuentes=(Fuente.VENTAS, Fuente.COMPRAS),
        dimensiones=("sucursal", "producto", "categoria"),
        excluye="Gastos operativos, sueldos, impuestos y gastos financieros.",
        notas_contables=(
            "NO es la ganancia. Llamarlo 'utilidad' hace que alguien reparta "
            "plata que todavía tiene que pagar el alquiler."
        ),
    ),
    "gastos": Metrica(
        clave="gastos",
        nombre="Gastos operativos",
        formula="Suma de gastos registrados del período, por categoría.",
        version=1,
        fuentes=(Fuente.GASTOS,),
        dimensiones=("categoria", "sucursal"),
        excluye="Compras de mercadería, que son costo y no gasto.",
    ),
    "entradas_de_caja": Metrica(
        clave="entradas_de_caja",
        nombre="Entradas de caja",
        formula="Dinero que entró de verdad en el período, por cualquier concepto.",
        version=1,
        fuentes=(Fuente.CAJA_Y_BANCOS,),
        dimensiones=("cuenta", "sucursal"),
    ),
    "salidas_de_caja": Metrica(
        clave="salidas_de_caja",
        nombre="Salidas de caja",
        formula="Dinero que salió de verdad en el período, por cualquier concepto.",
        version=1,
        fuentes=(Fuente.CAJA_Y_BANCOS,),
        dimensiones=("cuenta", "sucursal"),
    ),
    "flujo_de_caja": Metrica(
        clave="flujo_de_caja",
        nombre="Flujo de caja",
        formula="Entradas de caja menos salidas de caja.",
        version=1,
        fuentes=(Fuente.CAJA_Y_BANCOS,),
        dimensiones=("cuenta", "sucursal"),
        notas_contables=(
            "Es lo único que contesta '¿me alcanza para pagar el lunes?'. Una "
            "empresa puede tener margen y no tener caja."
        ),
    ),
    "cumplimiento_de_metas": Metrica(
        clave="cumplimiento_de_metas",
        nombre="Cumplimiento de metas",
        formula="Ventas netas del período dividido la meta cargada, en porcentaje.",
        version=1,
        fuentes=(Fuente.VENTAS, Fuente.METAS),
        unidad="%",
        dimensiones=("sucursal", "vendedor"),
    ),
    # ─── La que NO se habilita ───────────────────────────────────────────
    "utilidad_neta": Metrica(
        clave="utilidad_neta",
        nombre="Utilidad neta",
        formula=(
            "Ingresos reconocidos, menos costos, menos gastos operativos, "
            "menos gastos financieros, menos impuestos, menos otros egresos."
        ),
        version=1,
        fuentes=(
            Fuente.VENTAS, Fuente.COMPRAS, Fuente.GASTOS, Fuente.IMPUESTOS,
            Fuente.CAJA_Y_BANCOS, Fuente.NOMINA,
        ),
        excluye="Nada: es el resultado final. Por eso necesita TODAS las fuentes.",
        notas_contables=(
            "No se habilita mientras falte una sola de sus fuentes. Un número "
            "de utilidad calculado sin los impuestos o sin la nómina no está "
            "incompleto: está mal, y encima es el número con el que se "
            "reparten dividendos."
        ),
    ),
}


# Con qué fuentes cuenta hoy MetaBot.OS sin conectar nada de afuera. Las
# métricas que solo necesitan esto se pueden habilitar el primer día; las
# demás esperan a su conector (Fase 6).
FUENTES_INTERNAS = frozenset({Fuente.INTERNA, Fuente.VENTAS, Fuente.METAS})


def faltantes(clave: str, disponibles: frozenset[Fuente]) -> list[str]:
    """Qué fuentes le faltan a una métrica para poder calcularse."""
    m = CATALOGO.get(clave)
    if not m:
        return ["la métrica no existe"]
    return sorted(f.value for f in m.fuentes if f not in disponibles)


def se_puede_habilitar(clave: str, disponibles: frozenset[Fuente]) -> bool:
    return not faltantes(clave, disponibles)


def explicar_faltante(clave: str, disponibles: frozenset[Fuente]) -> str:
    """El mensaje honesto para el dueño cuando el dato no se puede calcular.

    Decir "no puedo" sin decir qué falta deja a alguien esperando un número
    que nunca va a llegar.
    """
    m = CATALOGO.get(clave)
    if not m:
        return "Esa métrica no existe en el catálogo."
    faltan = faltantes(clave, disponibles)
    if not faltan:
        return ""
    return (
        f"Con los datos conectados todavía no puedo calcular {m.nombre.lower()}. "
        f"Falta integrar: {', '.join(faltan)}."
    )
