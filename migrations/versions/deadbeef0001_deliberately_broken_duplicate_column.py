"""THROWAWAY -- deliberately broken migration, for CI verification only

Duplicates the password_hash column add from 9af8866f4b14, which already
ran earlier in the chain. Applying this against a database that already
went through 9af8866f4b14 must fail with "column already exists" -- this
is exactly the class of bug (a migration that doesn't actually apply
cleanly) the "migrations" CI job exists to catch before it reaches
production. Never meant to be merged.

Revision ID: deadbeef0001
Revises: 9af8866f4b14
Create Date: 2026-07-16 05:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'deadbeef0001'
down_revision = '9af8866f4b14'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        # password_hash already exists as of 9af8866f4b14 -- this must fail.
        batch_op.add_column(sa.Column('password_hash', sa.String(length=255), nullable=True))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('password_hash')
