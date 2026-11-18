"""Add participant_position_configs table

Revision ID: 008_participant_position_configs
Revises: 007_add_is_exclusive
Create Date: 2026-06-15

Adds the ``participant_position_configs`` table that stores per-participant
position gap overrides.

Business rule:
  The ``elder_position_gap`` in ``assignment_config`` sets a *global* minimum
  interval for all elders on a given position (e.g. all elders do Chairman no
  more than once every 4 weeks).  This new table lets you override that gap
  *per participant* — for example, the meeting overseer
  is allowed to chair more frequently (every 2 weeks instead of 4).

Priority in the algorithm (highest → lowest):
  1. participant_position_configs.position_gap   ← this table
  2. assignment_config.elder_position_gap        ← global elder override
  3. eff_gap == 0  → participant fully exempt (default for elders)
  4. eff_gap * 2   → standard formula

Initial data inserted by this migration:
  - participant id=8 (the meeting overseer): fixed/chairman, position_gap=2
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "008_participant_position_configs"
down_revision: Union[str, None] = "007_add_is_exclusive"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "participant_position_configs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "participant_id",
            sa.Integer(),
            sa.ForeignKey("participants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("section", sa.String(), nullable=False),
        sa.Column("position", sa.String(), nullable=False),
        sa.Column("position_gap", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "participant_id", "section", "position",
            name="uix_participant_position_config",
        ),
    )

    # Участник с id=8 — руководитель встречи (в базе владельца),
    # поэтому ему разрешено быть председателем раз в 2 недели (вместо 4).
    op.execute(
        "INSERT INTO participant_position_configs "
        "(participant_id, section, position, position_gap) "
        "VALUES (8, 'fixed', 'chairman', 2)"
    )


def downgrade() -> None:
    op.drop_table("participant_position_configs")
