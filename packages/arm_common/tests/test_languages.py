import pytest

from arm_common.languages import AUDIO_LANGUAGE_LABELS, preferred_languages, terminological


@pytest.mark.parametrize(
    ("code", "expected"),
    [("ger", "deu"), ("GER", "deu"), (" fre ", "fra"), ("deu", "deu"), ("eng", "eng"), ("xyz", "xyz")],
)
def test_terminological(code: str, expected: str) -> None:
    assert terminological(code) == expected


def test_preferred_languages_keeps_known_codes_once_in_order() -> None:
    assert preferred_languages(["ger", "eng", "deu", "klingon", "ENG"]) == ["deu", "eng"]


def test_preferred_languages_of_nothing_is_empty() -> None:
    assert preferred_languages(None) == []
    assert preferred_languages([]) == []


def test_every_offered_language_is_a_terminological_code() -> None:
    assert all(terminological(code) == code for code in AUDIO_LANGUAGE_LABELS)
