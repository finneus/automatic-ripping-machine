"""pause_policy: the one rule for what the global pause does to a new job."""

import pytest
from arm_common import Config

from arm_backend.pause_policy import refuses_new_jobs


@pytest.mark.parametrize(
    ("paused", "hold", "refused"),
    [
        (False, False, False),
        (False, True, False),
        (True, True, False),
        (True, False, True),
    ],
)
def test_only_a_pause_without_the_review_hold_refuses_new_jobs(paused: bool, hold: bool, refused: bool) -> None:
    assert refuses_new_jobs(Config(id=1, ripping_paused=paused, hold_for_review=hold)) is refused


def test_no_config_row_refuses_nothing() -> None:
    assert refuses_new_jobs(None) is False
