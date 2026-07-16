"""Repair a partially applied password_hash migration.

Revision ID: a1c7d4e9f203
Revises: 9d036093b81f
"""

from alembic import op
import sqlalchemy as sa


revision = "a1c7d4e9f203"
down_revision = "9d036093b81f"
branch_labels = None
depends_on = None


def upgrade():
    # The production database has recorded later revisions while this
    # nullable column is absent. Make the repair safe for both that damaged
    # database and fresh installs where 9af8866f4b14 already added it.
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255)"
        )
    else:
        inspector = sa.inspect(op.get_bind())
        if "password_hash" not in {column["name"] for column in inspector.get_columns("users")}:
            with op.batch_alter_table("users", schema=None) as batch_op:
                batch_op.add_column(
                    sa.Column("password_hash", sa.String(length=255), nullable=True)
                )


def downgrade():
    # Deliberately leave the repaired column in place. Dropping it would
    # reintroduce the production outage this compatibility migration fixes.
    pass
