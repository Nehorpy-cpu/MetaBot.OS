"""teléfono de contacto de la empresa

Revision ID: c1a83d5f2094
Revises: b2e94a15c706
Create Date: 2026-08-11 05:30:00.000000

Sin este dato el modelo INVENTA uno. Observado en producción: le dio a un
paciente "021 214-400", que no existe en ninguna parte de la base.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c1a83d5f2094'
down_revision: Union[str, None] = 'b2e94a15c706'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('companies', schema=None) as batch_op:
        batch_op.add_column(sa.Column('phone', sa.String(length=50), nullable=False, server_default=''))


def downgrade() -> None:
    with op.batch_alter_table('companies', schema=None) as batch_op:
        batch_op.drop_column('phone')
