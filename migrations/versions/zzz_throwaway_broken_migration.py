"""THROWAWAY: deliberately broken migration to verify CI + branch protection

This migration is intentionally broken -- it re-adds a column that already
exists (resume_structured was added in 9d036093b81f), which fails with a
Postgres DuplicateColumn error. Used only to verify the "migrations" CI job
and branch protection actually block a bad PR. This branch is never merged
and is deleted after the test.

Revision ID: zzz_throwaway
Revises: 9d036093b81f
Create Date: 2026-07-16 23:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'zzz_throwaway'
down_revision = '9d036093b81f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('resume_structured', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('resume_structured')
