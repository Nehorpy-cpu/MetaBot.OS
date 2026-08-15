"""Plan por empresa y clave de OpenAI propia

Dos ejes que no hay que confundir: `packs` dice QUÉ compró el cliente y `plan`
dice CUÁNTO puede usar. Meter el volumen adentro del bloque obligaría a vender
"agenda chica" y "agenda grande", que son el mismo software.

`openai_key_cifrada` vacía significa que el consumo lo paga la plataforma. Para
las pruebas y los planes chicos está bien; para un cliente de volumen alto no,
y por eso el plan Empresa exige clave propia.

`openai_key_solicitada_at` es la solicitud del cliente. El alta la hace el
admin de la plataforma: una credencial de un tercero no se carga sola.

Nace en "prueba" y NO en el plan más grande: si algo sale mal con el dato, que
salga mal para el lado de consumir de menos.

Revision ID: b7e4a92f3c18
Revises: a2f9d61c845e
"""
import sqlalchemy as sa
from alembic import op

revision = "b7e4a92f3c18"
down_revision = "a2f9d61c845e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companies", sa.Column(
        "plan", sa.String(30), nullable=False, server_default="prueba"))
    op.add_column("companies", sa.Column(
        "openai_key_cifrada", sa.Text(), nullable=False, server_default=""))
    op.add_column("companies", sa.Column(
        "openai_key_solicitada_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("companies", "openai_key_solicitada_at")
    op.drop_column("companies", "openai_key_cifrada")
    op.drop_column("companies", "plan")
