from arm_backend.audio_preference import preferred_audio_languages
from arm_common import Config

from tests._fakes import FakeSession


async def test_reads_the_cleaned_setting() -> None:
    db = FakeSession()
    db.rows["config"] = [Config(id=1, preferred_audio_languages=["ger", "eng", "nope"])]
    assert await preferred_audio_languages(db) == ["deu", "eng"]  # type: ignore[arg-type]


async def test_is_empty_without_a_config_row() -> None:
    db = FakeSession()
    db.rows["config"] = []
    assert await preferred_audio_languages(db) == []  # type: ignore[arg-type]
