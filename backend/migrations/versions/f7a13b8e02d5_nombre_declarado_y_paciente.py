"""nombre declarado y paciente de la conversación

Revision ID: f7a13b8e02d5
Revises: e4c92f0a7b16
Create Date: 2026-08-11 14:40:00.000000

`contact_name` guarda el nombre del PERFIL de WhatsApp, que la gente pone como
"Mami", el nombre de su comercio o un emoji. No sirve para agendar.

Faltaban dos cosas distintas:
- `stated_name`: el nombre que la persona DIJO en la conversación. Sin esto se
  perdía al cortarse el historial en 20 mensajes, y el bot volvía a preguntar
  algo que ya le habían contestado.
- `patient_name`: a quién le corresponde el turno cuando no es quien escribe.
  Mucha gente agenda para el hijo, la madre o la pareja, y en salud confundir
  esos dos significa mandarle a alguien los datos clínicos de otra persona.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f7a13b8e02d5'
down_revision: Union[str, None] = 'e4c92f0a7b16'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('stated_name', sa.String(length=200), nullable=False, server_default='')
        )
        batch_op.add_column(
            sa.Column('patient_name', sa.String(length=200), nullable=False, server_default='')
        )


def downgrade() -> None:
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.drop_column('patient_name')
        batch_op.drop_column('stated_name')
