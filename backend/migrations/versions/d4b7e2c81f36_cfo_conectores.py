"""CFO: conectores de datos y hechos económicos normalizados

Hasta acá el motor creía que todas las empresas tenían las mismas fuentes,
porque era una constante del módulo. Ahora depende de lo que CADA empresa
conectó, y de si ese conector trajo filas alguna vez: conectado no es
disponible.

`finance_records` es donde aterrizan los datos ya normalizados. Se guarda en
vez de consultar el sistema del cliente en el momento de la pregunta, por dos
razones: la respuesta no puede depender de que su ERP esté vivo y rápido, y
sin guardar no hay forma de decir de cuándo son los datos —que es la mitad de
lo que hace útil a un número financiero.

El monto va en BIGINT de guaraníes enteros. Un decimal flotante en plata
termina en un total que no cierra por un guaraní, y el dueño deja de creerle
al sistema por algo que no era el sistema.

Revision ID: d4b7e2c81f36
Revises: c8d3f5b21e94
"""
import sqlalchemy as sa
from alembic import op

revision = "d4b7e2c81f36"
down_revision = "c8d3f5b21e94"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "finance_connectors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("fuente", sa.String(30), nullable=False),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("nombre", sa.String(120), nullable=False),
        sa.Column("config", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("ultima_sync_at", sa.DateTime(), nullable=True),
        sa.Column("ultima_sync_ok", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ultimo_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("filas_ultima_sync", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("filas_totales", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        # Necesaria para que los registros puedan apuntar con clave compuesta.
        sa.UniqueConstraint("company_id", "id", name="uq_finance_connector_company_id"),
        # Dos conectores con el mismo nombre en una empresa vuelven imposible
        # saber cuál quedó atrasado.
        sa.UniqueConstraint("company_id", "nombre", name="uq_finance_connector_nombre"),
    )
    op.create_index("ix_finance_connectors_company_id", "finance_connectors", ["company_id"])
    op.create_index("ix_finance_connectors_fuente", "finance_connectors", ["fuente"])
    op.create_index("ix_finance_connectors_ultima_sync_at", "finance_connectors", ["ultima_sync_at"])

    op.create_table(
        "finance_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("connector_id", sa.Integer(), nullable=False),
        sa.Column("fuente", sa.String(30), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("monto_gs", sa.BigInteger(), nullable=False),
        sa.Column("categoria", sa.String(120), nullable=False, server_default=""),
        sa.Column("referencia", sa.String(120), nullable=False),
        sa.Column("detalle", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("cargado_at", sa.DateTime(), nullable=False),
        # Compuesta, como el resto del esquema: un registro no puede colgar
        # del conector de otra empresa, y no lo impide un `if` sino Postgres.
        sa.ForeignKeyConstraint(
            ["company_id", "connector_id"],
            ["finance_connectors.company_id", "finance_connectors.id"],
            name="fk_finance_record_tenant", ondelete="CASCADE",
        ),
        # Volver a subir la misma planilla no duplica. Sin esto, un dueño que
        # sube dos veces el mismo archivo ve sus ventas al doble.
        sa.UniqueConstraint(
            "company_id", "connector_id", "referencia",
            name="uq_finance_record_referencia",
        ),
    )
    op.create_index("ix_finance_records_company_id", "finance_records", ["company_id"])
    op.create_index("ix_finance_records_connector_id", "finance_records", ["connector_id"])
    op.create_index("ix_finance_records_fuente", "finance_records", ["fuente"])
    op.create_index("ix_finance_records_fecha", "finance_records", ["fecha"])
    # El índice que importa: toda métrica consulta por empresa + fuente + rango.
    op.create_index(
        "ix_finance_records_consulta", "finance_records",
        ["company_id", "fuente", "fecha"],
    )


def downgrade() -> None:
    op.drop_table("finance_records")
    op.drop_table("finance_connectors")
