"""asignar bloques a cada empresa según lo que REALMENTE usa

Revision ID: b8d2e5f70a91
Revises: a92d47c1f0b3
Create Date: 2026-08-14 18:00:00.000000

El sistema pasa a venderse por bloques. Antes de que el corte exista, cada
empresa tiene que quedar con sus bloques escritos de forma explícita.

Se miran los DATOS, no el rubro declarado. El rubro es lo que alguien tipeó al
darla de alta; las filas son lo que la empresa usa de verdad. Arfagi figura
como "ecommerce" y tiene catálogo: asignarle el bloque clínico por descuido le
dejaría el bot con herramientas que no necesita, y al revés —quitarle el
catálogo a quien lo usa— le rompe el negocio.

Nadie pierde nada: a quien ya usa una función se le asigna el bloque que la
contiene. El precio por bloques arranca en las ventas nuevas.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b8d2e5f70a91'
down_revision: Union[str, None] = 'a92d47c1f0b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _hay(conexion, tabla: str, company_id: int) -> bool:
    """¿Esta empresa tiene filas en esa tabla?"""
    try:
        return bool(conexion.execute(
            sa.text(f"SELECT 1 FROM {tabla} WHERE company_id = :c LIMIT 1"),
            {"c": company_id},
        ).first())
    except Exception:
        # Una tabla que todavía no existe en esta base no es un error: la
        # migración tiene que poder correr sobre instalaciones parciales.
        return False


def upgrade() -> None:
    conexion = op.get_bind()
    empresas = conexion.execute(
        sa.text("SELECT id, name, packs FROM companies")
    ).fetchall()

    for company_id, nombre, packs_actual in empresas:
        # Se PARTE de lo que la empresa ya tiene y solo se AGREGA. Un ensayo
        # contra la copia de producción mostró por qué: Centro Médico Asunción
        # tiene el bloque clínico asignado pero todavía no cargó ninguna
        # receta, así que una regla guiada solo por datos se lo quitaba. Nadie
        # puede perder por esta migración algo que hoy tiene.
        actuales = {k for k in (packs_actual or "").split(",") if k}
        bloques = ["core"]

        # Los packs viejos que ya no existen: `commerce` y `travel` quedaron
        # absorbidos por el núcleo, que trae catálogo y reglas de venta. No se
        # traducen a nada porque el núcleo va siempre.
        if "booking" in actuales:
            bloques.append("booking")
        if "healthcare" in actuales:
            if "booking" not in bloques:
                bloques.append("booking")   # no hay receta sin médico
            bloques.append("healthcare")

        # Y se agrega lo que los datos justifican aunque no estuviera asignado:
        # una empresa que ya tiene profesionales cargados usa la agenda, diga
        # lo que diga su configuración.
        if "booking" not in bloques and (
            _hay(conexion, "doctors", company_id)
            or _hay(conexion, "appointments", company_id)
        ):
            bloques.append("booking")
        if "healthcare" not in bloques and (
            _hay(conexion, "prescriptions", company_id)
            or _hay(conexion, "insurers", company_id)
        ):
            if "booking" not in bloques:
                bloques.append("booking")
            bloques.append("healthcare")

        # El portal del profesional se les REGALA a los que tienen el bloque
        # clínico. Quitarle una pantalla a alguien que ya la usa, por una
        # decisión comercial nuestra, es la peor forma de estrenar el modelo
        # por bloques. Quedan como clientes fundadores.
        if "healthcare" in bloques:
            bloques.append("practitioner")

        nuevo = ",".join(bloques)
        conexion.execute(
            sa.text("UPDATE companies SET packs = :p WHERE id = :c"),
            {"p": nuevo, "c": company_id},
        )
        print(f"  [bloques] {nombre[:34]:36} {packs_actual or '(vacío)'} -> {nuevo}")


def downgrade() -> None:
    # Volver a vacío hace que `active_packs` derive del vertical, que es el
    # comportamiento anterior exacto.
    op.execute(sa.text("UPDATE companies SET packs = ''"))
