"""clave normalizada de especialidad en el padrón

Revision ID: d3b70c4e18f2
Revises: c1a83d5f2094
Create Date: 2026-08-11 10:20:00.000000

La misma especialidad viene escrita de varias formas en el padrón del CPM.
Medido sobre las 4.772 filas: "Cirugía General" 327 filas y "Cirugia General"
19; "Pediatría General" 335, "Pediatria General" 23 y "Pediátria General" 1.

Buscar por el texto tal cual dejaba fuera a esos profesionales sin avisar: una
clínica que elegía "Cirugía General" en el desplegable no veía a 19 cirujanos
certificados. Se guarda la forma normalizada y se busca por ella.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd3b70c4e18f2'
down_revision: Union[str, None] = 'c1a83d5f2094'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('medical_registry', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('specialty_key', sa.String(length=120), nullable=False, server_default='')
        )
        batch_op.create_index('ix_medical_registry_specialty_key', ['specialty_key'])

    # Rellenar lo ya importado. Se hace en Python y no en SQL porque quitar
    # tildes y ordenar tokens es la misma función que usa la búsqueda: si acá
    # se calculara distinto, las claves no coincidirían.
    from app.registry import clave_de_especialidad

    conexion = op.get_bind()
    filas = conexion.execute(
        sa.text("SELECT id, specialty FROM medical_registry")
    ).fetchall()
    for fila_id, especialidad in filas:
        conexion.execute(
            sa.text("UPDATE medical_registry SET specialty_key = :k WHERE id = :i"),
            {"k": clave_de_especialidad(especialidad or "")[:120], "i": fila_id},
        )


def downgrade() -> None:
    with op.batch_alter_table('medical_registry', schema=None) as batch_op:
        batch_op.drop_index('ix_medical_registry_specialty_key')
        batch_op.drop_column('specialty_key')
