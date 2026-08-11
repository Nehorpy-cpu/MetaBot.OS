"""liberar el modelo del agente CX para que lo elija el router

Revision ID: e4c92f0a7b16
Revises: d3b70c4e18f2
Create Date: 2026-08-11 14:10:00.000000

Los 8 agentes CX quedaron con `model` fijado por la plantilla en
`nvidia/llama-3.3-nemotron-super-49b-v1.5`. Ese valor gana sobre el Model
Router, así que la tabla TASK_MODELS no tenía efecto para el bot que habla
con los pacientes.

Medido en el VPS el 11-ago-2026, turno completo con el prompt real y las 7
herramientas: ese modelo tarda 17,3s a 71,4s porque razona antes de contestar;
groq/openai/gpt-oss-120b hace lo mismo en 0,8s a 2,2s.

Se vacía SOLO donde el valor es el que puso la plantilla: si una empresa
eligió otro modelo a mano, esa elección se respeta.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e4c92f0a7b16'
down_revision: Union[str, None] = 'd3b70c4e18f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PUESTO_POR_LA_PLANTILLA = 'nvidia/llama-3.3-nemotron-super-49b-v1.5'


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE agents SET model = '' "
            "WHERE slug = 'cx' AND model = :puesto"
        ).bindparams(puesto=PUESTO_POR_LA_PLANTILLA)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE agents SET model = :puesto WHERE slug = 'cx' AND model = ''"
        ).bindparams(puesto=PUESTO_POR_LA_PLANTILLA)
    )
