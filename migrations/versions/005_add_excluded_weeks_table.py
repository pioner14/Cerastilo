"""Add participant_excluded_weeks table

Revision ID: 005_add_excluded_weeks_table
Revises: 004_add_unavailability
Create Date: 2026-06-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '005_add_excluded_weeks_table'
down_revision: Union[str, None] = '004_add_unavailability'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'participant_excluded_weeks',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('participant_id', sa.Integer(), nullable=False),
        sa.Column('week_start', sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(['participant_id'], ['participants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('participant_id', 'week_start', name='uix_excluded_week_participant')
    )


def downgrade() -> None:
    op.drop_table('participant_excluded_weeks')
