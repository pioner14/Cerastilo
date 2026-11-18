"""Create assignment templates table."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "015_assignment_templates"
down_revision: Union[str, None] = "014_assignment_sort_order"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assignment_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("section", sa.String(), nullable=False),
        sa.Column("duration", sa.Integer(), nullable=False, server_default="5"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("text", "section", name="uq_assignment_template"),
    )


def downgrade() -> None:
    op.drop_table("assignment_templates")
