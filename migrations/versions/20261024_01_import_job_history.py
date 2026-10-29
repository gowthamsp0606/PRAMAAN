"""Add persistent CSV import jobs and row results.

Revision ID: 20261024_01
Revises: 20261023_01
"""
from alembic import op

from app.models.import_job import ImportJob, ImportRowResult

revision = "20261024_01"
down_revision = "20261023_01"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    ImportJob.__table__.create(bind=bind, checkfirst=True)
    ImportRowResult.__table__.create(bind=bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    ImportRowResult.__table__.drop(bind=bind, checkfirst=True)
    ImportJob.__table__.drop(bind=bind, checkfirst=True)