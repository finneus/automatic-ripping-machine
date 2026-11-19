"""The operator's preferred audio languages, read for the main-feature pick (`track_selection`)."""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from arm_backend.constants import CONFIG_SINGLETON_ID
from arm_common import Config
from arm_common.languages import preferred_languages


async def preferred_audio_languages(db: AsyncSession) -> list[str]:
    """The `preferred_audio_languages` setting as `preferred_languages` cleans it; empty without a config row."""
    cfg = (await db.execute(select(Config).where(col(Config.id) == CONFIG_SINGLETON_ID))).scalar_one_or_none()
    return preferred_languages(cfg.preferred_audio_languages) if cfg is not None else []
