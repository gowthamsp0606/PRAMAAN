"""Phase 3: Student identity lifecycle and nullable APAAR ID for historical records.

Revision ID: 20261027_01
Revises: 20261026_01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20261027_01"
down_revision = "20261026_01"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "students" in tables:
        cols = {col["name"] for col in inspector.get_columns("students")}
        with op.batch_alter_table("students", schema=None) as batch_op:
            if "identity_status" not in cols:
                batch_op.add_column(
                    sa.Column(
                        "identity_status",
                        sa.String(32),
                        nullable=False,
                        server_default="APAAR_VERIFIED",
                    )
                )
            batch_op.alter_column(
                "apaar_id",
                existing_type=sa.String(32),
                nullable=True,
            )

    if "enrolments" in tables:
        with op.batch_alter_table("enrolments", schema=None) as batch_op:
            batch_op.alter_column(
                "apaar_id",
                existing_type=sa.String(32),
                nullable=True,
            )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "enrolments" in tables:
        with op.batch_alter_table("enrolments", schema=None) as batch_op:
            batch_op.alter_column(
                "apaar_id",
                existing_type=sa.String(32),
                nullable=False,
            )

    if "students" in tables:
        cols = {col["name"] for col in inspector.get_columns("students")}
        with op.batch_alter_table("students", schema=None) as batch_op:
            if "identity_status" in cols:
                batch_op.drop_column("identity_status")
            batch_op.alter_column(
                "apaar_id",
                existing_type=sa.String(32),
                nullable=False,
            )
