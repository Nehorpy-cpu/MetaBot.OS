"""CFO: credencial cifrada del conector

Un conector REST necesita un token y uno de PostgreSQL una contraseña. No hay
forma de sincronizar sin eso, así que la pregunta no era si guardarlos sino
cómo: cifrados con Fernet, con la llave en el entorno del servidor y NO en la
base. Cifrar con una llave guardada al lado de lo cifrado es guardar en claro
con pasos de más.

El valor descifrado no sale nunca por la API: el panel sabe si hay credencial,
jamás cuál es. Igual que el PIN.

Revision ID: f1c8a24e70d3
Revises: e5a91c37d84b
"""
import sqlalchemy as sa
from alembic import op

revision = "f1c8a24e70d3"
down_revision = "e5a91c37d84b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "finance_connectors",
        sa.Column("secreto_cifrado", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("finance_connectors", "secreto_cifrado")
