"""Add notification history table."""
from alembic import op
import sqlalchemy as sa

revision = "013_add_notification_history"
down_revision = "012_add_email_phone"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notification_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("participant_id", sa.Integer(), nullable=False),
        sa.Column("week_id", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("status", sa.String(20), nullable=False),  # "success" или "error"
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("subject", sa.String(200), nullable=True),
    )
    op.create_index(
        op.f("ix_notification_history_participant_id"),
        "notification_history",
        ["participant_id"],
    )
    op.create_index(
        op.f("ix_notification_history_week_id"),
        "notification_history",
        ["week_id"],
    )


def downgrade():
    op.drop_table("notification_history")
