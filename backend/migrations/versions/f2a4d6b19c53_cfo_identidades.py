"""CFO de Finanzas: quién puede preguntarle plata al bot

`finance_identities` es la tabla que decide si un número de WhatsApp puede
consultar datos financieros de una empresa, y hasta qué nivel. El número no
es la identidad: es la primera llave. Para lo sensible hace falta el PIN, que
se guarda hasheado con scrypt como cualquier contraseña.

Es POR EMPRESA (`company_id` + UNIQUE con el teléfono): el mismo número puede
ser dueño de tres negocios y ver distinto en cada uno.

No toca ninguna tabla existente: es aditiva pura. Una empresa que no contrate
el bloque `finance` no cambia en nada.

Revision ID: f2a4d6b19c53
Revises: e9b3c07f4a15
"""
import sqlalchemy as sa
from alembic import op

revision = "f2a4d6b19c53"
down_revision = "e9b3c07f4a15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "finance_identities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("phone", sa.String(30), nullable=False),
        sa.Column("nombre", sa.String(200), nullable=False, server_default=""),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("sensibilidad_max", sa.String(6), nullable=False, server_default="baja"),
        sa.Column("pin_hash", sa.String(255), nullable=False, server_default=""),
        sa.Column("pin_intentos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pin_bloqueado_hasta", sa.DateTime(), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("ultimo_uso_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        # Un número, una identidad por empresa. Sin esto quedan dos filas con
        # permisos distintos y nadie sabe cuál manda.
        sa.UniqueConstraint("company_id", "phone", name="uq_finance_identity_phone"),
        # Habilita que otras tablas del CFO citen (company_id, id) con clave
        # compuesta, como el resto del esquema.
        sa.UniqueConstraint("company_id", "id", name="uq_finance_identity_company_id"),
    )
    op.create_index("ix_finance_identities_company_id", "finance_identities", ["company_id"])
    op.create_index("ix_finance_identities_phone", "finance_identities", ["phone"])
    op.create_index("ix_finance_identities_user_id", "finance_identities", ["user_id"])


def downgrade() -> None:
    op.drop_table("finance_identities")
