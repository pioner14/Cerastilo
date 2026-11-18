"""Ответы участников на уведомления: подтвердил / не сможет."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "018_notification_responses"
down_revision: Union[str, None] = "017_assignment_updated_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notification_responses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("participant_id", sa.Integer(), nullable=False),
        sa.Column("week_id", sa.Integer(), nullable=False),
        sa.Column("response", sa.String(20), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("responded_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("participant_id", "week_id", name="uq_notification_response"),
    )
    op.create_index("ix_notification_responses_participant_id", "notification_responses", ["participant_id"])
    op.create_index("ix_notification_responses_week_id", "notification_responses", ["week_id"])


def downgrade() -> None:
    op.drop_table("notification_responses")
