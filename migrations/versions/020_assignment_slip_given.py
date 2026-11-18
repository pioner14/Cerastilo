"""Отметка «листок выдан» у пункта расписания."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "020_assignment_slip_given"
down_revision: Union[str, None] = "019_participant_updated_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Колонку могла уже добавить ensure_required_columns (core/database.py)
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("assignments")}
    if "slip_given_at" in columns:
        return
    with op.batch_alter_table("assignments") as batch_op:
        batch_op.add_column(sa.Column("slip_given_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("assignments") as batch_op:
        batch_op.drop_column("slip_given_at")
