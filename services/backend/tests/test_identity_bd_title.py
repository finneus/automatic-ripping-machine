from datetime import datetime, timezone

from arm_common import DiscType, Job, JobStatus
from arm_common.schemas import BdDiscMeta, ScanResult

from arm_backend.identity.sources.base import JobContext
from arm_backend.identity.sources.bd_title import BD_TITLE

NOW = datetime(2026, 9, 28, tzinfo=timezone.utc)


def _ctx(meta: BdDiscMeta | None, disc_type: DiscType = DiscType.BLURAY) -> JobContext:
    job = Job(id="job_1", drive_id="d", disc_type=disc_type, status=JobStatus.CREATED, metadata_json={})
    return JobContext(job=job, scan=ScanResult(disc_type=disc_type, bd_meta=meta), now=NOW)


def test_set_position_overrides_parsed_disc() -> None:
    claims = BD_TITLE.run(_ctx(BdDiscMeta(name="The West Wing Season 3 Disc 5", set_number=2, num_sets=6)))
    assert claims.job.model_dump(exclude_unset=True) == {
        "season": 3,
        "disc_number": 2,
        "disc_total": 6,
        "title": "the west wing",
    }


def test_placeholder_set_position_yields_to_the_disc_in_the_name() -> None:
    """Studios often stamp every disc of a box `1 of 1`. A disc number in the
    name above that total proves the set position is a placeholder, so the
    name's disc wins and the impossible total is dropped."""
    meta = BdDiscMeta(name="Suits: Season Seven\n(Disc 4)", language="eng", set_number=1, num_sets=1)
    claims = BD_TITLE.run(_ctx(meta))
    assert claims.job.model_dump(exclude_unset=True) == {"season": 7, "disc_number": 4, "title": "suits"}


def test_set_position_within_its_total_still_wins() -> None:
    claims = BD_TITLE.run(_ctx(BdDiscMeta(name="Show (Disc 2)", set_number=3, num_sets=4)))
    assert claims.job.model_dump(exclude_unset=True) == {"disc_number": 3, "disc_total": 4, "title": "show"}


def test_name_disc_above_total_without_set_number_keeps_the_meta_total_out() -> None:
    claims = BD_TITLE.run(_ctx(BdDiscMeta(name="Show (Disc 5)", num_sets=2)))
    assert claims.job.model_dump(exclude_unset=True) == {"disc_number": 5, "title": "show"}


def test_name_only() -> None:
    claims = BD_TITLE.run(_ctx(BdDiscMeta(name="Arrival")))
    assert claims.job.model_dump(exclude_unset=True) == {"title": "arrival"}
    assert claims.inputs == {"name": "Arrival"}


def test_skips_without_meta_or_on_dvd() -> None:
    assert BD_TITLE.applies_to(_ctx(None)) is not None
    assert BD_TITLE.applies_to(_ctx(BdDiscMeta(name="X"), DiscType.DVD)) is not None
    assert BD_TITLE.applies_to(_ctx(BdDiscMeta(name="X"))) is None


def test_bd_name_with_season_and_disc() -> None:
    claims = BD_TITLE.run(_ctx(BdDiscMeta(name="The West Wing: Season 3 Disc 2")))
    assert claims.job.model_dump(exclude_unset=True) == {
        "season": 3,
        "disc_number": 2,
        "title": "the west wing",
    }


def test_bd_name_with_empty_title() -> None:
    # A name that parses to an empty title (e.g. just whitespace or empty string)
    # should not include title in the job claims.
    claims = BD_TITLE.run(_ctx(BdDiscMeta(name="")))
    assert claims.job.model_dump(exclude_unset=True) == {}
    assert claims.inputs == {"name": ""}

    # Also test with just disc info and empty title
    claims = BD_TITLE.run(_ctx(BdDiscMeta(name="  ", set_number=2, num_sets=6)))
    assert claims.job.model_dump(exclude_unset=True) == {"disc_number": 2, "disc_total": 6}


def test_part_marker_only_keeps_disc_drops_title() -> None:
    """A BDMT disc title with a lone `P<n>` marker (one part of a single
    film) keeps the disc claim but must not propose a search title."""
    claims = BD_TITLE.run(_ctx(BdDiscMeta(name="Harry Potter Deathly Hallows P2")))
    assert claims.job.model_dump(exclude_unset=True) == {"disc_number": 2}
