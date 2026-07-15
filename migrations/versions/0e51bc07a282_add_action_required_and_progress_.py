"""Add Action Required and Progress statuses

Revision ID: 0e51bc07a282
Revises: 88d89c372a36
Create Date: 2026-07-15 18:30:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '0e51bc07a282'
down_revision = '88d89c372a36'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        # Postgres backs db.Enum(ApplicationStatus) with a native ENUM type,
        # so new members need an explicit ALTER TYPE. ADD VALUE can't run
        # inside the transaction Alembic normally wraps migrations in (the
        # new label isn't visible until the transaction commits), hence the
        # autocommit_block.
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE applicationstatus ADD VALUE IF NOT EXISTS 'ACTION_REQUIRED'")
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE applicationstatus ADD VALUE IF NOT EXISTS 'PROGRESS'")
    # SQLite has no native enum type -- the original migration stored
    # `status` as a plain VARCHAR with no CHECK constraint, so new Python
    # enum members are already writable there without any DDL change.


def downgrade():
    # Postgres has no ALTER TYPE ... DROP VALUE. Removing these would require
    # rebuilding the enum type (rename, create new, migrate column, drop old),
    # which isn't safe to do generically without knowing whether any row is
    # already using the new values. Left as a no-op; the extra enum members
    # simply go unused if this migration is rolled back.
    pass
