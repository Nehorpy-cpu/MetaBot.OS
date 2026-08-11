"""padrón de especialistas certificados y verificación de profesionales

Revision ID: d4f7a1c93e60
Revises: c92a4e17b508
Create Date: 2026-08-11 01:30:00.000000

`medical_registry` NO lleva company_id a propósito: es una tabla de
referencia de la plataforma (un padrón público), no datos de ningún tenant.
Las columnas nuevas de `doctors` van con server_default porque la tabla ya
tiene datos.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4f7a1c93e60'
down_revision: Union[str, None] = 'c92a4e17b508'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'medical_registry',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('full_name', sa.String(length=200), nullable=False),
        sa.Column('match_key', sa.String(length=200), nullable=False),
        sa.Column('specialty', sa.String(length=120), nullable=False),
        sa.Column('cert_number', sa.String(length=30), nullable=False, server_default=''),
        sa.Column('accredited_at', sa.Date(), nullable=True),
        sa.Column('expires_at', sa.Date(), nullable=True),
        sa.Column('source', sa.String(length=40), nullable=False, server_default='CPM'),
        sa.Column('imported_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('medical_registry', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_medical_registry_full_name'), ['full_name'], unique=False)
        batch_op.create_index(batch_op.f('ix_medical_registry_match_key'), ['match_key'], unique=False)
        batch_op.create_index(batch_op.f('ix_medical_registry_specialty'), ['specialty'], unique=False)
        batch_op.create_index(batch_op.f('ix_medical_registry_expires_at'), ['expires_at'], unique=False)

    with op.batch_alter_table('doctors', schema=None) as batch_op:
        batch_op.add_column(sa.Column('verification', sa.String(length=15), nullable=False, server_default='unverified'))
        batch_op.add_column(sa.Column('cert_number', sa.String(length=30), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('cert_specialty', sa.String(length=120), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('cert_expires_at', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('verified_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('doctors', schema=None) as batch_op:
        batch_op.drop_column('verified_at')
        batch_op.drop_column('cert_expires_at')
        batch_op.drop_column('cert_specialty')
        batch_op.drop_column('cert_number')
        batch_op.drop_column('verification')
    op.drop_table('medical_registry')
