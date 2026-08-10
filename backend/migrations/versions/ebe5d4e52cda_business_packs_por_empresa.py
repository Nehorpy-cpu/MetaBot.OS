"""business packs por empresa

Revision ID: ebe5d4e52cda
Revises: 6bcb858396f3
Create Date: 2026-08-10 14:53:47.041286
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ebe5d4e52cda'
down_revision: Union[str, None] = '6bcb858396f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default='' porque la tabla ya tiene filas: sin default, agregar
    # una columna NOT NULL rompe (lo detectó producción).
    with op.batch_alter_table('companies', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('packs', sa.String(length=200), nullable=False, server_default='')
        )

    # Backfill: derivar los packs de la vertical de cada empresa existente.
    companies = sa.table(
        'companies', sa.column('id', sa.Integer), sa.column('vertical', sa.String),
        sa.column('packs', sa.String),
    )
    for vertical, keys in (
        ('medical', 'booking,healthcare'),
        ('dental', 'booking,healthcare'),
        ('veterinary', 'booking,healthcare'),
        ('ecommerce', 'commerce'),
        ('retail', 'commerce'),
        ('construction', 'commerce'),
        ('beauty', 'booking,commerce'),
        ('gastronomy', 'commerce'),
        ('services', 'booking'),
        ('education', 'booking'),
        ('travel', 'travel'),
    ):
        op.execute(
            companies.update()
            .where(companies.c.vertical == op.inline_literal(vertical))
            .values(packs=op.inline_literal(keys))
        )


def downgrade() -> None:
    with op.batch_alter_table('companies', schema=None) as batch_op:
        batch_op.drop_column('packs')
