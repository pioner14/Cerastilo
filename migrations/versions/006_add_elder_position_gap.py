"""Add elder_position_gap to assignment_config

Revision ID: 006_add_elder_position_gap
Revises: 005_add_excluded_weeks_table
Create Date: 2026-06-10

Adds elder_position_gap column to assignment_config.
When set, this value is used as the minimum position gap for elders
(who are otherwise fully exempt from gap filters).
This enables fair rotation of elders on high-responsibility positions
like CBS conductor and Chairman (every N weeks).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '006_add_elder_position_gap'
down_revision: Union[str, None] = '005_add_excluded_weeks_table'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'assignment_config',
        sa.Column('elder_position_gap', sa.Integer(), nullable=True)
    )
    # Enforce 4-week rotation for elders on CBS conductor and Chairman
    op.execute(
        "UPDATE assignment_config SET elder_position_gap = 4 "
        "WHERE (section = 'cbs' AND position = 'conductor') "
        "   OR (section = 'fixed' AND position = 'chairman')"
    )


def downgrade() -> None:
    op.drop_column('assignment_config', 'elder_position_gap')
