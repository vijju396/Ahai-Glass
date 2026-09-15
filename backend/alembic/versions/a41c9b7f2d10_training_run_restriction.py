"""training run restriction

Records what a scoped run was cut down to, so a leaderboard built from two
branches can never be read as a network result.

Revision ID: a41c9b7f2d10
Revises: 533752466943
Create Date: 2026-09-10 00:00:00.000000+00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'a41c9b7f2d10'
down_revision = '533752466943'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'training_run',
        sa.Column('restriction_json', sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('training_run', 'restriction_json')
