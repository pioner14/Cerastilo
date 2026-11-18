"""Время правки карточки участника — для синхронизации ПК ↔ планшет."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "019_participant_updated_at"
down_revision: Union[str, None] = "018_notification_responses"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Колонку могла уже добавить ensure_required_columns (core/database.py)
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("participants")}
    if "updated_at" in columns:
        return
    with op.batch_alter_table("participants") as batch_op:
        batch_op.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("participants") as batch_op:
        batch_op.drop_column("updated_at")
