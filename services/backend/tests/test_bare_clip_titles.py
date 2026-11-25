"""Bare-clip duplicates of listed playlists (#693)."""

from arm_backend.bare_clip_titles import bare_clip_duplicates
from arm_common.schemas import ScanTitle


def _title(index: int, source: str | None, segments: str | None = None, minutes: int = 120) -> ScanTitle:
    return ScanTitle(index=index, duration_seconds=minutes * 60, source_name=source, segment_map=segments)


def test_the_issue_disc_drops_both_bare_clips():
    """Indiana Jones and the Last Crusade (UHD): the feature and one extra clip appear twice."""
    titles = [
        _title(0, "00801.mpls", "294"),
        _title(1, "01167.mpls", "582,580", minutes=2),
        _title(2, "00294.m2ts", minutes=126),
        _title(3, "00580.m2ts", minutes=2),
    ]
    assert bare_clip_duplicates(titles) == {2, 3}


def test_a_clip_no_listed_playlist_plays_is_kept():
    assert bare_clip_duplicates([_title(0, "00801.mpls", "294"), _title(1, "00300.m2ts")]) == set()


def test_titles_without_sources_have_no_duplicates():
    assert bare_clip_duplicates([_title(0, None), _title(1, None)]) == set()


def test_odd_names_and_segment_maps_are_ignored():
    titles = [
        _title(0, "00801.mpls", "x, 12 ,"),  # only 12 is a clip id
        _title(1, "00801.mpls"),  # a playlist without a segment map plays nothing we can read
        _title(2, "abc.m2ts"),  # no numeric clip id
        _title(3, "00012.M2TS"),  # case does not matter
        _title(4, "title_t00.mkv"),
    ]
    assert bare_clip_duplicates(titles) == {3}
