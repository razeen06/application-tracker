"""Add Closed status and hiring end date

Revision ID: c4e8a2d7b901
Revises: a1c7d4e9f203
Create Date: 2026-07-19 15:45:00.000000

"""
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "c4e8a2d7b901"
down_revision = "a1c7d4e9f203"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        # Application.status uses a native Postgres enum in production. The
        # new label must be committed before application requests can write
        # it, so use the same safe autocommit pattern as the earlier status
        # expansion migration.
        with op.get_context().autocommit_block():
            op.execute(
                "ALTER TYPE applicationstatus ADD VALUE IF NOT EXISTS 'CLOSED'"
            )

    op.add_column(
        "applications",
        sa.Column("hiring_end_date", sa.Date(), nullable=True),
    )


def downgrade():
    op.drop_column("applications", "hiring_end_date")
    # Postgres cannot safely remove one enum label in place. CLOSED remains
    # available but unused after downgrade, matching the precedent set by
    # 0e51bc07a282.
