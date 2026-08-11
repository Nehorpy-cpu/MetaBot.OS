"""número de WhatsApp único por empresa

Revision ID: b3d81f60a742
Revises: a71f4c9e2b05
Create Date: 2026-08-10 23:58:00.000000

Cierra una fuga de datos entre empresas encontrada en auditoría adversarial.

El webhook de la Cloud API resuelve a qué empresa pertenece un mensaje
entrante SOLO por `wa_phone_number_id`, con un `.first()`. Sin restricción de
unicidad, dos empresas podían registrar el mismo número y una se quedaba con
los mensajes de los pacientes de la otra —y todas las filas quedaban
perfectamente consistentes, así que ningún chequeo de integridad lo veía.

Orden (la lección ya pagada dos veces en producción): primero volver la
columna nulable, después el backfill de '' a NULL, y RECIÉN AHÍ el índice
único. Sin el backfill, las empresas sin configurar chocarían entre sí por
compartir la cadena vacía.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3d81f60a742'
down_revision: Union[str, None] = 'a71f4c9e2b05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) La columna admite NULL: "sin configurar" deja de ser cadena vacía.
    with op.batch_alter_table('companies', schema=None) as batch_op:
        batch_op.alter_column(
            'wa_phone_number_id',
            existing_type=sa.String(length=50),
            nullable=True,
        )

    # 2) Backfill: varias empresas sin número no deben chocar entre sí.
    op.execute("UPDATE companies SET wa_phone_number_id = NULL WHERE wa_phone_number_id = ''")

    # 3) Si ya hay dos empresas con el MISMO número, no se puede crear el
    #    índice. Se corta acá con un mensaje accionable en vez de dejar que
    #    reviente con un error de índice ilegible. Fallar cerrado es correcto:
    #    arrancar en ese estado significa enrutar mensajes al tenant equivocado.
    duplicados = op.get_bind().execute(sa.text(
        "SELECT wa_phone_number_id, count(*) AS n FROM companies "
        "WHERE wa_phone_number_id IS NOT NULL GROUP BY 1 HAVING count(*) > 1"
    )).fetchall()
    if duplicados:
        detalle = ", ".join(f"{d[0]} ({d[1]} empresas)" for d in duplicados)
        raise RuntimeError(
            "No se puede aplicar la migración: hay números de WhatsApp repetidos "
            f"entre empresas -> {detalle}. Cada número pertenece a UNA sola empresa; "
            "dejarlo así hace que una reciba los mensajes de los pacientes de la otra. "
            "Corregí wa_phone_number_id en la tabla companies y volvé a desplegar."
        )

    # 4) Recién ahora, el índice único.
    with op.batch_alter_table('companies', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_companies_wa_phone_number_id'))
        batch_op.create_index(
            batch_op.f('ix_companies_wa_phone_number_id'),
            ['wa_phone_number_id'],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table('companies', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_companies_wa_phone_number_id'))
        batch_op.create_index(
            batch_op.f('ix_companies_wa_phone_number_id'),
            ['wa_phone_number_id'],
            unique=False,
        )
    op.execute("UPDATE companies SET wa_phone_number_id = '' WHERE wa_phone_number_id IS NULL")
    with op.batch_alter_table('companies', schema=None) as batch_op:
        batch_op.alter_column(
            'wa_phone_number_id',
            existing_type=sa.String(length=50),
            nullable=False,
        )
