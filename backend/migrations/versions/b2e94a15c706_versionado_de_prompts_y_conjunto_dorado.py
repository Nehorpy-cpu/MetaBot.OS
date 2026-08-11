"""versionado de prompts y conjunto dorado

Revision ID: b2e94a15c706
Revises: a07c5f2be913
Create Date: 2026-08-11 04:30:00.000000

Etapa 5. Los índices únicos PARCIALES sobre `role` garantizan en el motor que
hay a lo sumo una versión activa y una candidata por agente: con dos activas,
cuál gana dependería del orden de las filas.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2e94a15c706'
down_revision: Union[str, None] = 'a07c5f2be913'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'agent_prompt_versions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('agent_id', sa.Integer(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('body_sha', sa.String(length=64), nullable=False),
        sa.Column('role', sa.String(length=10), nullable=False, server_default='archived'),
        sa.Column('source', sa.String(length=12), nullable=False, server_default='human'),
        sa.Column('suggestion_id', sa.Integer(), nullable=True),
        sa.Column('eval_run_id', sa.Integer(), nullable=True),
        sa.Column('note', sa.String(length=300), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('activated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
        sa.ForeignKeyConstraint(
            ['company_id', 'agent_id'], ['agents.company_id', 'agents.id'],
            name='fk_prompt_versions_agent_tenant',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'agent_id', 'version', name='uq_prompt_version_num'),
    )
    with op.batch_alter_table('agent_prompt_versions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_agent_prompt_versions_company_id'), ['company_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_agent_prompt_versions_agent_id'), ['agent_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_agent_prompt_versions_body_sha'), ['body_sha'], unique=False)
        batch_op.create_index(batch_op.f('ix_agent_prompt_versions_created_at'), ['created_at'], unique=False)
    # Únicos PARCIALES: a lo sumo una activa y una candidata por agente.
    op.create_index(
        'uq_prompt_version_active', 'agent_prompt_versions', ['company_id', 'agent_id'],
        unique=True, postgresql_where=sa.text("role = 'active'"),
        sqlite_where=sa.text("role = 'active'"),
    )
    op.create_index(
        'uq_prompt_version_candidate', 'agent_prompt_versions', ['company_id', 'agent_id'],
        unique=True, postgresql_where=sa.text("role = 'candidate'"),
        sqlite_where=sa.text("role = 'candidate'"),
    )

    op.create_table(
        'golden_cases',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('slug', sa.String(length=80), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('pack', sa.String(length=20), nullable=False, server_default=''),
        sa.Column('agent_slug', sa.String(length=30), nullable=False, server_default='cx'),
        sa.Column('user_message', sa.Text(), nullable=False),
        sa.Column('setup', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('checks', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('critical', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('rationale', sa.Text(), nullable=False, server_default=''),
        sa.Column('source', sa.String(length=20), nullable=False, server_default='regresion'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'slug', name='uq_golden_case_slug'),
    )
    with op.batch_alter_table('golden_cases', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_golden_cases_company_id'), ['company_id'], unique=False)

    op.create_table(
        'eval_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('agent_id', sa.Integer(), nullable=False),
        sa.Column('prompt_version_id', sa.Integer(), nullable=True),
        sa.Column('total', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('passed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('critical_failed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('verdict', sa.String(length=12), nullable=False, server_default='pending'),
        sa.Column('reason', sa.String(length=300), nullable=False, server_default=''),
        sa.Column('latency_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('eval_runs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_eval_runs_company_id'), ['company_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_eval_runs_agent_id'), ['agent_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_eval_runs_prompt_version_id'), ['prompt_version_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_eval_runs_created_at'), ['created_at'], unique=False)

    op.create_table(
        'eval_results',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('eval_run_id', sa.Integer(), nullable=False),
        sa.Column('case_slug', sa.String(length=80), nullable=False),
        sa.Column('passed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('critical', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('failures', sa.Text(), nullable=False, server_default=''),
        sa.Column('tools_used', sa.String(length=300), nullable=False, server_default=''),
        sa.Column('reply', sa.Text(), nullable=False, server_default=''),
        sa.Column('latency_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('eval_results', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_eval_results_company_id'), ['company_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_eval_results_eval_run_id'), ['eval_run_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_eval_results_case_slug'), ['case_slug'], unique=False)


def downgrade() -> None:
    op.drop_table('eval_results')
    op.drop_table('eval_runs')
    op.drop_table('golden_cases')
    op.drop_index('uq_prompt_version_candidate', table_name='agent_prompt_versions')
    op.drop_index('uq_prompt_version_active', table_name='agent_prompt_versions')
    op.drop_table('agent_prompt_versions')
