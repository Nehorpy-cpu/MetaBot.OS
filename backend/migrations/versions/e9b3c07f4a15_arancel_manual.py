"""El monto lo configura la clínica, el sistema lo toma

Dos formas de poner un monto a mano, para dos problemas distintos:

1. `service_coverages.arancel_gs` — lo que ESA aseguradora paga por ESA
   práctica. Es como funciona de verdad: cada convenio tiene su nomenclador
   con un monto fijo, que rara vez es un porcentaje redondo del precio de
   lista de la clínica. Se carga una vez y vale para todas las liquidaciones
   siguientes. 0 = no configurado, y ahí se sigue calculando por porcentaje,
   así que ninguna empresa existente cambia de números por esta migración.

2. `fee_batch_items.ajustado_a_mano` y compañía — corregir un renglón
   puntual antes de firmar. Se guarda lo que el sistema había calculado: un
   monto cambiado que no deja rastro es indistinguible de un error de
   cálculo, y acá alguien firma abajo del total.

`origen_arancel` pasa de 40 a 60 caracteres: "excluido del convenio: se abona
particular" no entraba, y una columna que trunca en silencio deja al
profesional leyendo media explicación.

Revision ID: e9b3c07f4a15
Revises: d5c7e14ab892
"""
import sqlalchemy as sa
from alembic import op

revision = "e9b3c07f4a15"
down_revision = "d5c7e14ab892"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "service_coverages",
        sa.Column("arancel_gs", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column(
        "fee_batch_items", "origen_arancel",
        existing_type=sa.String(40), type_=sa.String(60), existing_nullable=False,
    )
    op.add_column(
        "fee_batch_items",
        sa.Column("ajustado_a_mano", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
    )
    op.add_column(
        "fee_batch_items",
        sa.Column("facturado_calculado_gs", sa.Integer(), nullable=False,
                  server_default="0"),
    )
    op.add_column(
        "fee_batch_items",
        sa.Column("honorario_calculado_gs", sa.Integer(), nullable=False,
                  server_default="0"),
    )
    op.add_column(
        "fee_batch_items",
        sa.Column("ajuste_motivo", sa.String(200), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("fee_batch_items", "ajuste_motivo")
    op.drop_column("fee_batch_items", "honorario_calculado_gs")
    op.drop_column("fee_batch_items", "facturado_calculado_gs")
    op.drop_column("fee_batch_items", "ajustado_a_mano")
    op.alter_column(
        "fee_batch_items", "origen_arancel",
        existing_type=sa.String(60), type_=sa.String(40), existing_nullable=False,
    )
    op.drop_column("service_coverages", "arancel_gs")
