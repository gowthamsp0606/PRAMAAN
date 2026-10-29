"""Add a composite index for exact enrolment duplicate lookups.

Revision ID: 20261026_01
Revises: 20261024_01
"""
from alembic import op
from sqlalchemy import inspect

revision = "20261026_01"
down_revision = "20261024_01"
branch_labels = None
depends_on = None

INDEX_NAME = "idx_enrolment_duplicate_lookup"
TABLE_NAME = "enrolments"
COLUMNS = ["student_ref", "institution_id", "programme_id", "enrolment_start"]


def upgrade():
    inspector = inspect(op.get_bind())
    if TABLE_NAME not in inspector.get_table_names():
        # Fresh installations create the index from SQLAlchemy model metadata.
        return
    existing = {index["name"] for index in inspector.get_indexes(TABLE_NAME)}
    if INDEX_NAME not in existing:
        op.create_index(INDEX_NAME, TABLE_NAME, COLUMNS, unique=False)


def downgrade():
    inspector = inspect(op.get_bind())
    if TABLE_NAME in inspector.get_table_names():
        existing = {index["name"] for index in inspector.get_indexes(TABLE_NAME)}
        if INDEX_NAME in existing:
            op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
