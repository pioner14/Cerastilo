"""Add personal_gap to participants

Revision ID: 002_add_personal_gap
Revises: 001_initial
Create Date: 2026-06-02

personal_gap — персональный интервал назначений (в неделях).
NULL  = использовать умолчание по service_type
0     = всегда доступен (как старейшины)
N > 0 = не чаще раза в N недель
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002_add_personal_gap'
down_revision: Union[str, None] = '001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'participants',
        sa.Column('personal_gap', sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('participants', 'personal_gap')
