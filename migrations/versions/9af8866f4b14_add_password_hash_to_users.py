"""Add password_hash to users

Revision ID: 9af8866f4b14
Revises: 0e51bc07a282
Create Date: 2026-07-15 23:54:14.569261

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9af8866f4b14'
down_revision = '0e51bc07a282'
branch_labels = None
depends_on = None


def upgrade():
    # NOTE: autogenerate also proposed an `applications.status` type change
    # (VARCHAR -> the Enum it already is on Postgres) -- that's a SQLite-only
    # artifact of this being generated against the local dev DB (SQLite has
    # no native enum type, so it always shows as a "diff" against the model
    # regardless of what actually changed) rather than a real schema drift.
    # Dropped; unrelated to this migration's actual change.
    with op.batch_alter_table('users', schema=None) as batch_op:
        # Nullable: Google-only accounts (the original login path) never
        # set one -- its absence is how /login-email tells a Google-only
        # account apart from an unregistered email.
        batch_op.add_column(sa.Column('password_hash', sa.String(length=255), nullable=True))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('password_hash')
