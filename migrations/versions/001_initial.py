"""Initial schema - create all tables

Revision ID: 001_initial
Revises: 
Create Date: 2026-03-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === Participants ===
    op.create_table(
        'participants',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('gender', sa.String(), nullable=True),
        sa.Column('service_type', sa.String(), nullable=True),
        sa.Column('family_group_id', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('last_assignment_date', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint("gender IN ('male', 'female')", name='ck_participants_gender'),
        sa.PrimaryKeyConstraint('id')
    )

    # === Participant Qualifications (many-to-many) ===
    op.create_table(
        'participant_qualifications',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('participant_id', sa.Integer(), nullable=False),
        sa.Column('qualification_name', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['participant_id'], ['participants.id']),
        sa.UniqueConstraint('participant_id', 'qualification_name'),
        sa.PrimaryKeyConstraint('id')
    )

    # === Weeks ===
    op.create_table(
        'weeks',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('week_title', sa.String(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('bible_reading', sa.String(), nullable=True),
        sa.Column('month', sa.String(), nullable=True),
        sa.Column('year', sa.Integer(), nullable=True),
        sa.Column('workbook_source', sa.String(), nullable=True),
        sa.Column('special_event', sa.String(), nullable=True),
        sa.Column('announcement', sa.String(), nullable=True),
        sa.Column('songs', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # === Assignments ===
    op.create_table(
        'assignments',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('week_id', sa.Integer(), nullable=False),
        sa.Column('assignment_text', sa.String(), nullable=False),
        sa.Column('assignment_type', sa.String(), nullable=True),
        sa.Column('assignment_number', sa.String(), nullable=True),
        sa.Column('section', sa.String(), nullable=True),
        sa.Column('section_position', sa.Integer(), nullable=True),
        sa.Column('duration', sa.Integer(), nullable=True),
        sa.Column('participant_id', sa.Integer(), nullable=True),
        sa.Column('assistant_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['week_id'], ['weeks.id']),
        sa.ForeignKeyConstraint(['participant_id'], ['participants.id']),
        sa.ForeignKeyConstraint(['assistant_id'], ['participants.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # === Assignment Config ===
    op.create_table(
        'assignment_config',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('section', sa.String(), nullable=False),
        sa.Column('position', sa.String(), nullable=False),
        sa.Column('assignment_name', sa.String(), nullable=True),
        sa.Column('required_qualification', sa.String(), nullable=True),
        sa.Column('is_brothers_only', sa.Boolean(), default=False),
        sa.Column('needs_assistant', sa.Boolean(), default=False),
        sa.UniqueConstraint('section', 'position'),
        sa.PrimaryKeyConstraint('id')
    )

    # === Settings ===
    op.create_table(
        'settings',
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('value', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('key')
    )

    # === Groups (for cleaning schedule) ===
    op.create_table(
        'groups',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('order', sa.Integer(), default=0),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.PrimaryKeyConstraint('id')
    )

    # === Cleaning Schedule ===
    op.create_table(
        'cleaning_schedule',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('week_start', sa.Date(), nullable=False),
        sa.Column('group_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['group_id'], ['groups.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('week_start', name='uix_cleaning_week')
    )

    # === Attendant Schedule ===
    op.create_table(
        'attendant_schedule',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('week_start', sa.Date(), nullable=False),
        sa.Column('meeting_type', sa.String(length=20), nullable=False),
        sa.Column('participant_id', sa.Integer(), nullable=True),
        sa.Column('position', sa.Integer(), default=1),
        sa.ForeignKeyConstraint(['participant_id'], ['participants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('week_start', 'meeting_type', 'position', name='uix_attendant_week_meeting_pos')
    )

    # === Microphone Schedule ===
    op.create_table(
        'microphone_schedule',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('week_start', sa.Date(), nullable=False),
        sa.Column('meeting_type', sa.String(length=20), nullable=False),
        sa.Column('participant_id', sa.Integer(), nullable=True),
        sa.Column('position', sa.Integer(), default=1),
        sa.ForeignKeyConstraint(['participant_id'], ['participants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('week_start', 'meeting_type', 'position', name='uix_microphone_week_meeting_pos')
    )

    # === Sound Schedule ===
    op.create_table(
        'sound_schedule',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('week_start', sa.Date(), nullable=False),
        sa.Column('meeting_type', sa.String(length=20), nullable=False),
        sa.Column('participant_id', sa.Integer(), nullable=True),
        sa.Column('position', sa.Integer(), default=1),
        sa.ForeignKeyConstraint(['participant_id'], ['participants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('week_start', 'meeting_type', 'position', name='uix_sound_week_meeting_pos')
    )

    # === Zoom Attendant Schedule ===
    op.create_table(
        'zoom_attendant_schedule',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('week_start', sa.Date(), nullable=False),
        sa.Column('meeting_type', sa.String(length=20), nullable=False),
        sa.Column('participant_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['participant_id'], ['participants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('week_start', 'meeting_type', name='uix_zoom_week_meeting')
    )

    # === Stage Schedule ===
    op.create_table(
        'stage_schedule',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('week_start', sa.Date(), nullable=False),
        sa.Column('meeting_type', sa.String(length=20), nullable=False),
        sa.Column('participant_id', sa.Integer(), nullable=True),
        sa.Column('position', sa.Integer(), default=1),
        sa.ForeignKeyConstraint(['participant_id'], ['participants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('week_start', 'meeting_type', 'position', name='uix_stage_week_meeting_pos')
    )


def downgrade() -> None:
    # Drop tables in reverse order (respecting foreign keys)
    op.drop_table('stage_schedule')
    op.drop_table('zoom_attendant_schedule')
    op.drop_table('sound_schedule')
    op.drop_table('microphone_schedule')
    op.drop_table('attendant_schedule')
    op.drop_table('cleaning_schedule')
    op.drop_table('groups')
    op.drop_table('settings')
    op.drop_table('assignment_config')
    op.drop_table('assignments')
    op.drop_table('weeks')
    op.drop_table('participant_qualifications')
    op.drop_table('participants')
