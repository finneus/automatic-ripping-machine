"""Parse `makemkvcon -r info` robot output into the volume label, titles and disc type."""

import re
from typing import Callable, Iterable, Literal

from arm_common import DiscType
from arm_common.languages import terminological
from arm_common.schemas import ScanStream, ScanTitle

_DURATION_RE = re.compile(r"^(\d+):(\d{1,2}):(\d{1,2})$")
_QUOTED_RE = re.compile(r'^"(.*)"$')


def _strip_quotes(value: str) -> str:
    m = _QUOTED_RE.match(value.strip())
    return m.group(1) if m else value.strip()


def _parse_duration(value: str) -> int | None:
    m = _DURATION_RE.match(value.strip())
    if not m:
        return None
    h, mn, s = (int(g) for g in m.groups())
    return h * 3600 + mn * 60 + s


def _to_int(value: str) -> int | None:
    """The value as an int, or None when it isn't one."""
    try:
        return int(value)
    except ValueError:
        return None


# SINFO attribute codes this parser reads: the stream type (its code field says which: 6202 is audio), the stream's
# ISO 639-2 language code, short codec name, video frame size, stream flags and audio channel layout.
_SINFO_TYPE = 1
_SINFO_LANGUAGE = 3
_SINFO_CODEC = 6
_SINFO_RESOLUTION = 19
_SINFO_FLAGS = 22
_SINFO_CHANNELS = 40
_AUDIO_STREAM = 6202
# Stream type code -> ScanStream kind; other types (none seen on discs) are skipped.
_STREAM_KINDS: dict[int, Literal["video", "audio", "subtitle"]] = {6201: "video", 6202: "audio", 6203: "subtitle"}
# Stream flag bits (MakeMKV's AP_AVStreamFlag_*): a commentary, an alternate commentary, a stream MakeMKV derives
# itself (the AC3 core of a TrueHD track) and a forced subtitle.
_FLAG_COMMENTARY = 1 | 2
_FLAG_DERIVED = 2048
_FLAG_FORCED = 4096
# Text-valued SINFO attributes kept as they are.
_SINFO_TEXT = (_SINFO_LANGUAGE, _SINFO_CODEC, _SINFO_RESOLUTION, _SINFO_FLAGS, _SINFO_CHANNELS)

# A title's streams: stream index -> {SINFO attribute code: value}.
_Streams = dict[int, dict[int, int | str]]


def _audio_languages(streams: _Streams) -> list[str]:
    """The title's audio languages as terminological codes, each once, in stream order."""
    out: list[str] = []
    for idx in sorted(streams):
        stream = streams[idx]
        language = stream.get(_SINFO_LANGUAGE)
        if stream.get(_SINFO_TYPE) == _AUDIO_STREAM and isinstance(language, str) and language:
            code = terminological(language)
            if code not in out:
                out.append(code)
    return out


def _stream_flags(value: int | str | None) -> int:
    """A stream's flag bits; 0 when MakeMKV reported none or something that is not a number."""
    if isinstance(value, int):
        return value
    try:
        return int(value or 0)
    except ValueError:
        return 0


def _stream_text(stream: dict[int, int | str], attr: int) -> str | None:
    """A text attribute of a stream, or None when it is missing or empty."""
    value = stream.get(attr)
    return value if isinstance(value, str) and value else None


def _scan_stream(stream: dict[int, int | str]) -> ScanStream | None:
    """One stream as a ScanStream; None for a stream of unknown type or one MakeMKV derives itself."""
    type_code = stream.get(_SINFO_TYPE)
    kind = _STREAM_KINDS.get(type_code) if isinstance(type_code, int) else None
    flags = _stream_flags(stream.get(_SINFO_FLAGS))
    if kind is None or flags & _FLAG_DERIVED:
        return None
    language = _stream_text(stream, _SINFO_LANGUAGE)
    return ScanStream(
        kind=kind,
        language=terminological(language) if language else None,
        codec=_stream_text(stream, _SINFO_CODEC),
        channels=_stream_text(stream, _SINFO_CHANNELS),
        resolution=_stream_text(stream, _SINFO_RESOLUTION),
        forced=bool(flags & _FLAG_FORCED),
        commentary=bool(flags & _FLAG_COMMENTARY),
    )


def _scan_streams(streams: _Streams) -> list[ScanStream]:
    """The title's streams in stream order (see `_scan_stream`)."""
    return [stream for idx in sorted(streams) if (stream := _scan_stream(streams[idx])) is not None]


def _to_language(value: str) -> str | None:
    """A language code MakeMKV reported, as its terminological ISO 639-2 form; None when empty."""
    return terminological(value) if value else None


# TINFO attribute code -> (title field, parser). A field is set only when its parser returns a value.
_TINFO_FIELDS: dict[int, tuple[str, Callable[[str], int | str | None]]] = {
    8: ("chapter_count", _to_int),
    9: ("duration_seconds", _parse_duration),
    11: ("size_bytes", _to_int),
    16: ("source_name", str),
    26: ("segment_map", str),
    27: ("source_file", str),
    28: ("metadata_language", _to_language),
    49: ("comment", str),
}


def _classify_from_cinfo(disc_type_text: str) -> DiscType | None:
    """Map MakeMKV's `CINFO:1` text value to our DiscType enum.

    Observed values vary across MakeMKV versions:
      - "DVD" (v1.17.x) and "DVD disc" (v1.18.x) for DVD-Video
      - "Blu-ray disc" for BD-Video
      - "Audio CD" for CDDA
      - "HD-DVD" / "HD DVD" for HD-DVD (no v3 enum yet — return None)
    Match HD-DVD before DVD because "hd-dvd" contains "dvd".
    """
    s = disc_type_text.strip().lower()
    if "blu-ray" in s or "bluray" in s or s == "bd":
        return DiscType.BLURAY
    if "hd-dvd" in s or "hd dvd" in s:
        return None
    if "dvd" in s:
        return DiscType.DVD
    if "audio cd" in s or s == "cd":
        return DiscType.CD
    return None


def _split_robot_line(raw: str) -> tuple[str, list[str]] | None:
    """A robot-mode line as (message type, stripped comma fields); None for a blank or colonless line."""
    line = raw.strip()
    if not line or ":" not in line:
        return None
    msg_type, _, rest = line.partition(":")
    return msg_type, [f.strip() for f in rest.split(",")]


def _scan_title(idx: int, entry: dict[str, object], streams: _Streams) -> ScanTitle | None:
    """The ScanTitle for one title's collected TINFO fields and SINFO streams; None when it has no duration."""
    duration_obj = entry.get("duration_seconds")
    if not isinstance(duration_obj, int):
        return None
    chapter_obj = entry.get("chapter_count")
    size_obj = entry.get("size_bytes")
    return ScanTitle(
        index=idx,
        duration_seconds=duration_obj,
        chapter_count=chapter_obj if isinstance(chapter_obj, int) else None,
        size_bytes=size_obj if isinstance(size_obj, int) else None,
        source_file=_text(entry, "source_file"),
        source_name=_text(entry, "source_name"),
        segment_map=_text(entry, "segment_map"),
        comment=_text(entry, "comment"),
        metadata_language=_text(entry, "metadata_language"),
        audio_languages=_audio_languages(streams),
        streams=_scan_streams(streams),
    )


def _text(entry: dict[str, object], name: str) -> str | None:
    """A collected text field of a title, or None when it was not reported."""
    value = entry.get(name)
    return value if isinstance(value, str) else None


class _InfoParser:
    """Accumulates the disc label, the disc type and each title's TINFO fields from robot-mode lines."""

    def __init__(self) -> None:
        self.volume_label: str | None = None
        self.mkv_disc_type: DiscType | None = None
        self.titles: dict[int, dict[str, object]] = {}
        self.streams: dict[int, _Streams] = {}

    def feed(self, raw: str) -> None:
        """Route one line to its handler; other lines are ignored."""
        split = _split_robot_line(raw)
        if split is None:
            return
        msg_type, fields = split
        if msg_type == "CINFO" and len(fields) >= 3:
            self.on_cinfo(fields)
        elif msg_type == "TINFO" and len(fields) >= 4:
            self.on_tinfo(fields)
        elif msg_type == "SINFO" and len(fields) >= 5:
            self.on_sinfo(fields)

    def on_cinfo(self, fields: list[str]) -> None:
        try:
            code = int(fields[0])
        except ValueError:
            return
        if code == 1 and self.mkv_disc_type is None:
            self.mkv_disc_type = _classify_from_cinfo(_strip_quotes(",".join(fields[2:])))
        elif code in (2, 30) and not self.volume_label:
            self.volume_label = _strip_quotes(",".join(fields[2:]))

    def on_tinfo(self, fields: list[str]) -> None:
        try:
            track_idx = int(fields[0])
            code = int(fields[1])
        except ValueError:
            return
        value = _strip_quotes(",".join(fields[3:]))
        entry = self.titles.setdefault(track_idx, {})
        field = _TINFO_FIELDS.get(code)
        if field is not None:
            name, parse = field
            field_value = parse(value)
            if field_value is not None:
                entry[name] = field_value

    def on_sinfo(self, fields: list[str]) -> None:
        """Keep a stream's type (the attribute's code field) and its `_SINFO_TEXT` attributes (their values); other
        attributes are skipped."""
        try:
            title_idx, stream_idx, attr, code = (int(f) for f in fields[:4])
        except ValueError:
            return
        if attr == _SINFO_TYPE:
            value: int | str = code
        elif attr in _SINFO_TEXT:
            value = _strip_quotes(",".join(fields[4:]))
        else:
            return
        self.streams.setdefault(title_idx, {}).setdefault(stream_idx, {})[attr] = value

    def scan_titles(self) -> list[ScanTitle]:
        """The titles with a duration, in index order."""
        return [
            title
            for idx in sorted(self.titles)
            if (title := _scan_title(idx, self.titles[idx], self.streams.get(idx, {}))) is not None
        ]


def parse_makemkvcon_info(
    lines: Iterable[str],
) -> tuple[str | None, list[ScanTitle], DiscType | None]:
    """Parse the robot-mode output of `makemkvcon -r info`.

    Returns (volume_label, titles, mkv_disc_type).

    MakeMKV codes used:
    - CINFO:1,...    — disc-type text ("DVD" / "Blu-ray disc" / "HD-DVD" /
                       "Audio CD") — authoritative signal regardless of
                       region-locks or kernel-mount failures
    - CINFO:2,...    — disc name (volume label)
    - CINFO:30,...   — disc tree info (sometimes the only place with the label)
    - TINFO:t,9,...  — title duration (HH:MM:SS)
    - TINFO:t,8,...  — chapter count
    - TINFO:t,11,... — title size in bytes
    - TINFO:t,27,... — source filename (e.g. title_t00.mkv)
    - SINFO:t,s,1,6202,... — stream s of title t is an audio stream
    - SINFO:t,s,3,...      — the stream's language code (`ger`, `eng`)

    Reference: https://github.com/automatic-ripping-machine/automatic-ripping-machine/wiki/MakeMKV-Codes
    """
    parser = _InfoParser()
    for raw in lines:
        parser.feed(raw)
    return parser.volume_label, parser.scan_titles(), parser.mkv_disc_type
