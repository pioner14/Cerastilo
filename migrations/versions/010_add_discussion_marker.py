"""Add discussion_marker to assignments

Revision ID: 010_add_discussion_marker
Revises: 009_add_last_main_date
Create Date: 2026-07-15

Добавляет колонку ``discussion_marker`` в таблицу ``assignments``.

Проблема:
  С сентября 2025/2026 г. в рабочей тетради появился новый формат пункта
  в разделе «Оттачиваем навыки служения» (ministry) — «Обсуждение».
  В EPUB маркер «(N мин.) Обсуждение» располагается в параграфе-теле
  после заголовка H3, а не в самом заголовке.  Парсер ранее его не
  извлекал, поэтому в БД слово «обсуждение» отсутствовало и override,
  срабатывающий по ``assignment_text``, никогда не применялся.

Решение:
  Парсер EPUB теперь извлекает начальную подстроку «(N мин.) Обсуждение»
  из соседнего параграфа и сохраняет её в ``discussion_marker``.
  Алгоритм авто-назначения использует именно это поле (надёжнее, чем
  текст задания) для назначения пункта одному брату без напарника.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "010_add_discussion_marker"
down_revision: Union[str, None] = "009_add_last_main_date"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "assignments",
        sa.Column("discussion_marker", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("assignments", "discussion_marker")
