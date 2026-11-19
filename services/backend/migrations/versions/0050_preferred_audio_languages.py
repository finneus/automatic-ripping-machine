"""Add config.preferred_audio_languages: the audio languages the main-feature pick prefers.

A UHD often carries the film several times at the same length, one variant per language group. The main-feature
rip preset now picks among them by audio language; this setting says which ones to prefer, in order. Empty (the
default) prefers the variant with the most audio languages.

Revision ID: 0050_preferred_audio_languages
Revises: 0049_transcode_task_telemetry
Create Date: 2026-11-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0050_preferred_audio_languages"
down_revision: Union[str, None] = "0049_transcode_task_telemetry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "config",
        sa.Column("preferred_audio_languages", postgresql.ARRAY(sa.String()), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("config", "preferred_audio_languages")
