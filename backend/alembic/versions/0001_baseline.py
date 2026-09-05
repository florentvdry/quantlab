"""QuantLab baseline schema.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-05

The baseline is intentionally idempotent for existing local V1 databases: SQLAlchemy
creates only missing tables, then Alembic records the revision. Future schema changes
must use normal Alembic operations.
"""
from alembic import op
from app.db.session import Base
import app.models.entities  # noqa: F401

revision="0001_baseline"
down_revision=None
branch_labels=None
depends_on=None

def upgrade():
    Base.metadata.create_all(bind=op.get_bind())

def downgrade():
    Base.metadata.drop_all(bind=op.get_bind())
