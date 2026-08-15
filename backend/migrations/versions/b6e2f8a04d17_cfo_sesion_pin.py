"""CFO: la consulta que quedó esperando el PIN

Cuando la consulta es sensible el bot pide el PIN, y el dueño lo escribe en el
chat. Sin esta tabla ese mensaje se guarda en `messages` y viaja al historial
del modelo: el PIN termina escrito en el WhatsApp de un teléfono que se puede
perder, y en la base.

Con la consulta pendiente guardada acá, el servidor reconoce el mensaje
siguiente como un PIN, lo tacha antes de guardarlo, resuelve la consulta
original por su cuenta y nunca se lo pasa a ninguna IA.

Revision ID: b6e2f8a04d17
Revises: a7c3e91d24f8
"""
import sqlalchemy as sa
from alembic import op

revision = "b6e2f8a04d17"
down_revision = "a7c3e91d24f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "finance_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("phone", sa.String(30), nullable=False),
        sa.Column("metrica", sa.String(60), nullable=False, server_default=""),
        sa.Column("desde", sa.Date(), nullable=True),
        sa.Column("hasta", sa.Date(), nullable=True),
        sa.Column("pin_pedido_hasta", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("company_id", "phone", name="uq_finance_session_phone"),
    )
    op.create_index("ix_finance_sessions_company_id", "finance_sessions", ["company_id"])
    op.create_index("ix_finance_sessions_phone", "finance_sessions", ["phone"])


def downgrade() -> None:
    op.drop_table("finance_sessions")
