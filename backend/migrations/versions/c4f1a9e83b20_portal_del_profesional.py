"""Portal del profesional: la membresía puede apuntar a un doctor

Un usuario con rol `professional` es el médico. `doctor_id` es lo que hace
que vea SUS pacientes y no los del colega: sale del servidor, nunca del
request.

La clave foránea es COMPUESTA con company_id. Con un id suelto, un usuario de
la clínica A podría quedar apuntado al doctor de la clínica B y el portal le
mostraría los pacientes de otro tenant — el mismo error que ya se cerró en el
resto del esquema.

Revision ID: c4f1a9e83b20
Revises: b8d2e5f70a91
"""
import sqlalchemy as sa
from alembic import op

revision = "c4f1a9e83b20"
down_revision = "b8d2e5f70a91"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `role` pasa de 10 a 14 caracteres: "professional" son 12 y no entraba.
    # Sin esto el alta de un acceso falla con un error de la base, no del
    # código, y recién en producción.
    op.alter_column(
        "memberships", "role",
        existing_type=sa.String(10), type_=sa.String(14), existing_nullable=False,
    )
    op.add_column("memberships", sa.Column("doctor_id", sa.Integer(), nullable=True))
    op.create_index("ix_memberships_doctor_id", "memberships", ["doctor_id"])
    op.create_foreign_key(
        "fk_memberships_doctor_tenant",
        "memberships", "doctors",
        ["company_id", "doctor_id"], ["company_id", "id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_memberships_doctor_tenant", "memberships", type_="foreignkey")
    op.drop_index("ix_memberships_doctor_id", table_name="memberships")
    op.drop_column("memberships", "doctor_id")
    op.alter_column(
        "memberships", "role",
        existing_type=sa.String(14), type_=sa.String(10), existing_nullable=False,
    )
