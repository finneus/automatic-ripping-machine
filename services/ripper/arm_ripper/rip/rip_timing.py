"""Where a disc rip's time goes: opening the disc, writing each title, and the hash tail the job waits for.

One `_OpticalRip` pass feeds a `RipTiming` as it goes and logs it once at the end as a `rip.timing` event, so a slow
rip can be read from its job log: is the drive slow (MB/s), did it rip more than it needed (titles), or did the job
wait on something else (open time, hash tail)?
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_MB = 1_000_000
_GB = 1_000_000_000


@dataclass
class _Written:
    """One title's file as MakeMKV finished it."""

    title: int
    size_bytes: int
    at: float
    # Written while makemkvcon still ran (its own span is known), not settled after it exited.
    live: bool


@dataclass
class RipTiming:
    """The timestamps of one makemkvcon pass, on a monotonic clock."""

    clock: Callable[[], float] = time.monotonic
    started: float | None = None
    first_progress: float | None = None
    ripped: float | None = None
    hashed: float | None = None
    written: list[_Written] = field(default_factory=list)

    def start(self) -> None:
        """makemkvcon is about to run."""
        self.started = self.clock()

    def progressed(self) -> None:
        """MakeMKV reported progress: the first report marks the disc open and the write begun."""
        if self.first_progress is None:
            self.first_progress = self.clock()

    def title_written(self, title: int, size_bytes: int) -> None:
        """A title's file is complete. Before `finished`, it was written live and its own span is known."""
        self.written.append(_Written(title, size_bytes, self.clock(), live=self.ripped is None))

    def finished(self) -> None:
        """makemkvcon exited."""
        self.ripped = self.clock()

    def hashes_done(self) -> None:
        """Every written file is hashed: the job stops waiting on the rip."""
        self.hashed = self.clock()

    def summary(self) -> dict[str, Any] | None:
        """The pass as event fields; None until it started and finished."""
        if self.started is None or self.ripped is None:
            return None
        write_start = self.first_progress if self.first_progress is not None else self.started
        written_bytes = sum(w.size_bytes for w in self.written)
        write_seconds = self.ripped - write_start
        return {
            "open_seconds": _round(None if self.first_progress is None else self.first_progress - self.started),
            "rip_seconds": _round(self.ripped - self.started),
            "written_bytes": written_bytes,
            "mb_per_s": _rate(written_bytes, write_seconds),
            "hash_tail_seconds": _round(None if self.hashed is None else self.hashed - self.ripped),
            "titles": self._title_spans(write_start),
        }

    def _title_spans(self, write_start: float) -> list[dict[str, Any]]:
        """Each written title with the span since the previous one finished; a title settled after makemkvcon exited
        has no span of its own."""
        spans: list[dict[str, Any]] = []
        since = write_start
        for w in sorted(self.written, key=lambda w: w.at):
            seconds = w.at - since if w.live else None
            if w.live:
                since = w.at
            spans.append(
                {
                    "title": w.title,
                    "bytes": w.size_bytes,
                    "seconds": _round(seconds),
                    "mb_per_s": None if seconds is None else _rate(w.size_bytes, seconds),
                }
            )
        return spans

    def log(self) -> None:
        """Log the pass as one `rip.timing` event; nothing when it never ran to the end."""
        fields = self.summary()
        if fields is None:
            return
        logger.info("rip timing: %s", describe(fields), extra={"event": "rip.timing", **fields})


def describe(fields: dict[str, Any]) -> str:
    """The `rip.timing` fields in one readable line."""
    parts = []
    if fields["open_seconds"] is not None:
        parts.append(f"disc open after {fields['open_seconds']:.0f} s")
    parts.append(
        f"wrote {fields['written_bytes'] / _GB:.1f} GB in {fields['rip_seconds'] / 60:.1f} min"
        + ("" if fields["mb_per_s"] is None else f" ({fields['mb_per_s']:.1f} MB/s)")
    )
    for t in fields["titles"]:
        span = "" if t["seconds"] is None else f" in {t['seconds'] / 60:.1f} min ({t['mb_per_s']:.1f} MB/s)"
        parts.append(f"title {t['title']} {t['bytes'] / _GB:.1f} GB{span}")
    if fields["hash_tail_seconds"] is not None:
        parts.append(f"hash tail {fields['hash_tail_seconds'] / 60:.1f} min")
    return "; ".join(parts)


def _round(seconds: float | None) -> float | None:
    return None if seconds is None else round(seconds, 1)


def _rate(size_bytes: int, seconds: float) -> float | None:
    """MB/s; None when no time passed."""
    return round(size_bytes / seconds / _MB, 1) if seconds > 0 else None
