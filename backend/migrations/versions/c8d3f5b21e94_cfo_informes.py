"""CFO: informes privados con llave opaca

El dueño recibe el resumen por WhatsApp y un enlace. Ese enlace es lo único
que hay entre un tercero y los números de una empresa.

- `finance_reports` guarda un SNAPSHOT. El dueño reenvía el enlace a su
  contador tres días después y los dos tienen que ver el mismo número: si el
  informe se recalculara, la discusión pasaría a ser sobre el software.
- `finance_report_tokens` guarda el HASH del token, nunca el valor. Con
  acceso de lectura a un respaldo, alguien podría abrir los informes de
  todos los clientes.

El token no lleva adentro el id de la empresa, ni el teléfono, ni la fecha:
es opaco. Un enlace interceptado no tiene por qué contar de quién es.

Revision ID: c8d3f5b21e94
Revises: b6e2f8a04d17
"""
import sqlalchemy as sa
from alembic import op

revision = "c8d3f5b21e94"
down_revision = "b6e2f8a04d17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "finance_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("titulo", sa.String(200), nullable=False, server_default=""),
        sa.Column("pedido_por", sa.String(30), nullable=False, server_default=""),
        sa.Column("desde", sa.Date(), nullable=False),
        sa.Column("hasta", sa.Date(), nullable=False),
        sa.Column("snapshot", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("company_id", "id", name="uq_finance_report_company_id"),
    )
    op.create_index("ix_finance_reports_company_id", "finance_reports", ["company_id"])
    op.create_index("ix_finance_reports_created_at", "finance_reports", ["created_at"])

    op.create_table(
        "finance_report_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expira_at", sa.DateTime(), nullable=False),
        sa.Column("revocado_at", sa.DateTime(), nullable=True),
        sa.Column("un_solo_uso", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("aperturas", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("primera_apertura_at", sa.DateTime(), nullable=True),
        sa.Column("ultima_apertura_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        # Único: dos informes no pueden compartir llave.
        sa.UniqueConstraint("token_hash", name="uq_report_token_hash"),
        # Compuesta con company_id, como el resto del esquema: una llave no
        # puede apuntar al informe de otra empresa.
        sa.ForeignKeyConstraint(
            ["company_id", "report_id"],
            ["finance_reports.company_id", "finance_reports.id"],
            name="fk_report_token_tenant", ondelete="CASCADE",
        ),
    )
    op.create_index("ix_finance_report_tokens_company_id", "finance_report_tokens", ["company_id"])
    op.create_index("ix_finance_report_tokens_report_id", "finance_report_tokens", ["report_id"])
    op.create_index("ix_finance_report_tokens_token_hash", "finance_report_tokens", ["token_hash"])
    op.create_index("ix_finance_report_tokens_expira_at", "finance_report_tokens", ["expira_at"])


def downgrade() -> None:
    op.drop_table("finance_report_tokens")
    op.drop_table("finance_reports")
