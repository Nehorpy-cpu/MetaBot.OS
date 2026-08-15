"""Cuánto puede usar cada cliente, y cuánto le cuesta eso a la plataforma.

Son dos ejes distintos y hay que no confundirlos:

- **Los bloques (`packs.py`) dicen QUÉ compró**: agenda, salud, portal, CFO.
- **El plan dice CUÁNTO puede usar**: mensajes por mes, informes por mes.

Un sanatorio grande y una veterinaria chica pueden tener los mismos bloques y
consumos que se diferencian en un orden de magnitud. Meter el volumen adentro
del bloque obligaría a vender "agenda chica" y "agenda grande", que son el
mismo software.

## Por qué hay tope

Desde que la tarea `finanzas` corre con un modelo pago, cada mensaje cuesta
plata de verdad. Sin tope, un cliente de plan chico con un integrador mal
escrito consume el margen de diez clientes buenos, y nadie se entera hasta la
factura.

## De dónde salen los números

De medir, no de suponer. `agent_runs` guarda los tokens de cada turno desde el
15-ago-2026, y `costo_de()` los convierte a guaraníes con la tarifa publicada
del modelo. Los topes de abajo se fijaron para que el costo de IA quede en una
fracción chica del precio: si un cliente agota su plan, el mes sigue siendo
rentable.

**Los precios son una propuesta, no una tarifa vigente.** Salen del costo
medido más margen; hay que contrastarlos con lo que el mercado paraguayo paga
por un CRM o un sistema de turnos antes de publicarlos.
"""
from dataclasses import dataclass

# Tarifas de OpenAI por millón de tokens, en dólares, al 15-ago-2026.
# Están acá y no en la base porque cambian por decisión de un proveedor, no
# por configuración de un cliente: cuando cambien, se ve en el diff.
USD_POR_MILLON_ENTRADA = {"gpt-4o-mini": 0.15}
USD_POR_MILLON_SALIDA = {"gpt-4o-mini": 0.60}
# Audio, por minuto.
USD_POR_MINUTO_TRANSCRIPCION = 0.003   # gpt-4o-mini-transcribe
USD_POR_MILLON_TTS = 0.60              # gpt-4o-mini-tts, por token de texto

# Cotización de referencia. Es un dato que se mueve: acá va para poder mostrar
# un número en guaraníes, no para contabilidad.
GS_POR_USD = 7300


@dataclass(frozen=True)
class Plan:
    clave: str
    nombre: str
    descripcion: str
    # Mensajes entrantes que el bot contesta por mes. Es la unidad que el
    # cliente entiende ("cuántas consultas atiende") y también la que cuesta.
    mensajes_por_mes: int
    # Informes privados emitidos por mes. Cada uno es un cálculo y un enlace.
    informes_por_mes: int
    # Números de WhatsApp autorizados a consultar finanzas.
    identidades_cfo: int
    # Conectores de datos activos.
    conectores: int
    # Precio mensual PROPUESTO, en guaraníes. Ver la nota del encabezado.
    precio_gs: int
    # Si el cliente pone SU propia clave de OpenAI, la plataforma no paga los
    # tokens. Los planes grandes lo exigen justamente por eso.
    clave_propia: bool = False


PRUEBA = Plan(
    clave="prueba",
    nombre="Prueba",
    descripcion=(
        "Para conocer el sistema. Alcanza para probarlo con clientes reales "
        "durante unos días, no para operar."
    ),
    mensajes_por_mes=200,
    informes_por_mes=5,
    identidades_cfo=1,
    conectores=1,
    precio_gs=0,
)

BASICO = Plan(
    clave="basico",
    nombre="Básico",
    descripcion=(
        "Un negocio que atiende su WhatsApp todo el día: turnos, precios, "
        "consultas. Un solo dueño mirando los números."
    ),
    mensajes_por_mes=2_000,
    informes_por_mes=30,
    identidades_cfo=2,
    conectores=2,
    precio_gs=350_000,
)

PROFESIONAL = Plan(
    clave="profesional",
    nombre="Profesional",
    descripcion=(
        "Varias personas del equipo consultando, más de una sucursal, y el "
        "sistema de facturación conectado."
    ),
    mensajes_por_mes=8_000,
    informes_por_mes=150,
    identidades_cfo=6,
    conectores=6,
    precio_gs=990_000,
)

EMPRESA = Plan(
    clave="empresa",
    nombre="Empresa",
    descripcion=(
        "Volumen alto. A este nivel conviene que la empresa ponga su propia "
        "clave de OpenAI: paga el consumo directo al proveedor, sin margen "
        "nuestro encima, y le queda la factura a su nombre."
    ),
    mensajes_por_mes=40_000,
    informes_por_mes=1_000,
    identidades_cfo=25,
    conectores=20,
    precio_gs=2_400_000,
    clave_propia=True,
)


PLANES: dict[str, Plan] = {
    p.clave: p for p in (PRUEBA, BASICO, PROFESIONAL, EMPRESA)
}

PLAN_POR_DEFECTO = "prueba"


def plan_de(company) -> Plan:
    """El plan de una empresa. Si trae uno que ya no existe, cae al de prueba.

    Cae al MÁS CHICO a propósito: un plan desconocido no puede terminar
    habilitando el consumo más grande.
    """
    return PLANES.get(getattr(company, "plan", "") or "", PRUEBA)


def costo_gs(modelo: str, tokens_entrada: int, tokens_salida: int) -> int:
    """Cuánto costó ese turno, en guaraníes enteros.

    Devuelve 0 para los modelos gratuitos: no es que no cuesten nada de
    operar, es que no los facturamos por token.
    """
    entrada = USD_POR_MILLON_ENTRADA.get(modelo)
    salida = USD_POR_MILLON_SALIDA.get(modelo)
    if entrada is None or salida is None:
        return 0
    usd = (tokens_entrada / 1_000_000) * entrada + (tokens_salida / 1_000_000) * salida
    return int(round(usd * GS_POR_USD))


def costo_usd(modelo: str, tokens_entrada: int, tokens_salida: int) -> float:
    entrada = USD_POR_MILLON_ENTRADA.get(modelo)
    salida = USD_POR_MILLON_SALIDA.get(modelo)
    if entrada is None or salida is None:
        return 0.0
    return (tokens_entrada / 1_000_000) * entrada + (tokens_salida / 1_000_000) * salida


def catalogo() -> list[dict]:
    """Lo que se le muestra a quien va a comprar."""
    return [
        {
            "clave": p.clave,
            "nombre": p.nombre,
            "descripcion": p.descripcion,
            "mensajes_por_mes": p.mensajes_por_mes,
            "informes_por_mes": p.informes_por_mes,
            "identidades_cfo": p.identidades_cfo,
            "conectores": p.conectores,
            "precio_gs": p.precio_gs,
            "clave_propia": p.clave_propia,
        }
        for p in PLANES.values()
    ]
