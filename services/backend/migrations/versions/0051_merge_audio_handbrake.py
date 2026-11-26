"""Merge the two 0050 heads: preferred_audio_languages and handbrake_settings.

Both revisions branch from 0049 and touch different tables, so the merge carries no DDL. A database already at either
head upgrades through the other one and lands here.

Revision ID: 0051_merge_audio_handbrake
Revises: 0050_handbrake_settings, 0050_preferred_audio_languages
Create Date: 2026-11-26
"""

from typing import Sequence, Union

revision: str = "0051_merge_audio_handbrake"
down_revision: Union[str, Sequence[str], None] = ("0050_handbrake_settings", "0050_preferred_audio_languages")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
