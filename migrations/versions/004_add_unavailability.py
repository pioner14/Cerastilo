"""Add unavailability dates to participants

Revision ID: 004_add_unavailability
Revises: 003_add_is_minor
Create Date: 2026-06-03

Add unavailable_from and unavailable_to columns to participants table
for temporary/vacation exclusion.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '004_add_unavailability'
down_revision: Union[str, None] = '003_add_is_minor'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'participants',
        sa.Column('unavailable_from', sa.Date(), nullable=True)
    )
    op.add_column(
        'participants',
        sa.Column('unavailable_to', sa.Date(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('participants', 'unavailable_from')
    op.drop_column('participants', 'unavailable_to')
