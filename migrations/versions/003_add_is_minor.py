"""Add is_minor to participants

Revision ID: 003_add_is_minor
Revises: 002_add_personal_gap
Create Date: 2026-06-03

is_minor — признак несовершеннолетнего участника.
Несовершеннолетний может быть в паре ТОЛЬКО с:
  - другим несовершеннолетним (как главный или помощник)
  - взрослым членом своей семьи (только как помощник)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '003_add_is_minor'
down_revision: Union[str, None] = '002_add_personal_gap'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'participants',
        sa.Column('is_minor', sa.Boolean(), nullable=False, server_default='0')
    )


def downgrade() -> None:
    op.drop_column('participants', 'is_minor')
