"""Add email and phone to participants

Revision ID: 012_add_email_phone
Revises: 011_section_position_string
Create Date: 2026-08-26

email — адрес электронной почты участника для отправки уведомлений о заданиях.
phone — номер телефона (справочно, из списка возвещателей).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '012_add_email_phone'
down_revision: Union[str, None] = '011_section_position_string'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'participants',
        sa.Column('email', sa.String(), nullable=True)
    )
    op.add_column(
        'participants',
        sa.Column('phone', sa.String(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('participants', 'phone')
    op.drop_column('participants', 'email')
