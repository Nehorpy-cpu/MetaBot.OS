"""Cuánto lleva usado cada empresa este mes, y qué le queda.

Se cuenta sobre lo que YA existe —`agent_runs` y `finance_reports`— y no sobre
contadores propios. Un contador es una segunda verdad sobre lo mismo, y cuando
las dos no coinciden la que está mal es siempre la del contador: se
desincroniza con un reinicio, con una transacción que revierte, con un borrado
manual. Contar filas es más lento y es correcto.

El mes es el calendario, no treinta días móviles: el cliente entiende "se me
reinicia el 1°", y una ventana móvil obliga a explicar por qué ayer podía y
hoy no.
"""
from datetime import date, datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import planes
from .models import AgentRun, Company, FinanceReport


def _inicio_del_mes() -> datetime:
    hoy = datetime.now(timezone.utc).replace(tzinfo=None)
    return hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def mensajes_del_mes(db: Session, company_id: int) -> int:
    """Turnos que el bot contestó este mes. Uno por mensaje entrante."""
    return (
        db.query(func.count())
        .select_from(AgentRun)
        .filter(
            AgentRun.company_id == company_id,
            AgentRun.agent_slug == "cx",
            AgentRun.created_at >= _inicio_del_mes(),
        )
        .scalar()
    ) or 0


def informes_del_mes(db: Session, company_id: int) -> int:
    return (
        db.query(func.count())
        .select_from(FinanceReport)
        .filter(
            FinanceReport.company_id == company_id,
            FinanceReport.created_at >= _inicio_del_mes(),
        )
        .scalar()
    ) or 0


def tokens_del_mes(db: Session, company_id: int) -> dict:
    """Tokens y costo del mes, abierto por modelo.

    Abierto por modelo porque el costo por token es distinto en cada uno: un
    total de tokens sin decir de qué modelo no se puede convertir a plata.
    """
    filas = (
        db.query(
            AgentRun.model,
            func.sum(AgentRun.tokens_entrada),
            func.sum(AgentRun.tokens_salida),
            func.count(),
        )
        .filter(
            AgentRun.company_id == company_id,
            AgentRun.created_at >= _inicio_del_mes(),
        )
        .group_by(AgentRun.model)
        .all()
    )
    por_modelo = []
    total_gs = 0
    total_tokens = 0
    for modelo, entrada, salida, cuantos in filas:
        entrada = int(entrada or 0)
        salida = int(salida or 0)
        gs = planes.costo_gs(modelo or "", entrada, salida)
        total_gs += gs
        total_tokens += entrada + salida
        por_modelo.append({
            "modelo": modelo or "(sin registrar)",
            "turnos": cuantos,
            "tokens_entrada": entrada,
            "tokens_salida": salida,
            "costo_gs": gs,
            # Un modelo gratuito con tokens contados no es un error: es que no
            # se factura por token.
            "gratuito": gs == 0 and (entrada + salida) > 0,
        })
    return {
        "por_modelo": sorted(por_modelo, key=lambda x: -x["costo_gs"]),
        "tokens": total_tokens,
        "costo_gs": total_gs,
    }


def resumen(db: Session, company: Company) -> dict:
    """Lo que ve el cliente: cuánto usó, cuánto le queda, qué le cuesta.

    El costo se muestra SIEMPRE, incluso en los planes donde lo paga la
    plataforma. Un cliente que ve lo que consume entiende por qué el plan
    grande cuesta más, y el que pone su propia clave necesita el número para
    controlar su factura.
    """
    plan = planes.plan_de(company)
    mensajes = mensajes_del_mes(db, company.id)
    informes = informes_del_mes(db, company.id)
    uso = tokens_del_mes(db, company.id)
    return {
        "plan": {
            "clave": plan.clave,
            "nombre": plan.nombre,
            "precio_gs": plan.precio_gs,
            "clave_propia": plan.clave_propia,
        },
        "desde": _inicio_del_mes().date().isoformat(),
        "mensajes": {
            "usados": mensajes,
            "tope": plan.mensajes_por_mes,
            "restantes": max(0, plan.mensajes_por_mes - mensajes),
        },
        "informes": {
            "usados": informes,
            "tope": plan.informes_por_mes,
            "restantes": max(0, plan.informes_por_mes - informes),
        },
        "consumo_de_ia": uso,
        # La clave con la que se está atendiendo. Que el cliente lo sepa no es
        # un detalle: mientras diga "plataforma", el consumo lo paga MetaBot.
        "clave_en_uso": "propia" if company.openai_key_cifrada else "plataforma",
    }


def alcanza_mensajes(db: Session, company: Company) -> bool:
    plan = planes.plan_de(company)
    return mensajes_del_mes(db, company.id) < plan.mensajes_por_mes


def alcanza_informes(db: Session, company: Company) -> bool:
    plan = planes.plan_de(company)
    return informes_del_mes(db, company.id) < plan.informes_por_mes


def alcanza_identidades(db: Session, company: Company) -> bool:
    """Cuántos números del CFO puede tener. Se cuentan los ACTIVOS: dar de
    baja a uno tiene que liberar el lugar, si no el cliente queda atrapado
    por gente que ya no trabaja ahí."""
    from .models import FinanceIdentity

    plan = planes.plan_de(company)
    cuantas = (
        db.query(func.count())
        .select_from(FinanceIdentity)
        .filter(
            FinanceIdentity.company_id == company.id,
            FinanceIdentity.activo.is_(True),
        )
        .scalar()
    ) or 0
    return cuantas < plan.identidades_cfo


def alcanza_conectores(db: Session, company: Company) -> bool:
    from .models import FinanceConnector

    plan = planes.plan_de(company)
    cuantos = (
        db.query(func.count())
        .select_from(FinanceConnector)
        .filter(FinanceConnector.company_id == company.id)
        .scalar()
    ) or 0
    return cuantos < plan.conectores


def aviso_de_cupo(company: Company, que: str) -> str:
    """Este SÍ le habla a quien administra, que es quien puede cambiar el
    plan. Es la conversación opuesta a la del tope de mensajes: ahí del otro
    lado hay un cliente que no tiene la culpa; acá, alguien que compró un plan
    y quiere más."""
    plan = planes.plan_de(company)
    cuanto = (plan.identidades_cfo if que == "identidades" else plan.conectores)
    cosa = "números autorizados" if que == "identidades" else "conectores"
    return (
        f"El plan {plan.nombre} incluye {cuanto} {cosa}. Para agregar más hay "
        "que pasar a un plan mayor."
    )


def aviso_de_tope(company: Company, que: str) -> str:
    """Lo que se le dice a la persona del otro lado.

    Se le habla al CLIENTE FINAL, que no tiene idea de que existe un plan y no
    tiene la culpa. Nada de "cuota excedida": eso es vocabulario nuestro y
    hace quedar mal al negocio que nos contrató.
    """
    if que == "mensajes":
        return (
            "Por hoy no puedo seguir contestando por acá. Escribinos de nuevo "
            "más tarde o llamanos y te atendemos."
        )
    return (
        "Este mes ya se emitieron todos los informes del plan. Se puede "
        "ampliar desde el panel."
    )
