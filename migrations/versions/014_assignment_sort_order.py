"""Add manual ordering to assignments."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014_assignment_sort_order"
down_revision: Union[str, None] = "013_add_notification_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("assignments") as batch_op:
        batch_op.add_column(sa.Column("sort_order", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("assignments") as batch_op:
        batch_op.drop_column("sort_order")
