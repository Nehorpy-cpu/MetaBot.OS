"""salud: campos de catálogo, convenios con seguros y recetas

Revision ID: c92a4e17b508
Revises: b3d81f60a742
Create Date: 2026-08-11 00:40:00.000000

Columnas nuevas sobre `services` (tabla poblada: 7 filas en producción), así
que van con server_default. Las tablas nuevas no necesitan backfill.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c92a4e17b508'
down_revision: Union[str, None] = 'b3d81f60a742'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Columnas nuevas sobre tabla poblada: siempre con server_default.
    with op.batch_alter_table('services', schema=None) as batch_op:
        batch_op.add_column(sa.Column('specialty', sa.String(length=100), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('prep', sa.Text(), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('sample', sa.String(length=80), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('code', sa.String(length=50), nullable=False, server_default=''))

    # 2) Convenios con aseguradoras (del tenant, no una base compartida).
    op.create_table(
        'insurers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('plan', sa.String(length=80), nullable=False, server_default=''),
        sa.Column('coverage_pct', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('copay_gs', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('notes', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'name', 'plan', name='uq_insurer_company_name_plan'),
    )
    with op.batch_alter_table('insurers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_insurers_company_id'), ['company_id'], unique=False)

    op.create_table(
        'service_coverages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('insurer_id', sa.Integer(), nullable=False),
        sa.Column('service_id', sa.Integer(), nullable=False),
        sa.Column('coverage_pct', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('copay_gs', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('excluded', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
        sa.ForeignKeyConstraint(['insurer_id'], ['insurers.id'], ),
        sa.ForeignKeyConstraint(['service_id'], ['services.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('insurer_id', 'service_id', name='uq_coverage_insurer_service'),
    )
    with op.batch_alter_table('service_coverages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_service_coverages_company_id'), ['company_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_service_coverages_insurer_id'), ['insurer_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_service_coverages_service_id'), ['service_id'], unique=False)

    # 3) Recetas cargadas por el doctor.
    op.create_table(
        'prescriptions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('doctor_id', sa.Integer(), nullable=False),
        sa.Column('patient_name', sa.String(length=120), nullable=False),
        sa.Column('patient_phone', sa.String(length=30), nullable=False),
        sa.Column('diagnosis', sa.Text(), nullable=False, server_default=''),
        sa.Column('indications', sa.Text(), nullable=False, server_default=''),
        sa.Column('issued_at', sa.DateTime(), nullable=False),
        sa.Column('status', sa.String(length=15), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
        sa.ForeignKeyConstraint(['doctor_id'], ['doctors.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('prescriptions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_prescriptions_company_id'), ['company_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_prescriptions_doctor_id'), ['doctor_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_prescriptions_patient_phone'), ['patient_phone'], unique=False)
        batch_op.create_index(batch_op.f('ix_prescriptions_issued_at'), ['issued_at'], unique=False)

    op.create_table(
        'prescription_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('prescription_id', sa.Integer(), nullable=False),
        sa.Column('medication', sa.String(length=200), nullable=False),
        sa.Column('dose', sa.String(length=120), nullable=False),
        sa.Column('route', sa.String(length=60), nullable=False, server_default='vía oral'),
        sa.Column('frequency', sa.String(length=120), nullable=False, server_default=''),
        sa.Column('every_hours', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('duration_days', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('instructions', sa.Text(), nullable=False, server_default=''),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
        sa.ForeignKeyConstraint(['prescription_id'], ['prescriptions.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('prescription_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_prescription_items_company_id'), ['company_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_prescription_items_prescription_id'), ['prescription_id'], unique=False)


def downgrade() -> None:
    op.drop_table('prescription_items')
    op.drop_table('prescriptions')
    op.drop_table('service_coverages')
    op.drop_table('insurers')
    with op.batch_alter_table('services', schema=None) as batch_op:
        batch_op.drop_column('code')
        batch_op.drop_column('sample')
        batch_op.drop_column('prep')
        batch_op.drop_column('specialty')
