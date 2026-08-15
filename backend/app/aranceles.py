"""La aritmética del dinero: convenios, coberturas y honorarios.

Vive en un módulo propio y no adentro de `chat.py` porque ahora hay dos
lugares que necesitan el MISMO número:

- el bot, cuando le dice al paciente cuánto le sale un estudio con su seguro;
- la planilla de honorarios, cuando le dice al profesional cuánto le tiene
  que pagar esa misma aseguradora por esa misma atención.

Si cada uno hiciera su propia cuenta, la diferencia no aparecería como un
error: aparecería como una discusión con el paciente en la caja, o como una
planilla que la aseguradora rechaza. Una sola función, un solo número.

Todo en guaraníes enteros. Nunca float: 0.1 + 0.2 no es 0.3, y acá cada
redondeo es plata de alguien.
"""
from dataclasses import dataclass

from sqlalchemy.orm import Session

from .models import Insurer, Service, ServiceCoverage
from .textos import formato_gs, normalizar


@dataclass(frozen=True)
class Cobertura:
    """Lo que el convenio dice para un servicio puntual."""

    cobertura_pct: int
    copago_gs: int
    excluido: bool
    # De dónde salió: el convenio general o una excepción para ese estudio.
    # Sirve para explicar un número que al profesional le puede parecer raro.
    origen: str
    # Monto fijo que paga la aseguradora por esta práctica, cargado a mano
    # desde su nomenclador. 0 = no configurado y se calcula por porcentaje.
    arancel_gs: int = 0


@dataclass(frozen=True)
class Montos:
    """Cómo se reparte el precio de lista entre paciente y aseguradora."""

    precio_lista_gs: int
    paga_el_paciente_gs: int
    paga_el_seguro_gs: int
    excluido: bool
    # El monto de la aseguradora salió de un arancel cargado a mano, no de un
    # porcentaje. Se propaga para poder decirlo en la planilla.
    arancel_manual: bool = False


def buscar_convenio(db: Session, company_id: int, pedido: str) -> Insurer | None:
    """Encuentra el convenio que el paciente nombró, como lo nombró.

    El paciente escribe "nanduti plan oro" y el convenio se llama
    "Seguro Ñandutí". Se compara sin tildes ni ñ, y también contra el plan:
    dos planes de la misma prepaga cubren distinto, así que confundirlos es
    darle al paciente un precio que no es el suyo.

    El convenio lo cargó ESTA empresa. No hay una base compartida de
    aseguradoras: eso sería inventar acuerdos comerciales que no existen.
    """
    buscado = normalizar(pedido).strip()
    if not buscado:
        return None
    convenios = (
        db.query(Insurer)
        .filter(Insurer.company_id == company_id, Insurer.active)
        .all()
    )
    for i in convenios:
        nombre = normalizar(i.name)
        completo = normalizar(f"{i.name} {i.plan}").strip()
        plan = normalizar(i.plan)
        if nombre in buscado or buscado in completo:
            # Si el paciente nombró un plan, tiene que coincidir.
            if not plan or plan in buscado or not any(
                normalizar(o.plan) in buscado
                for o in convenios
                if normalizar(o.name) == nombre
            ):
                return i
    return None


def convenios_activos(db: Session, company_id: int, limite: int = 15) -> list[str]:
    """Los convenios que sí tiene, para poder ser honesto con el que no."""
    return [
        f"{i.name} {i.plan}".strip()
        for i in db.query(Insurer)
        .filter(Insurer.company_id == company_id, Insurer.active)
        .limit(limite)
        .all()
    ]


def cobertura_de(
    db: Session, company_id: int, insurer: Insurer, service: Service | None
) -> Cobertura:
    """Qué cubre ese convenio para ese servicio.

    El convenio trae una cobertura general; un servicio puntual puede tener
    su propia excepción, y hay estudios que directamente no están cubiertos.
    """
    if service is None:
        return Cobertura(insurer.coverage_pct, insurer.copay_gs, False, "convenio")
    override = (
        db.query(ServiceCoverage)
        .filter(
            ServiceCoverage.company_id == company_id,
            ServiceCoverage.insurer_id == insurer.id,
            ServiceCoverage.service_id == service.id,
        )
        .first()
    )
    if override:
        return Cobertura(
            override.coverage_pct, override.copay_gs, override.excluded,
            "arancel del convenio" if override.arancel_gs > 0
            else "excepción para este estudio",
            arancel_gs=override.arancel_gs,
        )
    return Cobertura(insurer.coverage_pct, insurer.copay_gs, False, "convenio")


def repartir(precio_gs: int, cobertura: Cobertura | None) -> Montos:
    """Cuánto pone el paciente y cuánto la aseguradora.

    Sin convenio (particular) o con el estudio excluido, paga todo el
    paciente. El copago es un fijo que se le cobra ADEMÁS de su parte —así
    está definido el convenio— y no sale del bolsillo de la aseguradora.

    Hay dos formas de saber cuánto pone la aseguradora, y la primera manda:

    1. **El arancel cargado a mano.** Es como funciona de verdad: cada
       aseguradora tiene su nomenclador con un monto fijo por práctica. Si
       está configurado se usa TAL CUAL, sin recalcular nada. Puede ser mayor
       que el precio de lista de la clínica —pasa— y en ese caso el paciente
       no pone nada.
    2. **El porcentaje**, para lo que todavía no tiene arancel cargado. Se
       reparte sobre el precio de lista calculando primero la parte de la
       aseguradora y dejando el resto al paciente, para que las dos sumen
       exactamente el precio y no se pierda ni se invente un guaraní.
    """
    precio = max(0, int(precio_gs or 0))
    if cobertura is None or cobertura.excluido:
        return Montos(precio, precio, 0, cobertura.excluido if cobertura else False)

    copago = max(0, cobertura.copago_gs)
    if cobertura.arancel_gs > 0:
        del_seguro = int(cobertura.arancel_gs)
        # Lo que la clínica le cobra al paciente es lo que falta para llegar a
        # su precio. Si el arancel lo cubre entero, no paga nada (salvo el
        # copago, que es aparte por definición del convenio).
        del_paciente = max(0, precio - del_seguro) + copago
        return Montos(precio, del_paciente, del_seguro, False, arancel_manual=True)

    pct = max(0, min(100, cobertura.cobertura_pct))
    del_seguro = round(precio * pct / 100)
    del_paciente = precio - del_seguro + copago
    return Montos(precio, del_paciente, del_seguro, False)


def honorario_gs(facturado_gs: int, honorario_pct: int) -> int:
    """Lo que le corresponde al profesional de lo facturado.

    En un sanatorio el profesional cobra un porcentaje y la institución
    retiene el resto; un consultorio propio pone 100. El porcentaje es del
    profesional y no de la clínica entera porque no todos arreglan igual.
    """
    return round(max(0, int(facturado_gs or 0)) * max(0, min(100, honorario_pct)) / 100)


# Re-exportado para que quien arma una planilla no tenga que saber que el
# formateo de guaraníes vive en otro módulo.
__all__ = [
    "Cobertura", "Montos", "buscar_convenio", "cobertura_de", "convenios_activos",
    "formato_gs", "honorario_gs", "repartir",
]
