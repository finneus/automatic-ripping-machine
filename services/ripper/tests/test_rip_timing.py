"""rip_timing: where a disc rip's time goes, logged once per makemkvcon pass as a `rip.timing` event."""

import logging

from arm_ripper.rip.rip_timing import RipTiming, describe


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _two_title_pass() -> tuple[RipTiming, _Clock]:
    """Disc open after 20 s, a 46 GB title after 30 min, a 4 GB extra 3 min later, the hash done 2.5 min after."""
    clock = _Clock()
    timing = RipTiming(clock=clock)
    timing.start()
    clock.now += 20
    timing.progressed()
    clock.now += 1800
    timing.progressed()
    timing.title_written(0, 46_000_000_000)
    clock.now += 180
    timing.title_written(3, 4_000_000_000)
    timing.finished()
    clock.now += 150
    timing.hashes_done()
    return timing, clock


def test_summary_splits_the_pass_into_open_write_and_hash_tail():
    timing, _clock = _two_title_pass()
    assert timing.summary() == {
        "open_seconds": 20.0,
        "rip_seconds": 2000.0,
        "written_bytes": 50_000_000_000,
        "mb_per_s": 25.3,
        "hash_tail_seconds": 150.0,
        "titles": [
            {"title": 0, "bytes": 46_000_000_000, "seconds": 1800.0, "mb_per_s": 25.6},
            {"title": 3, "bytes": 4_000_000_000, "seconds": 180.0, "mb_per_s": 22.2},
        ],
    }


def test_a_title_settled_after_makemkvcon_exited_has_no_span_of_its_own():
    clock = _Clock()
    timing = RipTiming(clock=clock)
    timing.start()
    clock.now += 600
    timing.finished()
    timing.title_written(2, 6_000_000_000)
    fields = timing.summary()
    assert fields is not None
    assert fields["open_seconds"] is None
    assert fields["mb_per_s"] == 10.0
    assert fields["hash_tail_seconds"] is None
    assert fields["titles"] == [{"title": 2, "bytes": 6_000_000_000, "seconds": None, "mb_per_s": None}]


def test_no_summary_before_the_pass_ran_to_the_end():
    timing = RipTiming(clock=_Clock())
    assert timing.summary() is None
    timing.start()
    assert timing.summary() is None


def test_a_pass_that_took_no_time_has_no_rate():
    timing = RipTiming(clock=_Clock())
    timing.start()
    timing.progressed()
    timing.title_written(0, 10)
    timing.finished()
    fields = timing.summary()
    assert fields is not None
    assert fields["mb_per_s"] is None
    assert fields["titles"][0]["mb_per_s"] is None


def test_describe_reads_as_one_line():
    timing, _clock = _two_title_pass()
    fields = timing.summary()
    assert fields is not None
    assert describe(fields) == (
        "disc open after 20 s; wrote 50.0 GB in 33.3 min (25.3 MB/s); title 0 46.0 GB in 30.0 min (25.6 MB/s); "
        "title 3 4.0 GB in 3.0 min (22.2 MB/s); hash tail 2.5 min"
    )


def test_describe_leaves_out_what_was_not_measured():
    fields = {
        "open_seconds": None,
        "rip_seconds": 0.0,
        "written_bytes": 0,
        "mb_per_s": None,
        "hash_tail_seconds": None,
        "titles": [{"title": 1, "bytes": 2_000_000_000, "seconds": None, "mb_per_s": None}],
    }
    assert describe(fields) == "wrote 0.0 GB in 0.0 min; title 1 2.0 GB"


def test_log_emits_one_rip_timing_event_with_the_fields(caplog):
    timing, _clock = _two_title_pass()
    with caplog.at_level(logging.INFO, logger="arm_ripper.rip.rip_timing"):
        timing.log()
    [record] = [r for r in caplog.records if getattr(r, "event", None) == "rip.timing"]
    assert record.getMessage().startswith("rip timing: disc open after 20 s")
    assert record.hash_tail_seconds == 150.0
    assert [t["title"] for t in record.titles] == [0, 3]


def test_log_says_nothing_for_a_pass_that_never_finished(caplog):
    timing = RipTiming(clock=_Clock())
    timing.start()
    with caplog.at_level(logging.INFO, logger="arm_ripper.rip.rip_timing"):
        timing.log()
    assert caplog.records == []
