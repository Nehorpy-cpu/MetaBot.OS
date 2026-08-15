"""Tokens por ejecución: la base para poner precio y tope

Sin esto, "cuánto sale atender a un cliente" es una opinión. `agent_runs` ya
medía latencia y herramientas, pero tiraba el `usage` que devuelve el
proveedor — y sobre algo que no se mide no se puede poner ni un precio ni un
tope.

Cero significa que el proveedor no informó los tokens, no que la llamada fue
gratis. Se distingue mirando el modelo: los de Groq informan; si aparece un
cero con un modelo de OpenAI, hay un problema.

Revision ID: a2f9d61c845e
Revises: f1c8a24e70d3
"""
import sqlalchemy as sa
from alembic import op

revision = "a2f9d61c845e"
down_revision = "f1c8a24e70d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column(
        "tokens_entrada", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("agent_runs", sa.Column(
        "tokens_salida", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("agent_runs", "tokens_salida")
    op.drop_column("agent_runs", "tokens_entrada")
