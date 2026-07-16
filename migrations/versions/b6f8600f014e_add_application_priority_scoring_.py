"""Add application priority scoring: background_text, company_profiles, score columns

Revision ID: b6f8600f014e
Revises: 9af8866f4b14
Create Date: 2026-07-16 16:11:07.709239

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b6f8600f014e'
down_revision = '9af8866f4b14'
branch_labels = None
depends_on = None


def upgrade():
    # NOTE: autogenerate also proposed an `applications.status` type change
    # (VARCHAR -> the Enum it already is on Postgres) here, same SQLite-only
    # artifact as every prior migration in this project (SQLite has no
    # native enum type, so it always diffs against the model regardless of
    # what actually changed). Dropped; unrelated to this migration.
    op.create_table('company_profiles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_name', sa.String(length=200), nullable=False),
    sa.Column('competitiveness_score', sa.Float(), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=True),
    sa.Column('grounded', sa.Boolean(), nullable=False),
    sa.Column('fetched_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('company_profiles', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_company_profiles_company_name'), ['company_name'], unique=True)

    with op.batch_alter_table('applications', schema=None) as batch_op:
        batch_op.add_column(sa.Column('suitability_score', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('competitiveness_score', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('priority_label', sa.String(length=50), nullable=True))

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('background_text', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('background_text')

    with op.batch_alter_table('applications', schema=None) as batch_op:
        batch_op.drop_column('priority_label')
        batch_op.drop_column('competitiveness_score')
        batch_op.drop_column('suitability_score')

    with op.batch_alter_table('company_profiles', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_company_profiles_company_name'))

    op.drop_table('company_profiles')
