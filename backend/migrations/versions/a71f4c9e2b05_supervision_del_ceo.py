"""supervisión del CEO sobre los turnos del CX

Revision ID: a71f4c9e2b05
Revises: 450266faba63
Create Date: 2026-08-10 23:10:00.000000

Toda empresa existente queda en `supervision='off'`: el comportamiento no
cambia hasta que alguien lo active a propósito. Por eso las columnas nuevas
llevan `server_default` — la tabla `companies` ya tiene datos en producción.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a71f4c9e2b05'
down_revision: Union[str, None] = '450266faba63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Columnas nuevas sobre tablas pobladas: siempre con server_default.
    with op.batch_alter_table('companies', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('supervision', sa.String(length=10), nullable=False, server_default='off')
        )
        batch_op.add_column(
            sa.Column('supervision_pct', sa.Integer(), nullable=False, server_default='100')
        )
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('pending_directive', sa.String(length=500), nullable=False, server_default='')
        )

    # 2) Tabla nueva: no necesita backfill, así que índices y FKs van juntos.
    op.create_table(
        'supervisions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('conversation_id', sa.Integer(), nullable=False),
        sa.Column('trigger_key', sa.String(length=40), nullable=False),
        sa.Column('agent_slug', sa.String(length=30), nullable=False),
        sa.Column('mode', sa.String(length=10), nullable=False),
        sa.Column('arm', sa.String(length=12), nullable=False, server_default='supervised'),
        sa.Column('action', sa.String(length=15), nullable=False, server_default='keep'),
        sa.Column('reason', sa.String(length=500), nullable=False, server_default=''),
        sa.Column('downgraded', sa.String(length=120), nullable=False, server_default=''),
        sa.Column('latency_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('supervisions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_supervisions_company_id'), ['company_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_supervisions_conversation_id'), ['conversation_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_supervisions_trigger_key'), ['trigger_key'], unique=False)
        batch_op.create_index(batch_op.f('ix_supervisions_created_at'), ['created_at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('supervisions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_supervisions_created_at'))
        batch_op.drop_index(batch_op.f('ix_supervisions_trigger_key'))
        batch_op.drop_index(batch_op.f('ix_supervisions_conversation_id'))
        batch_op.drop_index(batch_op.f('ix_supervisions_company_id'))
    op.drop_table('supervisions')
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.drop_column('pending_directive')
    with op.batch_alter_table('companies', schema=None) as batch_op:
        batch_op.drop_column('supervision_pct')
        batch_op.drop_column('supervision')
