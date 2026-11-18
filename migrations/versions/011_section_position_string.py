"""Change section_position column type from INTEGER to String

Revision ID: 011_section_position_string
Revises: 010_add_discussion_marker
Create Date: 2026-07-21

Меняет тип колонки ``section_position`` в таблице ``assignments``
с INTEGER на String/TEXT.

Проблема:
  В модели models.py колонка объявлена как Column(Integer),
  но в реальности туда записываются строковые значения:
  'chairman', 'prayer_open', 'prayer_close' для fixed,
  'conductor', 'reader' для cbs, а также '1','2','3','4' для ministry/treasures/living.
  SQLite терпит это безошибочно, но при переходе на PostgreSQL
  или SQLite strict mode запись упадёт с type error.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "011_section_position_string"
down_revision: Union[str, None] = "010_add_discussion_marker"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("assignments") as batch_op:
        batch_op.alter_column(
            "section_position",
            existing_type=sa.Integer(),
            type_=sa.String(),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("assignments") as batch_op:
        batch_op.alter_column(
            "section_position",
            existing_type=sa.String(),
            type_=sa.Integer(),
            existing_nullable=True,
        )
