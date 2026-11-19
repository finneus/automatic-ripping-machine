from collections.abc import Sequence

from arm_common import TrackStatus, DiscType, OutputMode, RipPreset, Track, TrackKind, TrackSelection
from arm_common.schemas import ScanResult, ScanTitle, TrackFilters

MAIN_FEATURE_MIN_SECONDS = 45 * 60
# Titles this close to the longest are variants of the film: a UHD can carry it once per language group.
MAIN_FEATURE_TIE_SECONDS = 60
ALL_TRACKS_MIN_SECONDS = 60


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


def _variant_rank(title: ScanTitle, preferred: Sequence[str]) -> tuple[tuple[bool, ...], int, int]:
    """How well one variant of the film fits: which preferred audio languages it has (in preference order), then how
    many audio languages it has, then its size (the variant with every language group is the largest)."""
    languages = set(title.audio_languages)
    return tuple(lang in languages for lang in preferred), len(languages), title.size_bytes or 0


def _main_feature(titles: list[ScanTitle], preferred: Sequence[str]) -> ScanTitle:
    """The main feature: among the titles within `MAIN_FEATURE_TIE_SECONDS` of the longest one (that runs at least
    `MAIN_FEATURE_MIN_SECONDS` when any does), the best `_variant_rank`; on a full tie the lowest index."""
    eligible = [t for t in titles if t.duration_seconds >= MAIN_FEATURE_MIN_SECONDS] or titles
    longest = max(t.duration_seconds for t in eligible)
    variants = [t for t in eligible if longest - t.duration_seconds <= MAIN_FEATURE_TIE_SECONDS]
    return max(variants, key=lambda t: _variant_rank(t, preferred))


def _select_video(scan: ScanResult, rip_preset: RipPreset, job_id: str, preferred: Sequence[str]) -> list[Track]:
    titles = scan.titles
    if not titles:
        return []
    rule = rip_preset.track_selection
    if rule == TrackSelection.MAIN_FEATURE:
        return [_video_track(job_id, _main_feature(titles, preferred))]
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
    job_id: str, scan: ScanResult, rip_preset: RipPreset, preferred_audio_languages: Sequence[str] = ()
) -> list[Track]:
    """Apply rip-preset track-selection rules to a scan. `preferred_audio_languages` (terminological codes, in
    order) picks the main feature among same-length variants of the film."""
    whole = _whole_disc_tracks(job_id, scan, rip_preset)
    if whole is not None:
        return whole
    if scan.disc_type in (DiscType.DVD, DiscType.BLURAY):
        return _select_video(scan, rip_preset, job_id, preferred_audio_languages)
    if scan.disc_type == DiscType.CD:
        return _select_audio(scan, rip_preset, job_id)
    raise TrackSelectionError(f"cannot select tracks for disc_type={scan.disc_type}")


def select_tracks_for_review(
    job_id: str, scan: ScanResult, rip_preset: RipPreset, preferred_audio_languages: Sequence[str] = ()
) -> list[Track]:
    """Persist EVERY scanned title as a Track for the timed review gate, marking
    preset-rejected titles `excluded=True` (the default keep/drop set) so the
    review UI shows the full title list and the operator can re-enable any.

    Differs from `select_tracks` (which returns only the preset's subset): here
    the preset computes *defaults*, not membership. The kept set is whatever
    `select_tracks` would have produced, matched by `source_ref`. (spec §4.3)

    A whole-disc track (a DATA disc, the ISO dump, the FOLDER backup) has no
    per-title list: review persistence is the single track `select_tracks` makes.
    """
    whole = _whole_disc_tracks(job_id, scan, rip_preset)
    if whole is not None:
        return whole

    kept_refs = {t.source_ref for t in select_tracks(job_id, scan, rip_preset, preferred_audio_languages)}
    is_cd = scan.disc_type == DiscType.CD
    rows: list[Track] = []
    for title in scan.titles:
        track = _audio_track(job_id, title) if is_cd else _video_track(job_id, title)
        track.excluded = str(title.index) not in kept_refs
        rows.append(track)
    return rows
