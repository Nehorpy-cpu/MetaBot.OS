"""CFO de Finanzas: quién puede preguntar qué, y con qué prueba.

Este módulo NO calcula plata. Decide dos cosas antes de que se calcule nada:

1. **Quién está preguntando.** El número de WhatsApp es la primera llave, no
   la identidad. Un WhatsApp se clona, se hereda con un chip reciclado y se
   pierde en un taxi; del otro lado se contestan saldos bancarios.
2. **Cuánto pesa la pregunta.** "¿Cuánto vendimos hoy?" y "¿cuánto hay en el
   banco?" no pueden costar lo mismo en pruebas.

La clasificación vive en código y no en la base a propósito: un cambio de
"qué es sensible" tiene que verse en el diff de un commit y pasar por
revisión, igual que los permisos (`app/permissions.py`). Editarlo en caliente
desde un panel es la forma de que un día el saldo bancario amanezca en riesgo
bajo y nadie sepa quién lo movió.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy.orm import Session

from .auth import hash_password, verify_password
from .models import Company, FinanceIdentity


class Riesgo(str, Enum):
    """Cuánto duele que este dato salga por el número equivocado."""

    BAJA = "baja"
    MEDIA = "media"
    ALTA = "alta"


# Orden explícito: `Riesgo` es un Enum de strings y comparar "media" > "baja"
# alfabéticamente da la respuesta equivocada.
_PESO = {Riesgo.BAJA: 0, Riesgo.MEDIA: 1, Riesgo.ALTA: 2}


def alcanza(techo: str, pedido: Riesgo) -> bool:
    """¿El techo de esta identidad cubre una consulta de ese riesgo?"""
    try:
        return _PESO[Riesgo(techo)] >= _PESO[pedido]
    except ValueError:
        # Un valor guardado que no es un riesgo válido no se interpreta como
        # permisivo: se trata como el mínimo.
        return pedido is Riesgo.BAJA


# Qué riesgo tiene cada métrica. Lo que NO está acá se trata como ALTA: una
# métrica nueva sin clasificar no puede nacer siendo pública.
RIESGO_POR_METRICA: dict[str, Riesgo] = {
    # Lo que cualquiera en el mostrador ya ve
    "ventas_brutas": Riesgo.BAJA,
    "ventas_netas": Riesgo.BAJA,
    "cumplimiento_de_metas": Riesgo.BAJA,
    # Lo que le sirve a un competidor o a un empleado
    "margen_bruto": Riesgo.MEDIA,
    "gastos": Riesgo.MEDIA,
    "cuentas_por_cobrar": Riesgo.MEDIA,
    "cobrado": Riesgo.MEDIA,
    # Lo que no se le muestra ni al contador sin que el dueño lo sepa
    "entradas_de_caja": Riesgo.ALTA,
    "salidas_de_caja": Riesgo.ALTA,
    "flujo_de_caja": Riesgo.ALTA,
    "utilidad_neta": Riesgo.ALTA,
}

def riesgo_de(metricas: list[str]) -> Riesgo:
    """El riesgo de una consulta es el de su métrica MÁS sensible.

    Preguntar "ventas y saldo bancario" en un mismo mensaje no puede colarse
    como consulta de riesgo bajo porque la primera lo sea.
    """
    peor = Riesgo.BAJA
    for m in metricas:
        r = RIESGO_POR_METRICA.get(m, Riesgo.ALTA)
        if _PESO[r] > _PESO[peor]:
            peor = r
    return peor


# ─── Identidad ───────────────────────────────────────────────────────────

MINUTOS_DE_BLOQUEO = 15
INTENTOS_DE_PIN = 5
LARGO_MINIMO_DE_PIN = 4


def solo_digitos(telefono: str) -> str:
    """`+595 981 123-456` → `595981123456`.

    Se guarda y se compara normalizado: dos formatos del mismo número son dos
    identidades distintas para una restricción de unicidad, y ahí el dueño
    queda con dos permisos que nadie sabe cuál manda.
    """
    return "".join(c for c in (telefono or "") if c.isdigit())


@dataclass(frozen=True)
class Veredicto:
    """Si la consulta puede seguir, y qué falta si no."""

    ok: bool
    identidad: FinanceIdentity | None = None
    # Código estructurado, NUNCA texto: quien decide con esto no puede
    # depender de una redacción que alguien va a mejorar.
    codigo: str = ""
    motivo: str = ""
    riesgo: Riesgo = Riesgo.BAJA


def _ahora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def identidad_de(db: Session, company_id: int, telefono: str) -> FinanceIdentity | None:
    """La identidad autorizada de ese número EN ESA EMPRESA.

    El filtro por empresa no es opcional ni una optimización: el mismo número
    puede ser dueño de tres negocios y ver distinto en cada uno.
    """
    digitos = solo_digitos(telefono)
    if not digitos:
        return None
    return (
        db.query(FinanceIdentity)
        .filter(
            FinanceIdentity.company_id == company_id,
            FinanceIdentity.phone == digitos,
        )
        .first()
    )


def empresas_de(db: Session, telefono: str) -> list[tuple[int, str]]:
    """Todas las empresas donde ese número está autorizado.

    Para el caso "tenés acceso a tres empresas, ¿cuál querés consultar?". La
    empresa activa la resuelve el servidor con esto; el modelo no la elige.
    """
    digitos = solo_digitos(telefono)
    if not digitos:
        return []
    filas = (
        db.query(FinanceIdentity, Company)
        .join(Company, Company.id == FinanceIdentity.company_id)
        .filter(FinanceIdentity.phone == digitos, FinanceIdentity.activo)
        .order_by(Company.name)
        .all()
    )
    return [(c.id, c.name) for _, c in filas]


def autorizar(
    db: Session, company_id: int, telefono: str, riesgo: Riesgo,
    pin: str | None = None,
) -> Veredicto:
    """¿Puede este número hacer esta consulta, ahora?

    El orden importa. Primero se descarta al desconocido —sin decirle qué
    empresa existe ni por qué no—, después el techo de sensibilidad, y recién
    al final se pide el PIN. Pedirle el PIN a alguien que igual no tiene
    permiso le confirma que el número está dado de alta en algún lado.
    """
    identidad = identidad_de(db, company_id, telefono)
    if identidad is None or not identidad.activo:
        return Veredicto(
            False, None, "no_autorizado",
            "Este número no está autorizado para consultar datos de la empresa.",
            riesgo,
        )

    if not alcanza(identidad.sensibilidad_max, riesgo):
        return Veredicto(
            False, identidad, "sensibilidad_insuficiente",
            "Tu usuario no tiene habilitado ese nivel de información. "
            "Pedíselo a quien administra la empresa.",
            riesgo,
        )

    if riesgo is Riesgo.BAJA:
        return Veredicto(True, identidad, "", "", riesgo)

    # De acá para abajo hace falta PIN.
    if not identidad.pin_hash:
        return Veredicto(
            False, identidad, "pin_no_configurado",
            "Para esta consulta necesitás un PIN y todavía no configuraste "
            "uno. Se configura desde el panel.",
            riesgo,
        )

    bloqueo = identidad.pin_bloqueado_hasta
    if bloqueo and bloqueo > _ahora():
        faltan = int((bloqueo - _ahora()).total_seconds() // 60) + 1
        return Veredicto(
            False, identidad, "pin_bloqueado",
            f"Demasiados intentos. Probá de nuevo en {faltan} minutos.",
            riesgo,
        )

    if not pin:
        return Veredicto(
            False, identidad, "pin_requerido",
            "Esa consulta es sensible: mandame tu PIN para continuar.",
            riesgo,
        )

    if not verify_password(pin, identidad.pin_hash):
        identidad.pin_intentos += 1
        if identidad.pin_intentos >= INTENTOS_DE_PIN:
            # Se bloquea el PIN, NO la identidad: un atacante que prueba
            # números no puede dejar al dueño afuera para siempre.
            identidad.pin_bloqueado_hasta = _ahora() + timedelta(minutes=MINUTOS_DE_BLOQUEO)
            identidad.pin_intentos = 0
        db.commit()
        return Veredicto(
            False, identidad, "pin_incorrecto", "El PIN no es correcto.", riesgo,
        )

    identidad.pin_intentos = 0
    identidad.pin_bloqueado_hasta = None
    identidad.ultimo_uso_at = _ahora()
    db.commit()
    return Veredicto(True, identidad, "", "", riesgo)


def guardar_pin(db: Session, identidad: FinanceIdentity, pin: str) -> None:
    """Guarda el PIN hasheado. Nunca en texto plano, ni en logs, ni de vuelta."""
    limpio = (pin or "").strip()
    if len(limpio) < LARGO_MINIMO_DE_PIN or not limpio.isdigit():
        raise ValueError(
            f"El PIN tiene que ser de al menos {LARGO_MINIMO_DE_PIN} dígitos."
        )
    identidad.pin_hash = hash_password(limpio)
    identidad.pin_intentos = 0
    identidad.pin_bloqueado_hasta = None
    db.commit()


FUERA_DE_ALCANCE = (
    "Estoy configurado para analizar las finanzas, ventas y datos operativos "
    "de esta empresa. Puedo ayudarte con esos datos."
)


# ─── La consulta pendiente ───────────────────────────────────────────────
#
# Cuando el bot pide el PIN, la persona lo escribe en el chat. Sin esto, ese
# mensaje se guarda en la base y viaja al historial del modelo: el PIN queda
# escrito en un WhatsApp que se puede perder.

MINUTOS_DE_ESPERA_DE_PIN = 5


def es_pin(texto: str) -> bool:
    """¿Este mensaje parece un PIN y nada más?

    Se exige que sea SOLO dígitos: "el pin es 4721" no se tacha, porque ahí
    la persona ya escribió el PIN dentro de una frase y tacharlo a medias da
    una falsa sensación de que se cuidó.
    """
    limpio = (texto or "").strip()
    return limpio.isdigit() and LARGO_MINIMO_DE_PIN <= len(limpio) <= 12


def pedir_pin(db: Session, company_id: int, telefono: str, metrica: str,
              desde=None, hasta=None) -> bool:
    """Deja anotado qué se estaba preguntando, para poder retomarlo.

    Devuelve False —y no anota nada— si esa métrica NO necesita PIN. Un
    pedido de PIN abierto para una consulta de riesgo bajo se traga cualquier
    número de cuatro cifras que la persona escriba después, y encima nunca lo
    valida: la respuesta sale igual con el PIN equivocado.
    """
    from .models import FinanceSession

    if riesgo_de([metrica]) is Riesgo.BAJA:
        return False

    digitos = solo_digitos(telefono)
    fila = (
        db.query(FinanceSession)
        .filter(FinanceSession.company_id == company_id,
                FinanceSession.phone == digitos)
        .first()
    )
    if fila is None:
        fila = FinanceSession(company_id=company_id, phone=digitos)
        db.add(fila)
    fila.metrica = metrica
    fila.desde = desde
    fila.hasta = hasta
    fila.pin_pedido_hasta = _ahora() + timedelta(minutes=MINUTOS_DE_ESPERA_DE_PIN)
    fila.updated_at = _ahora()
    db.commit()
    return True


def consulta_pendiente(db: Session, company_id: int, telefono: str):
    """La consulta que quedó esperando el PIN, si sigue vigente."""
    from .models import FinanceSession

    fila = (
        db.query(FinanceSession)
        .filter(
            FinanceSession.company_id == company_id,
            FinanceSession.phone == solo_digitos(telefono),
        )
        .first()
    )
    if not fila or not fila.pin_pedido_hasta or fila.pin_pedido_hasta < _ahora():
        return None
    return fila


def cerrar_pendiente(db: Session, company_id: int, telefono: str) -> None:
    """Se resolvió o se abandonó: el pedido de PIN deja de estar abierto."""
    from .models import FinanceSession

    fila = (
        db.query(FinanceSession)
        .filter(
            FinanceSession.company_id == company_id,
            FinanceSession.phone == solo_digitos(telefono),
        )
        .first()
    )
    if fila:
        fila.pin_pedido_hasta = None
        fila.metrica = ""
        db.commit()


# Lo que se guarda EN LUGAR del PIN. Que se vea que hubo un mensaje —si no,
# la conversación queda con un hueco inexplicable— sin guardar el valor.
PIN_TACHADO = "[PIN enviado por el usuario · no se guarda]"
