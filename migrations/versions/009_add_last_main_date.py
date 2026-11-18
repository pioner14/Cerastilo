"""Add last_main_date to participants

Revision ID: 009_add_last_main_date
Revises: 008_participant_position_configs
Create Date: 2026-06-18

Добавляет колонку ``last_main_date`` в таблицу ``participants``.

Проблема:
  Ранее ``last_assignment_date`` обновлялось для ОБЕИХ ролей — главного и
  напарника.  Из-за этого участник, назначенный напарником, оказывался
  заблокированным от главной роли на полный интервал (min_gap недель), как
  будто он только что выступал в главной роли.

  Пример (Ларцева Любовь, min_gap=4):
    01.06 — главный → last_assignment_date = 01.06
    03.08 — напарник → last_assignment_date = 03.08  ← блокирует до 31.08!
  За 7 недель (08.06–27.07) алгоритм её обходил из-за высокой конкуренции,
  а когда наконец взял — только напарником, обнулив счётчик заново.

Решение:
  ``last_main_date`` — дата последнего назначения в роли ГЛАВНОГО участника.
  Алгоритм при фильтрации кандидатов на главную роль теперь использует
  ``last_main_date`` вместо ``last_assignment_date``.

  Роль напарника по-прежнему обновляет ``last_assignment_date`` (для проверки
  «занят ли на этой неделе»), но НЕ сдвигает очередь на главную роль.

Инициализация:
  Для существующих записей ``last_main_date`` устанавливается равным
  ``last_assignment_date`` (консервативный старт).  Алгоритм сам откорректирует
  значения по мере работы.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "009_add_last_main_date"
down_revision: Union[str, None] = "008_participant_position_configs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "participants",
        sa.Column("last_main_date", sa.DateTime(), nullable=True),
    )

    # Инициализация: копируем last_assignment_date как стартовое значение.
    # Это консервативно: кто был напарником — получит «честный» старт.
    # Алгоритм откорректирует при следующих авто-назначениях.
    op.execute(
        "UPDATE participants SET last_main_date = last_assignment_date "
        "WHERE last_assignment_date IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("participants", "last_main_date")
