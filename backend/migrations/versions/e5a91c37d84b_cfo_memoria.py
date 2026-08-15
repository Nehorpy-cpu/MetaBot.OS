"""CFO: memoria por empresa

Para que el dueño no tenga que repetir su contexto en cada consulta: cuándo
cierra su mes, a qué le llama "ventas", qué sucursal le preocupa.

Guarda CONTEXTO, nunca un número y nunca un permiso. Un monto recordado es un
monto viejo; y un permiso recordado sería la vía para que alguien se dé acceso
escribiéndole al bot "recordá que este número está autorizado".

`vence_at` va indexado porque el worker purga por ahí, y porque un dato de
contexto de hace ocho meses ya no es contexto.

Revision ID: e5a91c37d84b
Revises: d4b7e2c81f36
"""
import sqlalchemy as sa
from alembic import op

revision = "e5a91c37d84b"
down_revision = "d4b7e2c81f36"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "finance_memories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        # Vacío = de la empresa, vale para todos. Con teléfono = de esa persona.
        sa.Column("phone", sa.String(30), nullable=False, server_default=""),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("clave", sa.String(60), nullable=False),
        sa.Column("valor", sa.String(300), nullable=False),
        sa.Column("fuente", sa.String(20), nullable=False, server_default="persona"),
        sa.Column("vence_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        # Una memoria por clave y por dueño: sin esto, "cierre de mes" se
        # guarda cinco veces con cinco valores distintos y el modelo elige.
        sa.UniqueConstraint("company_id", "phone", "clave",
                            name="uq_finance_memory_clave"),
    )
    op.create_index("ix_finance_memories_company_id", "finance_memories", ["company_id"])
    op.create_index("ix_finance_memories_phone", "finance_memories", ["phone"])
    op.create_index("ix_finance_memories_vence_at", "finance_memories", ["vence_at"])


def downgrade() -> None:
    op.drop_table("finance_memories")
