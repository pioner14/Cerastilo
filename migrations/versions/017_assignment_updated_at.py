"""Время изменения назначения — для синхронизации ПК ↔ планшет."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "017_assignment_updated_at"
down_revision: Union[str, None] = "016_drop_assignment_templates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("assignments") as batch_op:
        batch_op.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("assignments") as batch_op:
        batch_op.drop_column("updated_at")
