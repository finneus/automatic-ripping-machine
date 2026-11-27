from collections.abc import Sequence, Set

from arm_backend.bare_clip_titles import bare_clip_duplicates
from arm_common import TrackStatus, DiscType, OutputMode, RipPreset, Track, TrackKind, TrackSelection
from arm_common.schemas import ScanResult, ScanTitle, TrackFilters

MAIN_FEATURE_MIN_SECONDS = 45 * 60
# Titles this close to the longest are variants of the film: a UHD can carry it once per language group.
MAIN_FEATURE_TIE_SECONDS = 60
ALL_TRACKS_MIN_SECONDS = 60
# MakeMKV's comment on the film of a disc whose decoy playlists it sorted out (it needs the disc's Java for that).
MAKEMKV_MAIN_FEATURE_COMMENT = "FPL_MainFeature"


class TrackSelectionError(ValueError):
    pass


def _video_track(job_id: str, title: ScanTitle) -> Track:
    return Track(
        job_id=job_id,
        kind=TrackKind.VIDEO_TITLE,
        index=title.index,
        source_ref=str(title.index),
        expected_duration_seconds=title.duration_seconds,
        expected_size_bytes=title.size_bytes,
    )


def _audio_track(job_id: str, title: ScanTitle) -> Track:
    return Track(
        job_id=job_id,
        kind=TrackKind.AUDIO_TRACK,
        index=title.index,
        source_ref=str(title.index),
        expected_duration_seconds=title.duration_seconds,
        expected_size_bytes=title.size_bytes,
    )


def _parse_filters(rip_preset: RipPreset) -> TrackFilters:
    """Materialise `track_filters_json` as a typed `TrackFilters`.

    Raises if the preset says CUSTOM but has no filters configured — that
    combination is a save-time bug we surface loudly rather than silently
    selecting nothing.
    """
    if rip_preset.track_filters_json is None:
        raise TrackSelectionError(
            f"rip_preset {rip_preset.id} declares CUSTOM track_selection but has no track_filters_json"
        )
    return TrackFilters.model_validate(rip_preset.track_filters_json)


def _apply_custom_filters(titles: list[ScanTitle], filters: TrackFilters) -> list[ScanTitle]:
    """AND-of-conditions filter. `title_indices` (allowlist) restricts first; min/max + exclude apply after."""
    candidates = titles
    if filters.title_indices is not None:
        allow = set(filters.title_indices)
        candidates = [t for t in candidates if t.index in allow]
    if filters.title_indices_exclude is not None:
        deny = set(filters.title_indices_exclude)
        candidates = [t for t in candidates if t.index not in deny]
    if filters.min_duration_seconds is not None:
        threshold = filters.min_duration_seconds
        candidates = [t for t in candidates if t.duration_seconds >= threshold]
    if filters.max_duration_seconds is not None:
        ceiling = filters.max_duration_seconds
        candidates = [t for t in candidates if t.duration_seconds <= ceiling]
    return candidates


def _variant_rank(title: ScanTitle, preferred: Sequence[str]) -> tuple[tuple[bool, ...], tuple[bool, ...], int, int]:
    """How well one variant of the film fits: which preferred audio languages it has (in preference order), then
    whether its MakeMKV title language is a preferred one (in the same order; it tells apart the variants that share
    their audio but differ in opening text and credits), then how many audio languages it has, then its size (the
    variant with every language group is the largest)."""
    languages = set(title.audio_languages)
    audio = tuple(lang in languages for lang in preferred)
    metadata = tuple(title.metadata_language == lang for lang in preferred)
    return audio, metadata, len(languages), title.size_bytes or 0


def _main_feature(titles: list[ScanTitle], preferred: Sequence[str], reference: Set[str] = frozenset()) -> ScanTitle:
    """The main feature: among the titles within `MAIN_FEATURE_TIE_SECONDS` of the longest one (that runs at least
    `MAIN_FEATURE_MIN_SECONDS` when any does), the best `_variant_rank`; on a full tie the lowest index. A bare clip
    of a listed playlist is never picked while the playlist is there: same film, but without its chapters. When
    MakeMKV comments a title `MAKEMKV_MAIN_FEATURE_COMMENT`, only such titles are candidates: a decoy playlist can be
    the longest title on the disc. When a variant plays the clips TheDiscDB marks the film's main movie (`reference`,
    segment maps), only such variants are candidates: the others carry a translated opening and credits."""
    return max(_main_feature_candidates(titles, reference), key=lambda t: _variant_rank(t, preferred))


def _main_feature_candidates(titles: list[ScanTitle], reference: Set[str]) -> list[ScanTitle]:
    """The same-length variants of the film `_main_feature` ranks (see there for which titles they are)."""
    duplicates = bare_clip_duplicates(titles)
    pool = [t for t in titles if t.index not in duplicates] or titles
    pool = [t for t in pool if t.comment == MAKEMKV_MAIN_FEATURE_COMMENT] or pool
    eligible = [t for t in pool if t.duration_seconds >= MAIN_FEATURE_MIN_SECONDS] or pool
    longest = max(t.duration_seconds for t in eligible)
    variants = [t for t in eligible if longest - t.duration_seconds <= MAIN_FEATURE_TIE_SECONDS]
    return [t for t in variants if t.segment_map in reference] or variants


def _evidence(title: ScanTitle, preferred: Sequence[str]) -> tuple[tuple[bool, ...], tuple[bool, ...], int]:
    """`_variant_rank` without the size: a few bytes more (a longer translated opening) say nothing about which
    variant is the original."""
    audio, metadata, count, _size = _variant_rank(title, preferred)
    return audio, metadata, count


def main_feature_guess(
    scan: ScanResult, rip_preset: RipPreset, preferred: Sequence[str] = (), reference: Set[str] = frozenset()
) -> list[ScanTitle]:
    """The variants a main-feature pick could only guess between: two or more same-length titles that tie on
    everything that tells variants apart (TheDiscDB's main movie, MakeMKV's comment, audio and title languages), so
    size or index decided. Empty when the pick had evidence, or the preset does not pick a main feature."""
    if rip_preset.track_selection != TrackSelection.MAIN_FEATURE or scan.disc_type not in (
        DiscType.DVD,
        DiscType.BLURAY,
    ):
        return []
    if not scan.titles:
        return []
    candidates = _main_feature_candidates(scan.titles, reference)
    best = max(_evidence(t, preferred) for t in candidates)
    tied = [t for t in candidates if _evidence(t, preferred) == best]
    return tied if len(tied) > 1 else []


def _select_video(
    scan: ScanResult, rip_preset: RipPreset, job_id: str, preferred: Sequence[str], reference: Set[str]
) -> list[Track]:
    titles = scan.titles
    if not titles:
        return []
    rule = rip_preset.track_selection
    if rule == TrackSelection.MAIN_FEATURE:
        return [_video_track(job_id, _main_feature(titles, preferred, reference))]
    if rule == TrackSelection.ALL_TRACKS:
        return [_video_track(job_id, t) for t in titles if t.duration_seconds >= ALL_TRACKS_MIN_SECONDS]
    if rule == TrackSelection.ARCHIVE:
        return [_video_track(job_id, t) for t in titles]
    if rule == TrackSelection.CUSTOM:
        filters = _parse_filters(rip_preset)
        return [_video_track(job_id, t) for t in _apply_custom_filters(titles, filters)]
    # Unreachable: TrackSelection enum is exhaustively handled above.
    raise TrackSelectionError(f"unknown track_selection: {rule}")  # pragma: no cover


def _select_audio(scan: ScanResult, rip_preset: RipPreset, job_id: str) -> list[Track]:
    rule = rip_preset.track_selection
    if rule == TrackSelection.CUSTOM:
        filters = _parse_filters(rip_preset)
        return [_audio_track(job_id, t) for t in _apply_custom_filters(scan.titles, filters)]
    return [_audio_track(job_id, t) for t in scan.titles]


class DiscBackupNeedsBluray(TrackSelectionError):
    """A FOLDER (decrypted backup) preset was applied to a disc that is not a Blu-ray."""


def _whole_disc_track(job_id: str, kind: TrackKind) -> Track:
    return Track(
        job_id=job_id,
        kind=kind,
        index=0,
        source_ref="full",
        status=TrackStatus.QUEUED,
        attempts=0,
    )


def _dumps_whole_disc(scan: ScanResult, rip_preset: RipPreset) -> bool:
    """A DATA disc has no titles, and an ISO preset copies a DVD or Blu-ray
    whole whatever titles the scan found: both are one full-disc dump."""
    if scan.disc_type == DiscType.DATA:
        return True
    return rip_preset.output_mode == OutputMode.ISO and scan.disc_type in (DiscType.DVD, DiscType.BLURAY)


def _whole_disc_tracks(job_id: str, scan: ScanResult, rip_preset: RipPreset) -> list[Track] | None:
    """The single track for a preset that takes the disc whole, or None when
    the preset selects titles. A FOLDER preset backs up a Blu-ray and refuses
    any other disc."""
    if rip_preset.output_mode == OutputMode.FOLDER:
        if scan.disc_type != DiscType.BLURAY:
            raise DiscBackupNeedsBluray(f"disc backup needs a Blu-ray, not disc_type={scan.disc_type.value}")
        return [_whole_disc_track(job_id, TrackKind.DISC_BACKUP)]
    if _dumps_whole_disc(scan, rip_preset):
        return [_whole_disc_track(job_id, TrackKind.DATA_DUMP)]
    return None


def select_tracks(
    job_id: str,
    scan: ScanResult,
    rip_preset: RipPreset,
    preferred_audio_languages: Sequence[str] = (),
    reference_segment_maps: Set[str] = frozenset(),
) -> list[Track]:
    """Apply rip-preset track-selection rules to a scan. `reference_segment_maps` (TheDiscDB's main movie of the
    film) and then `preferred_audio_languages` (terminological codes, in order) pick the main feature among
    same-length variants of the film."""
    whole = _whole_disc_tracks(job_id, scan, rip_preset)
    if whole is not None:
        return whole
    if scan.disc_type in (DiscType.DVD, DiscType.BLURAY):
        return _select_video(scan, rip_preset, job_id, preferred_audio_languages, reference_segment_maps)
    if scan.disc_type == DiscType.CD:
        return _select_audio(scan, rip_preset, job_id)
    raise TrackSelectionError(f"cannot select tracks for disc_type={scan.disc_type}")


def select_tracks_for_review(
    job_id: str,
    scan: ScanResult,
    rip_preset: RipPreset,
    preferred_audio_languages: Sequence[str] = (),
    reference_segment_maps: Set[str] = frozenset(),
) -> list[Track]:
    """Persist EVERY scanned title as a Track for the timed review gate, marking
    preset-rejected titles `excluded=True` (the default keep/drop set) so the
    review UI shows the full title list and the operator can re-enable any.

    Differs from `select_tracks` (which returns only the preset's subset): here
    the preset computes *defaults*, not membership. The kept set is whatever
    `select_tracks` would have produced, matched by `source_ref`.

    A whole-disc track (a DATA disc, the ISO dump, the FOLDER backup) has no
    per-title list: review persistence is the single track `select_tracks` makes.
    """
    whole = _whole_disc_tracks(job_id, scan, rip_preset)
    if whole is not None:
        return whole

    kept = select_tracks(job_id, scan, rip_preset, preferred_audio_languages, reference_segment_maps)
    kept_refs = {t.source_ref for t in kept}
    # A bare clip of a listed playlist starts excluded: every title is persisted here, so dropping it from the
    # default set cannot shift which file belongs to which title.
    duplicates = bare_clip_duplicates(scan.titles)
    is_cd = scan.disc_type == DiscType.CD
    rows: list[Track] = []
    for title in scan.titles:
        track = _audio_track(job_id, title) if is_cd else _video_track(job_id, title)
        track.excluded = str(title.index) not in kept_refs or title.index in duplicates
        rows.append(track)
    return rows
