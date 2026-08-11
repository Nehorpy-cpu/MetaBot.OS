"""recordatorios de medicación: consentimiento, versión de receta y baja

Revision ID: f61e9d3a08c7
Revises: e58c2b91d7a4
Create Date: 2026-08-11 02:50:00.000000

Columnas nuevas sobre tablas pobladas: todas con server_default.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f61e9d3a08c7'
down_revision: Union[str, None] = 'e58c2b91d7a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('opted_out', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('opted_out_at', sa.DateTime(), nullable=True))

    with op.batch_alter_table('prescriptions', schema=None) as batch_op:
        # Apagados por defecto: el recordatorio de medicación se activa
        # cuando el paciente lo pide, no cuando la clínica lo asume.
        batch_op.add_column(sa.Column('reminders_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('consent_by', sa.String(length=120), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('consent_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('version', sa.Integer(), nullable=False, server_default='1'))


def downgrade() -> None:
    with op.batch_alter_table('prescriptions', schema=None) as batch_op:
        batch_op.drop_column('version')
        batch_op.drop_column('consent_at')
        batch_op.drop_column('consent_by')
        batch_op.drop_column('reminders_enabled')
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.drop_column('opted_out_at')
        batch_op.drop_column('opted_out')
