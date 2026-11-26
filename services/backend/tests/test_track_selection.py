"""Track-selection rule unit tests."""

import pytest

from arm_backend.track_selection import (
    ALL_TRACKS_MIN_SECONDS,
    MAKEMKV_MAIN_FEATURE_COMMENT,
    MAIN_FEATURE_MIN_SECONDS,
    MAIN_FEATURE_TIE_SECONDS,
    select_tracks,
    select_tracks_for_review,
)
from arm_common import (
    DiscType,
    IdentificationMode,
    MediaType,
    OutputMode,
    RipPreset,
    TrackKind,
    TrackSelection,
)
from arm_common.schemas import ScanResult, ScanTitle


def _preset(rule: TrackSelection) -> RipPreset:
    return RipPreset(
        id="rpr_test",
        name="test",
        media_type=MediaType.MOVIE,
        is_builtin=False,
        track_selection=rule,
        identification_mode=IdentificationMode.REQUIRED,
        output_mode=OutputMode.TRACKS,
    )


def _scan(*durations: int) -> ScanResult:
    return ScanResult(
        disc_type=DiscType.DVD,
        titles=[ScanTitle(index=i, duration_seconds=d) for i, d in enumerate(durations)],
    )


def test_archive_returns_every_title():
    scan = _scan(120, 90 * 60, 30, 60 * 60)
    tracks = select_tracks("job_01JZXR7K3M5Q8N4VWA00000001", scan, _preset(TrackSelection.ARCHIVE))
    assert [t.index for t in tracks] == [0, 1, 2, 3]
    assert all(t.kind == TrackKind.VIDEO_TITLE for t in tracks)


def test_all_tracks_filters_below_minimum():
    short = ALL_TRACKS_MIN_SECONDS - 1
    scan = _scan(short, ALL_TRACKS_MIN_SECONDS, 5 * 60, short)
    tracks = select_tracks("job_01JZXR7K3M5Q8N4VWA00000001", scan, _preset(TrackSelection.ALL_TRACKS))
    assert [t.index for t in tracks] == [1, 2]


def test_main_feature_returns_longest_above_threshold():
    scan = _scan(60 * 30, 90 * 60, 60 * 60, 45 * 60)
    tracks = select_tracks("job_01JZXR7K3M5Q8N4VWA00000001", scan, _preset(TrackSelection.MAIN_FEATURE))
    assert len(tracks) == 1
    assert tracks[0].index == 1
    assert tracks[0].expected_duration_seconds == 90 * 60


def test_main_feature_falls_back_to_longest_when_no_threshold_match():
    short = MAIN_FEATURE_MIN_SECONDS - 1
    scan = _scan(short, short - 100, short - 50)
    tracks = select_tracks("job_01JZXR7K3M5Q8N4VWA00000001", scan, _preset(TrackSelection.MAIN_FEATURE))
    assert len(tracks) == 1
    assert tracks[0].index == 0  # longest of the shorts
    assert tracks[0].expected_duration_seconds == short


def test_custom_without_filters_raises():
    from arm_backend.track_selection import TrackSelectionError

    with pytest.raises(TrackSelectionError):
        select_tracks("job_01JZXR7K3M5Q8N4VWA00000001", _scan(60), _preset(TrackSelection.CUSTOM))


def test_empty_scan_returns_empty():
    tracks = select_tracks("job_01JZXR7K3M5Q8N4VWA00000001", _scan(), _preset(TrackSelection.ARCHIVE))
    assert tracks == []


def test_data_disc_emits_single_dump():
    scan = ScanResult(disc_type=DiscType.DATA, volume_label="DATA_DISC")
    tracks = select_tracks("job_01JZXR7K3M5Q8N4VWA00000001", scan, _preset(TrackSelection.ALL_TRACKS))
    assert len(tracks) == 1
    assert tracks[0].kind == TrackKind.DATA_DUMP
    assert tracks[0].source_ref == "full"


def test_cd_emits_audio_tracks():
    scan = ScanResult(
        disc_type=DiscType.CD,
        titles=[ScanTitle(index=i, duration_seconds=180) for i in range(1, 4)],
    )
    tracks = select_tracks("job_01JZXR7K3M5Q8N4VWA00000001", scan, _preset(TrackSelection.ALL_TRACKS))
    assert [t.kind for t in tracks] == [TrackKind.AUDIO_TRACK] * 3
    assert [t.index for t in tracks] == [1, 2, 3]


# --- select_tracks_for_review (timed review gate: persist ALL, default excluded) ---


def test_review_persists_all_titles_with_main_feature_defaults():
    """MAIN_FEATURE keeps only the longest title; review persists ALL of them,
    marking the non-kept ones excluded by default."""
    scan = _scan(120, 90 * 60, 30, 60 * 60)  # indices 0..3; longest = index 1
    tracks = select_tracks_for_review("job_01JZXR7K3M5Q8N4VWA00000001", scan, _preset(TrackSelection.MAIN_FEATURE))
    assert [t.index for t in tracks] == [0, 1, 2, 3]  # every title persisted
    kept = {t.index for t in tracks if not t.excluded}
    assert kept == {1}  # only the longest is kept by default
    assert all(t.excluded for t in tracks if t.index != 1)


def test_review_archive_keeps_all_unexcluded():
    """ARCHIVE keeps every title -> none excluded by default."""
    scan = _scan(120, 5400, 30)
    tracks = select_tracks_for_review("job_01JZXR7K3M5Q8N4VWA00000001", scan, _preset(TrackSelection.ARCHIVE))
    assert len(tracks) == 3
    assert all(not t.excluded for t in tracks)


def test_review_all_tracks_excludes_below_minlength():
    """ALL_TRACKS drops titles under the min-length -> those persist excluded."""
    short = ALL_TRACKS_MIN_SECONDS - 1
    scan = _scan(short, 3600, short)
    tracks = select_tracks_for_review("job_01JZXR7K3M5Q8N4VWA00000001", scan, _preset(TrackSelection.ALL_TRACKS))
    assert len(tracks) == 3  # all persisted
    kept = {t.index for t in tracks if not t.excluded}
    assert kept == {1}  # only the above-threshold one kept by default


def test_review_data_disc_delegates_to_single_dump():
    scan = ScanResult(disc_type=DiscType.DATA, volume_label="DATA_DISC")
    tracks = select_tracks_for_review("job_01JZXR7K3M5Q8N4VWA00000001", scan, _preset(TrackSelection.ALL_TRACKS))
    assert len(tracks) == 1
    assert tracks[0].kind == TrackKind.DATA_DUMP


# --- ISO output mode: a full-disc dump whatever the disc holds ---


def _iso_preset() -> RipPreset:
    return RipPreset(
        id="rpr_builtin_iso_dump",
        name="ISO: Full-disc dump",
        media_type=MediaType.ISO,
        is_builtin=True,
        track_selection=TrackSelection.ALL_TRACKS,
        identification_mode=IdentificationMode.SKIP,
        output_mode=OutputMode.ISO,
    )


@pytest.mark.parametrize("disc_type", [DiscType.BLURAY, DiscType.DVD])
def test_iso_preset_dumps_a_video_disc_that_has_titles(disc_type: DiscType):
    """The ISO preset copies the disc whole. Titles in the scan must not turn
    it into a MakeMKV rip of those titles."""
    scan = ScanResult(
        disc_type=disc_type,
        titles=[ScanTitle(index=i, duration_seconds=d) for i, d in enumerate([7200, 1800, 300])],
    )
    tracks = select_tracks("job_01JZXR7K3M5Q8N4VWA00000001", scan, _iso_preset())
    assert [(t.kind, t.source_ref) for t in tracks] == [(TrackKind.DATA_DUMP, "full")]


def test_iso_preset_dumps_a_video_disc_without_titles():
    scan = ScanResult(disc_type=DiscType.BLURAY)
    tracks = select_tracks("job_01JZXR7K3M5Q8N4VWA00000001", scan, _iso_preset())
    assert [t.kind for t in tracks] == [TrackKind.DATA_DUMP]


def test_review_iso_preset_persists_the_single_dump():
    """The review gate shows the one dump, not every title marked excluded."""
    scan = _scan(7200, 1800)
    tracks = select_tracks_for_review("job_01JZXR7K3M5Q8N4VWA00000001", scan, _iso_preset())
    assert [(t.kind, t.excluded) for t in tracks] == [(TrackKind.DATA_DUMP, False)]


# --- FOLDER output mode: one decrypted-backup track, Blu-ray only ---


def _backup_preset() -> RipPreset:
    return RipPreset(
        id="rpr_builtin_bd_backup",
        name="Blu-ray: Decrypted backup",
        media_type=MediaType.ISO,
        is_builtin=True,
        track_selection=TrackSelection.ALL_TRACKS,
        identification_mode=IdentificationMode.SKIP,
        output_mode=OutputMode.FOLDER,
    )


def test_folder_preset_backs_up_a_bluray_with_titles():
    scan = ScanResult(
        disc_type=DiscType.BLURAY,
        titles=[ScanTitle(index=i, duration_seconds=d) for i, d in enumerate([7200, 1800])],
    )
    tracks = select_tracks("job_01JZXR7K3M5Q8N4VWA00000001", scan, _backup_preset())
    assert [(t.kind, t.index, t.source_ref) for t in tracks] == [(TrackKind.DISC_BACKUP, 0, "full")]


def test_folder_preset_backs_up_a_bluray_without_titles():
    """A backup copies the disc structure; it does not need MakeMKV's title list."""
    scan = ScanResult(disc_type=DiscType.BLURAY)
    tracks = select_tracks("job_01JZXR7K3M5Q8N4VWA00000001", scan, _backup_preset())
    assert [t.kind for t in tracks] == [TrackKind.DISC_BACKUP]


@pytest.mark.parametrize("disc_type", [DiscType.DVD, DiscType.DATA, DiscType.CD])
def test_folder_preset_refuses_anything_but_a_bluray(disc_type: DiscType):
    from arm_backend.track_selection import DiscBackupNeedsBluray

    scan = ScanResult(disc_type=disc_type, titles=[ScanTitle(index=1, duration_seconds=3600)])
    with pytest.raises(DiscBackupNeedsBluray, match=f"disc backup needs a Blu-ray, not disc_type={disc_type.value}"):
        select_tracks("job_01JZXR7K3M5Q8N4VWA00000001", scan, _backup_preset())


def test_review_folder_preset_persists_the_single_backup():
    scan = ScanResult(disc_type=DiscType.BLURAY, titles=[ScanTitle(index=0, duration_seconds=7200)])
    tracks = select_tracks_for_review("job_01JZXR7K3M5Q8N4VWA00000001", scan, _backup_preset())
    assert [(t.kind, t.excluded) for t in tracks] == [(TrackKind.DISC_BACKUP, False)]


# --- main feature among same-length variants (one per language group) ---------------------------------------------


def _variants(*titles: tuple[int, list[str], int]) -> ScanResult:
    """A Blu-ray whose titles are (duration, audio languages, size) in index order."""
    return ScanResult(
        disc_type=DiscType.BLURAY,
        titles=[
            ScanTitle(index=i, duration_seconds=d, audio_languages=langs, size_bytes=size)
            for i, (d, langs, size) in enumerate(titles)
        ],
    )


# Skyfall on UHD: the film three times at the same length.
_SKYFALL = _variants(
    (8590, ["eng", "jpn"], 56_000),
    (8590, ["eng", "ces", "deu", "fra", "hun", "ita", "pol", "spa"], 61_800),
    (8590, ["eng", "ces", "deu", "fra", "hun", "ita", "jpn", "pol", "spa"], 62_800),
)


def _main(scan: ScanResult, preferred: tuple[str, ...] = ()) -> str:
    tracks = select_tracks("job_01JZXR7K3M5Q8N4VWA00000001", scan, _preset(TrackSelection.MAIN_FEATURE), preferred)
    assert len(tracks) == 1
    return tracks[0].source_ref


def test_main_feature_prefers_the_variant_with_the_preferred_languages():
    scan = _variants((8590, ["eng", "jpn"], 63_000), (8590, ["deu", "eng"], 56_000), (8590, ["fra"], 70_000))
    assert _main(scan, ("deu", "eng")) == "1"


def test_main_feature_ranks_preferred_languages_in_order():
    scan = _variants((8590, ["eng"], 70_000), (8590, ["deu"], 50_000))
    assert _main(scan, ("deu", "eng")) == "1"


def test_main_feature_without_a_preference_takes_the_most_languages_then_the_largest():
    assert _main(_SKYFALL) == "2"
    same_languages = _variants((8590, ["deu", "eng"], 50_000), (8590, ["eng", "deu"], 60_000))
    assert _main(same_languages) == "1"


def test_main_feature_without_language_data_takes_the_largest_variant():
    assert _main(_variants((8590, [], 56_000), (8590, [], 62_800), (8590, [], 61_800))) == "1"


def test_main_feature_full_tie_keeps_the_first_title():
    assert _main(_variants((8590, ["eng"], 100), (8590, ["eng"], 100))) == "0"


def _localised(*languages: str | None) -> ScanResult:
    """A Blu-ray with the film once per language, same audio and size, told apart only by the title language: the
    Star Wars UHDs carry four such playlists (opening text and credits in English, French, German, Italian)."""
    return ScanResult(
        disc_type=DiscType.BLURAY,
        titles=[
            ScanTitle(
                index=i,
                duration_seconds=8407,
                audio_languages=["eng", "fra", "deu", "ita"],
                size_bytes=56_000,
                metadata_language=lang,
            )
            for i, lang in enumerate(languages)
        ],
    )


def test_main_feature_picks_the_variant_whose_title_language_is_preferred():
    scan = _localised("fra", "ita", "deu", "eng")
    assert _main(scan, ("deu", "eng")) == "2"
    assert _main(scan, ("eng", "deu")) == "3"


def test_main_feature_title_language_falls_through_the_preference_order():
    assert _main(_localised("fra", "eng", None), ("deu", "eng")) == "1"


def test_main_feature_title_language_never_outweighs_the_audio_languages():
    """A variant with a preferred audio language beats one that only carries a preferred title language."""
    scan = ScanResult(
        disc_type=DiscType.BLURAY,
        titles=[
            ScanTitle(index=0, duration_seconds=8407, audio_languages=["eng"], size_bytes=1, metadata_language="deu"),
            ScanTitle(index=1, duration_seconds=8407, audio_languages=["deu"], size_bytes=1, metadata_language="eng"),
        ],
    )
    assert _main(scan, ("deu", "eng")) == "1"


def test_main_feature_without_a_preference_ignores_the_title_language():
    assert _main(_localised("fra", "deu")) == "0"


def test_main_feature_variant_window_is_measured_from_the_longest_title():
    near = 9000 - MAIN_FEATURE_TIE_SECONDS
    far = 9000 - MAIN_FEATURE_TIE_SECONDS - 1
    assert _main(_variants((9000, ["eng"], 10), (near, ["deu", "eng"], 10)), ("deu",)) == "1"
    assert _main(_variants((9000, ["eng"], 10), (far, ["deu", "eng"], 10)), ("deu",)) == "0"


def test_review_keeps_the_preferred_variant_and_excludes_the_others():
    tracks = select_tracks_for_review(
        "job_01JZXR7K3M5Q8N4VWA00000001", _SKYFALL, _preset(TrackSelection.MAIN_FEATURE), ("deu", "eng")
    )
    assert [t.excluded for t in tracks] == [True, True, False]


def _bluray(*titles: tuple[int, str, str | None]) -> ScanResult:
    """(minutes, source, segment map) per title, in index order."""
    return ScanResult(
        disc_type=DiscType.BLURAY,
        titles=[
            ScanTitle(index=i, duration_seconds=m * 60, source_name=src, segment_map=seg)
            for i, (m, src, seg) in enumerate(titles)
        ],
    )


def test_main_feature_never_picks_the_bare_clip_of_a_listed_playlist():
    """#693: the clip is listed first and as long as the playlist, but the playlist carries the chapters."""
    scan = _bluray((127, "00294.m2ts", None), (127, "00801.mpls", "294"), (2, "01167.mpls", "582"))
    tracks = select_tracks("job_01JZXR7K3M5Q8N4VWA00000001", scan, _preset(TrackSelection.MAIN_FEATURE))
    assert [t.index for t in tracks] == [1]


def test_main_feature_falls_back_to_the_clips_when_every_title_is_one():
    scan = _bluray((127, "00294.m2ts", None), (127, "00294.m2ts", None))
    # No playlist plays them, so neither is a duplicate; the first longest wins as before.
    tracks = select_tracks("job_01JZXR7K3M5Q8N4VWA00000001", scan, _preset(TrackSelection.MAIN_FEATURE))
    assert [t.index for t in tracks] == [0]


def test_all_tracks_keeps_bare_clips_so_files_still_pair_with_titles():
    scan = _bluray((127, "00801.mpls", "294"), (127, "00294.m2ts", None))
    tracks = select_tracks("job_01JZXR7K3M5Q8N4VWA00000001", scan, _preset(TrackSelection.ALL_TRACKS))
    assert [t.index for t in tracks] == [0, 1]


def test_review_starts_bare_clips_excluded():
    scan = _bluray((127, "00801.mpls", "294"), (127, "00294.m2ts", None), (5, "00300.mpls", "300"))
    rows = select_tracks_for_review("job_01JZXR7K3M5Q8N4VWA00000001", scan, _preset(TrackSelection.ALL_TRACKS))
    assert [(r.index, r.excluded) for r in rows] == [(0, False), (1, True), (2, False)]


def _commented(*titles: tuple[int, str | None]) -> ScanResult:
    """(minutes, MakeMKV comment) per title, in index order."""
    return ScanResult(
        disc_type=DiscType.BLURAY,
        titles=[ScanTitle(index=i, duration_seconds=m * 60, comment=c) for i, (m, c) in enumerate(titles)],
    )


def test_main_feature_takes_the_title_makemkv_marks_over_a_longer_decoy():
    """A decoy playlist runs longer than the film; MakeMKV's `FPL_MainFeature` comment names the film."""
    scan = _commented((130, None), (121, MAKEMKV_MAIN_FEATURE_COMMENT), (131, None))
    assert _main(scan) == "1"


def test_main_feature_ranks_several_marked_titles_by_the_usual_rule():
    scan = _commented((121, MAKEMKV_MAIN_FEATURE_COMMENT), (140, None), (123, MAKEMKV_MAIN_FEATURE_COMMENT))
    assert _main(scan) == "2"


def test_main_feature_ignores_other_makemkv_comments():
    scan = _commented((121, "SF_Trailer"), (130, None))
    assert _main(scan) == "1"


def test_review_excludes_the_decoys_next_to_the_marked_title():
    scan = _commented((130, None), (121, MAKEMKV_MAIN_FEATURE_COMMENT))
    rows = select_tracks_for_review("job_01JZXR7K3M5Q8N4VWA00000001", scan, _preset(TrackSelection.MAIN_FEATURE))
    assert [(r.index, r.excluded) for r in rows] == [(0, True), (1, False)]
