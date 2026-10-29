"""Add append-only alert review history.

Revision ID: 20261023_01
Revises: None
"""
from alembic import op

from app.models.review_event import AlertReviewEvent

revision = "20261023_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    AlertReviewEvent.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade():
    AlertReviewEvent.__table__.drop(bind=op.get_bind(), checkfirst=True)