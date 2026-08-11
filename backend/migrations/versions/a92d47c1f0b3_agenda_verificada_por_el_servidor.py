"""agenda verificada por el servidor: franjas, ausencias y duración real

Revision ID: a92d47c1f0b3
Revises: f7a13b8e02d5
Create Date: 2026-08-11 15:30:00.000000

`Doctor.schedule` es texto libre, así que la única forma de saber si el doctor
atendía un martes a las 10 era que el MODELO interpretara ese string. Un
paciente podía quedar agendado un domingo a las 23:00 con un profesional que
atiende lunes a viernes de mañana, y el sistema le mandaba el recordatorio
T-24h de una cita que no existía.

Todo entra con `server_default` igual al comportamiento de hoy:
- `doctors.agenda_mode = 'libre'` es el estado real del 100% de los doctores,
  y en modo libre se les sigue agendando. Bloquear a una clínica que no cargó
  su horario le rompe el negocio; inventarle una franja sería peor.
- `appointments.duration_min = 30` es el DEFAULT_SLOT_MIN que ya usaba el
  motor, así que las citas viejas conservan su comportamiento.
- `appointments.verificacion = 'sin_verificar'` es la verdad sobre lo ya
  agendado: nadie lo validó contra un horario.

NO se inserta ninguna franja. Ningún horario nace de una regex sobre el texto
libre: eso sería la misma regla violada con otro disfraz.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a92d47c1f0b3'
down_revision: Union[str, None] = 'f7a13b8e02d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('doctors', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'agenda_mode', sa.String(length=15), nullable=False, server_default='libre'))

    with op.batch_alter_table('appointments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('service_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column(
            'duration_min', sa.Integer(), nullable=False, server_default='30'))
        batch_op.add_column(sa.Column(
            'verificacion', sa.String(length=20), nullable=False,
            server_default='sin_verificar'))
        batch_op.create_index('ix_appointments_service_id', ['service_id'])

    op.create_table(
        'doctor_schedules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        # Nulo = horario de la INSTITUCIÓN: cinco filas cubren a los 40
        # médicos y matan el "domingo a las 23:00" el día uno.
        sa.Column('doctor_id', sa.Integer(), nullable=True),
        # Nulo = la franja vale para todo. Con servicio, vale SOLO para ese:
        # así se representa al profesional que atiende consulta toda la semana
        # pero hace ecocardiogramas solo los martes a la tarde.
        sa.Column('service_id', sa.Integer(), nullable=True),
        sa.Column('weekday', sa.Integer(), nullable=False),
        # Minutos desde medianoche: toda la aritmética de huecos y solapes se
        # hace en minutos.
        sa.Column('hora_inicio', sa.Integer(), nullable=False),
        sa.Column('hora_fin', sa.Integer(), nullable=False),
        sa.Column('lugar', sa.String(length=120), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.ForeignKeyConstraint(
            ['company_id', 'doctor_id'], ['doctors.company_id', 'doctors.id'],
            name='fk_doctor_schedules_doctor_tenant', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['company_id', 'service_id'], ['services.company_id', 'services.id'],
            name='fk_doctor_schedules_service_tenant', ondelete='CASCADE'),
        sa.CheckConstraint('weekday >= 0 AND weekday <= 6', name='ck_schedule_weekday'),
        sa.CheckConstraint('hora_fin > hora_inicio', name='ck_schedule_rango'),
    )
    op.create_index('ix_doctor_schedules_company_id', 'doctor_schedules', ['company_id'])
    op.create_index('ix_doctor_schedules_doctor_id', 'doctor_schedules', ['doctor_id'])

    op.create_table(
        'doctor_absences',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        # Nulo = cierra la clínica entera ese día, para todos.
        sa.Column('doctor_id', sa.Integer(), nullable=True),
        sa.Column('desde', sa.Date(), nullable=False),
        sa.Column('hasta', sa.Date(), nullable=False),
        sa.Column('motivo', sa.String(length=120), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.ForeignKeyConstraint(
            ['company_id', 'doctor_id'], ['doctors.company_id', 'doctors.id'],
            name='fk_doctor_absences_doctor_tenant', ondelete='CASCADE'),
        sa.CheckConstraint('hasta >= desde', name='ck_absence_rango'),
    )
    op.create_index('ix_doctor_absences_company_id', 'doctor_absences', ['company_id'])
    op.create_index('ix_doctor_absences_doctor_id', 'doctor_absences', ['doctor_id'])
    op.create_index('ix_doctor_absences_desde', 'doctor_absences', ['desde'])


def downgrade() -> None:
    op.drop_table('doctor_absences')
    op.drop_table('doctor_schedules')
    with op.batch_alter_table('appointments', schema=None) as batch_op:
        batch_op.drop_index('ix_appointments_service_id')
        batch_op.drop_column('verificacion')
        batch_op.drop_column('duration_min')
        batch_op.drop_column('service_id')
    with op.batch_alter_table('doctors', schema=None) as batch_op:
        batch_op.drop_column('agenda_mode')
