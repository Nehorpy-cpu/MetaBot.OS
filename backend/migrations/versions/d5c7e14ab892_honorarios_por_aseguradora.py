"""Honorarios: la atención registra su convenio y se liquida por planilla

Tres cosas:

1. `appointments.insurer_id` — por qué convenio vino el paciente. NULL no es
   un dato faltante: es "particular", que es la mitad de la agenda y va en su
   propia planilla.
2. `doctors.honorario_pct` — qué porcentaje de lo facturado le corresponde al
   profesional. Arranca en 100 para todos: es lo único que no le cambia la
   plata a nadie hasta que la clínica cargue su arreglo real.
3. `fee_batches` / `fee_batch_items` — la planilla como documento.

Las claves foráneas son COMPUESTAS con company_id, como el resto del esquema:
una planilla no puede citar la atención de otra empresa ni entregarse a una
aseguradora que no es de este tenant.

La restricción única de `fee_batch_items(company_id, appointment_id)` es la
más importante del cambio: una atención se cobra UNA vez. Sin ella, rearmar
una planilla o superponer dos períodos factura dos veces la misma consulta, y
eso no se arregla con un deploy: se arregla con una nota de crédito.

Revision ID: d5c7e14ab892
Revises: c4f1a9e83b20
"""
import sqlalchemy as sa
from alembic import op

revision = "d5c7e14ab892"
down_revision = "c4f1a9e83b20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- 1. La atención registra su convenio -----------------------------
    # El UNIQUE va primero: sin él PostgreSQL no acepta que otra tabla
    # referencie (company_id, id) de appointments.
    op.create_unique_constraint(
        "uq_appointment_company_id", "appointments", ["company_id", "id"]
    )
    op.add_column("appointments", sa.Column("insurer_id", sa.Integer(), nullable=True))
    op.create_index("ix_appointments_insurer_id", "appointments", ["insurer_id"])
    op.create_foreign_key(
        "fk_appointments_insurer_tenant",
        "appointments", "insurers",
        ["company_id", "insurer_id"], ["company_id", "id"],
    )

    # --- 2. El arreglo del profesional -----------------------------------
    op.add_column(
        "doctors",
        sa.Column("honorario_pct", sa.Integer(), nullable=False, server_default="100"),
    )

    # --- 3. Las planillas -------------------------------------------------
    op.create_table(
        "fee_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("doctor_id", sa.Integer(), nullable=False),
        sa.Column("insurer_id", sa.Integer(), nullable=True),
        sa.Column("insurer_nombre", sa.String(200), nullable=False, server_default="Particulares"),
        sa.Column("desde", sa.Date(), nullable=False),
        sa.Column("hasta", sa.Date(), nullable=False),
        sa.Column("estado", sa.String(12), nullable=False, server_default="borrador"),
        sa.Column("total_facturado_gs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_honorario_gs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("honorario_pct", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("firmada_at", sa.DateTime(), nullable=True),
        sa.Column("firmada_por", sa.Integer(), nullable=True),
        sa.Column("entregada_at", sa.DateTime(), nullable=True),
        sa.Column("cobrada_at", sa.DateTime(), nullable=True),
        sa.Column("notas", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("company_id", "id", name="uq_fee_batch_company_id"),
        sa.ForeignKeyConstraint(
            ["company_id", "doctor_id"], ["doctors.company_id", "doctors.id"],
            name="fk_fee_batch_doctor_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "insurer_id"], ["insurers.company_id", "insurers.id"],
            name="fk_fee_batch_insurer_tenant",
        ),
        sa.CheckConstraint("desde <= hasta", name="ck_fee_batch_periodo"),
    )
    op.create_index("ix_fee_batches_company_id", "fee_batches", ["company_id"])
    op.create_index("ix_fee_batches_doctor_id", "fee_batches", ["doctor_id"])
    op.create_index("ix_fee_batches_insurer_id", "fee_batches", ["insurer_id"])
    op.create_index("ix_fee_batches_estado", "fee_batches", ["estado"])

    op.create_table(
        "fee_batch_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("appointment_id", sa.Integer(), nullable=False),
        sa.Column("atendido_at", sa.DateTime(), nullable=False),
        sa.Column("paciente", sa.String(200), nullable=False),
        sa.Column("servicio", sa.String(200), nullable=False, server_default=""),
        sa.Column("precio_lista_gs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("facturado_gs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("honorario_gs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("origen_arancel", sa.String(40), nullable=False, server_default=""),
        # LA restricción del cambio: una atención se cobra una sola vez.
        sa.UniqueConstraint("company_id", "appointment_id", name="uq_fee_item_atencion"),
        sa.ForeignKeyConstraint(
            ["company_id", "batch_id"], ["fee_batches.company_id", "fee_batches.id"],
            name="fk_fee_item_batch_tenant", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "appointment_id"],
            ["appointments.company_id", "appointments.id"],
            name="fk_fee_item_appointment_tenant",
        ),
    )
    op.create_index("ix_fee_batch_items_company_id", "fee_batch_items", ["company_id"])
    op.create_index("ix_fee_batch_items_batch_id", "fee_batch_items", ["batch_id"])
    op.create_index("ix_fee_batch_items_appointment_id", "fee_batch_items", ["appointment_id"])


def downgrade() -> None:
    op.drop_table("fee_batch_items")
    op.drop_table("fee_batches")
    op.drop_column("doctors", "honorario_pct")
    op.drop_constraint("fk_appointments_insurer_tenant", "appointments", type_="foreignkey")
    op.drop_index("ix_appointments_insurer_id", table_name="appointments")
    op.drop_column("appointments", "insurer_id")
    op.drop_constraint("uq_appointment_company_id", "appointments", type_="unique")
