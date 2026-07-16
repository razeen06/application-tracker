"""Add resume_structured to users

Revision ID: 9d036093b81f
Revises: b6f8600f014e
Create Date: 2026-07-16 22:32:12.488370

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9d036093b81f'
down_revision = 'b6f8600f014e'
branch_labels = None
depends_on = None


def upgrade():
    # NOTE: autogenerate also proposed an `applications.status` type change
    # (VARCHAR -> the Enum it already is on Postgres) here, same SQLite-only
    # artifact as every prior migration in this project (SQLite has no
    # native enum type, so it always diffs against the model regardless of
    # what actually changed). Dropped; unrelated to this migration.
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('resume_structured', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('resume_structured')
