"""claves foráneas compuestas en el resto de las tablas del tenant

Revision ID: a07c5f2be913
Revises: f61e9d3a08c7
Create Date: 2026-08-11 03:30:00.000000

Completa el principio innegociable #1: el aislamiento entre empresas vive en
la capa de datos. Ya estaba doctor_services; ahora van citas, mensajes,
supervisiones, hallazgos, sugerencias de prompt, recetas y coberturas.

La clave SIMPLE se elimina: junto a la compuesta crea dos caminos entre las
mismas tablas y SQLAlchemy no puede resolver el join (lo comprobamos, la suite
entera se cayó con AmbiguousForeignKeysError).

Orden: limpiar cruces y huérfanos → recién entonces las restricciones. Un
INSERT que ya cruzaba empresas era inválido: se borra y se informa.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a07c5f2be913'
down_revision: Union[str, None] = 'f61e9d3a08c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (hija, columna, padre, nombre de la restricción, borrado en cascada)
COMPUESTAS = [
    ("appointments", "doctor_id", "doctors", "fk_appointments_doctor_tenant", False),
    ("messages", "conversation_id", "conversations", "fk_messages_conversation_tenant", True),
    ("supervisions", "conversation_id", "conversations", "fk_supervisions_conversation_tenant", False),
    ("audit_findings", "conversation_id", "conversations", "fk_audit_findings_conversation_tenant", False),
    ("prompt_suggestions", "agent_id", "agents", "fk_prompt_suggestions_agent_tenant", False),
    ("prescriptions", "doctor_id", "doctors", "fk_prescriptions_doctor_tenant", False),
    ("prescription_items", "prescription_id", "prescriptions", "fk_prescription_items_tenant", True),
    ("service_coverages", "insurer_id", "insurers", "fk_coverage_insurer_tenant", False),
    ("service_coverages", "service_id", "services", "fk_coverage_service_tenant", False),
]

# Padres que todavía no tenían UNIQUE(company_id, id).
PADRES = [
    ("conversations", "uq_conversation_company_id"),
    ("agents", "uq_agent_company_id"),
    ("prescriptions", "uq_prescription_company_id"),
    ("insurers", "uq_insurer_company_id"),
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # En SQLite las restricciones se crean con la tabla: los tests usan
        # create_all sobre el modelo, que ya las declara compuestas.
        return

    # 1) Limpieza ANTES de las restricciones: si queda un cruce, la migración
    #    falla y el backend no arranca.
    for hija, col, padre, _, _ in COMPUESTAS:
        cruces = bind.execute(sa.text(
            f"SELECT count(*) FROM {hija} h JOIN {padre} p ON p.id = h.{col} "
            f"WHERE h.company_id <> p.company_id"
        )).scalar() or 0
        huerfanos = bind.execute(sa.text(
            f"SELECT count(*) FROM {hija} h "
            f"WHERE h.{col} IS NOT NULL "
            f"  AND NOT EXISTS (SELECT 1 FROM {padre} p WHERE p.id = h.{col})"
        )).scalar() or 0
        if cruces or huerfanos:
            print(f"[migración] {hija}.{col}: {cruces} cruces entre empresas y "
                  f"{huerfanos} huérfanos. Se eliminan: ya eran filas inválidas.")
            op.execute(sa.text(
                f"DELETE FROM {hija} WHERE id IN ("
                f" SELECT h.id FROM {hija} h LEFT JOIN {padre} p ON p.id = h.{col}"
                f" WHERE h.{col} IS NOT NULL AND (p.id IS NULL OR h.company_id <> p.company_id))"
            ))

    # 2) UNIQUE(company_id, id) en los padres que faltaban.
    for tabla, nombre in PADRES:
        existe = bind.execute(sa.text(
            "SELECT 1 FROM pg_constraint WHERE conname = :n"
        ), {"n": nombre}).scalar()
        if not existe:
            op.create_unique_constraint(nombre, tabla, ["company_id", "id"])

    # 3) Fuera las claves simples que apuntan al mismo padre: quedan
    #    redundantes y crean un segundo camino entre las tablas.
    for hija, col, padre, _, _ in COMPUESTAS:
        for fila in bind.execute(sa.text(
            # cast() explícito y no `::regclass`: los dos puntos del cast se
            # confunden con el marcador de parámetro :hija y PostgreSQL da
            # error de sintaxis.
            "SELECT c.conname FROM pg_constraint c "
            "WHERE c.conrelid = cast(:hija AS regclass) AND c.contype = 'f' "
            "  AND c.confrelid = cast(:padre AS regclass) "
            "  AND array_length(c.conkey, 1) = 1"
        ), {"hija": hija, "padre": padre}).fetchall():
            op.drop_constraint(fila[0], hija, type_="foreignkey")

    # 4) Recién ahora: el motor impide el cruce.
    for hija, col, padre, nombre, cascada in COMPUESTAS:
        op.create_foreign_key(
            nombre, hija, padre,
            ["company_id", col], ["company_id", "id"],
            ondelete="CASCADE" if cascada else None,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for hija, col, padre, nombre, _ in COMPUESTAS:
        op.drop_constraint(nombre, hija, type_="foreignkey")
        op.create_foreign_key(None, hija, padre, [col], ["id"])
    for tabla, nombre in PADRES:
        op.drop_constraint(nombre, tabla, type_="unique")
