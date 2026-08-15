"""CFO: en qué estado está cada métrica para cada empresa

La FÓRMULA no va en la base: vive en `app/cfo_metricas.py`, porque cambiar qué
significa "venta" tiene que verse en el diff de un commit y pasar por
revisión. Esta tabla guarda lo que sí es propio de cada empresa: qué versión
aprobó, quién la aprobó y desde cuándo rige.

Sin fila en estado `activa`, el CFO NO usa esa métrica. Deny by default: una
métrica que nadie aprobó no puede contestarle un número al dueño.

Revision ID: a7c3e91d24f8
Revises: f2a4d6b19c53
"""
import sqlalchemy as sa
from alembic import op

revision = "a7c3e91d24f8"
down_revision = "f2a4d6b19c53"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "finance_metric_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("clave", sa.String(60), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("estado", sa.String(12), nullable=False, server_default="borrador"),
        sa.Column("aprobada_por", sa.Integer(), nullable=True),
        sa.Column("aprobada_at", sa.DateTime(), nullable=True),
        sa.Column("vigente_desde", sa.Date(), nullable=True),
        sa.Column("notas", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        # Una sola fila por métrica y empresa: dos versiones activas de
        # "ventas netas" es exactamente el problema que esto viene a resolver.
        sa.UniqueConstraint("company_id", "clave", name="uq_metric_state_clave"),
    )
    op.create_index("ix_finance_metric_states_company_id", "finance_metric_states", ["company_id"])
    op.create_index("ix_finance_metric_states_clave", "finance_metric_states", ["clave"])
    op.create_index("ix_finance_metric_states_estado", "finance_metric_states", ["estado"])


def downgrade() -> None:
    op.drop_table("finance_metric_states")
