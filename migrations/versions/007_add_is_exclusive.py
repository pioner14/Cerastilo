"""Add is_exclusive to assignment_config

Revision ID: 007_add_is_exclusive
Revises: 006_add_elder_position_gap
Create Date: 2026-06-12

Adds is_exclusive BOOLEAN column to assignment_config.

When is_exclusive = 0 (False), being assigned to this position does NOT
prevent the participant from receiving additional assignments in the same
week (e.g. prayer + ministry student assignment are compatible).

Replaces the fragile qualification-name-based detection in
auto_assignment_service.py (non_blocking_assigned / _NON_EXCLUSIVE_QUALS).

Default = 1 (True) — all existing positions remain fully exclusive.
Non-exclusive positions: prayer_open, prayer_close, bible_reading.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '007_add_is_exclusive'
down_revision: Union[str, None] = '006_add_elder_position_gap'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'assignment_config',
        sa.Column('is_exclusive', sa.Boolean(), nullable=False, server_default='1')
    )
    # Mark prayer and Bible reading as non-exclusive:
    # a participant assigned to these can still receive a ministry assignment.
    op.execute(
        "UPDATE assignment_config SET is_exclusive = 0 "
        "WHERE (section = 'fixed' AND position IN ('prayer_open', 'prayer_close')) "
        "   OR (section = 'treasures' AND position = '3')"
    )


def downgrade() -> None:
    op.drop_column('assignment_config', 'is_exclusive')
