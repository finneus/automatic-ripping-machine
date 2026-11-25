"""Blu-ray titles that are only the bare clip of a playlist the scan also lists.

On some Blu-rays MakeMKV lists the main feature twice: as its playlist (`00801.mpls`) and as the clip that playlist
plays (`00294.m2ts`), byte for byte the same film without the chapter marks. A title is such a bare clip when its
source is an `.m2ts` whose clip id appears in the segment map of an `.mpls` title of the same scan.
"""

from arm_common.schemas import ScanTitle


def _clip_id(source_name: str | None) -> int | None:
    """The clip id of a bare-clip source (`00294.m2ts` -> 294), or None for a playlist or no source."""
    if not source_name or not source_name.lower().endswith(".m2ts"):
        return None
    stem = source_name[: -len(".m2ts")]
    return int(stem) if stem.isdigit() else None


def _playlist_clips(title: ScanTitle) -> set[int]:
    """The clip ids a playlist title plays; empty for anything that is not a playlist with a segment map."""
    if not title.source_name or not title.source_name.lower().endswith(".mpls") or not title.segment_map:
        return set()
    return {int(part) for part in title.segment_map.split(",") if part.strip().isdigit()}


def bare_clip_duplicates(titles: list[ScanTitle]) -> set[int]:
    """Indexes of the titles that are a bare clip of a listed playlist."""
    played: set[int] = set()
    for title in titles:
        played |= _playlist_clips(title)
    return {t.index for t in titles if (clip := _clip_id(t.source_name)) is not None and clip in played}
