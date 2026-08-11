"""aislamiento a nivel motor: doctor_services con clave foránea compuesta

Revision ID: e58c2b91d7a4
Revises: d4f7a1c93e60
Create Date: 2026-08-11 02:10:00.000000

Principio innegociable #1: el aislamiento entre empresas vive en la CAPA DE
DATOS, no en la disciplina del programador. Dos auditorías ya demostraron que
la disciplina falla.

`doctor_services` era el agujero más grande del modelo: no tenía company_id,
así que era imposible siquiera preguntar de qué empresa era una fila. Nada
impedía ligar el doctor de la empresa A con el servicio de la B, y el bot
resolvía el nombre del profesional sin filtrar por empresa: el cliente de A
podía recibir por WhatsApp el nombre del profesional de B.

Orden obligatorio (lección pagada dos veces en producción): columna nueva con
server_default → backfill → limpieza de huérfanos → índices y claves foráneas.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e58c2b91d7a4'
down_revision: Union[str, None] = 'd4f7a1c93e60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    es_postgres = bind.dialect.name == "postgresql"

    # 1) Columna nueva sobre tabla poblada: nunca NOT NULL sin default.
    with op.batch_alter_table('doctor_services', schema=None) as batch_op:
        batch_op.add_column(sa.Column('company_id', sa.Integer(), nullable=False, server_default='0'))

    # 2) Backfill desde el doctor asociado.
    if es_postgres:
        op.execute(
            "UPDATE doctor_services SET company_id = d.company_id "
            "FROM doctors d WHERE d.id = doctor_services.doctor_id"
        )
    else:
        op.execute(
            "UPDATE doctor_services SET company_id = "
            "(SELECT d.company_id FROM doctors d WHERE d.id = doctor_services.doctor_id)"
        )

    # 3) Huérfanos y cruces entre empresas: hay que sacarlos ANTES de crear la
    #    clave foránea, o la migración falla. Un vínculo que cruza empresas ya
    #    era inválido: se borra y se informa.
    cruces = bind.execute(sa.text(
        "SELECT count(*) FROM doctor_services ds "
        "JOIN doctors d ON d.id = ds.doctor_id "
        "JOIN services s ON s.id = ds.service_id "
        "WHERE d.company_id <> s.company_id"
    )).scalar() or 0
    huerfanos = bind.execute(sa.text(
        "SELECT count(*) FROM doctor_services ds "
        "WHERE NOT EXISTS (SELECT 1 FROM doctors d WHERE d.id = ds.doctor_id) "
        "   OR NOT EXISTS (SELECT 1 FROM services s WHERE s.id = ds.service_id)"
    )).scalar() or 0
    if cruces or huerfanos:
        print(f"[migración] doctor_services: {cruces} vínculos entre empresas distintas "
              f"y {huerfanos} huérfanos. Se eliminan: ya eran inválidos.")
    op.execute(
        "DELETE FROM doctor_services WHERE id IN ("
        " SELECT ds.id FROM doctor_services ds"
        " LEFT JOIN doctors d ON d.id = ds.doctor_id"
        " LEFT JOIN services s ON s.id = ds.service_id"
        " WHERE d.id IS NULL OR s.id IS NULL OR d.company_id <> s.company_id"
        ")"
    )
    op.execute("DELETE FROM doctor_services WHERE company_id = 0")

    with op.batch_alter_table('doctor_services', schema=None) as batch_op:
        batch_op.alter_column('company_id', existing_type=sa.Integer(), server_default=None)
        batch_op.create_index(batch_op.f('ix_doctor_services_company_id'), ['company_id'], unique=False)

    # 4) Las tablas padre necesitan UNIQUE(company_id, id) para poder ser
    #    referenciadas por una clave foránea compuesta.
    with op.batch_alter_table('doctors', schema=None) as batch_op:
        batch_op.create_unique_constraint('uq_doctor_company_id', ['company_id', 'id'])
    with op.batch_alter_table('services', schema=None) as batch_op:
        batch_op.create_unique_constraint('uq_service_company_id', ['company_id', 'id'])

    # 5) Fuera las claves foráneas simples: quedan redundantes y tener dos
    #    formas de decir lo mismo invita a que se desincronicen.
    if es_postgres:
        for fk in bind.execute(sa.text(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'doctor_services'::regclass AND contype = 'f'"
        )).fetchall():
            op.drop_constraint(fk[0], 'doctor_services', type_='foreignkey')

        # 6) Recién ahora: el motor impide el cruce entre empresas.
        op.create_foreign_key(
            'fk_doctor_services_doctor_tenant', 'doctor_services', 'doctors',
            ['company_id', 'doctor_id'], ['company_id', 'id'],
        )
        op.create_foreign_key(
            'fk_doctor_services_service_tenant', 'doctor_services', 'services',
            ['company_id', 'service_id'], ['company_id', 'id'],
        )
    # En SQLite las claves foráneas se recrean con la tabla; los tests usan
    # create_all sobre el modelo, que ya las declara compuestas.


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_constraint('fk_doctor_services_service_tenant', 'doctor_services', type_='foreignkey')
        op.drop_constraint('fk_doctor_services_doctor_tenant', 'doctor_services', type_='foreignkey')
        op.create_foreign_key(None, 'doctor_services', 'doctors', ['doctor_id'], ['id'])
        op.create_foreign_key(None, 'doctor_services', 'services', ['service_id'], ['id'])
    with op.batch_alter_table('services', schema=None) as batch_op:
        batch_op.drop_constraint('uq_service_company_id', type_='unique')
    with op.batch_alter_table('doctors', schema=None) as batch_op:
        batch_op.drop_constraint('uq_doctor_company_id', type_='unique')
    with op.batch_alter_table('doctor_services', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_doctor_services_company_id'))
        batch_op.drop_column('company_id')
