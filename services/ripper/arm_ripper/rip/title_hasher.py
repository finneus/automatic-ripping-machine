"""SHA-256 of each ripped title, computed while makemkvcon writes the next.

`mkv all` finishes titles one at a time, so a title's file is final as soon
as its done event arrives. Hashing it then, one file at a time in a single
worker, overlaps the read with the rest of the rip; only the last title (or
whatever the worker has not reached yet) is left when makemkvcon exits.
`finish` waits for that remainder and reports it as a "verifying" pass, so
the job page shows progress instead of a silent re-read.

With `hash_files=False` (`ARM_HASH_TITLES=false`) every title is reported at
once with no digest: nothing reads the stored sha256, and on a lone title
(a main-feature rip) the re-read is minutes of waiting before the eject.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from arm_ripper.rip.hashing import sha256_file

logger = logging.getLogger("arm_ripper.rip.title_hasher")

# (bytes_done, bytes_total, rate_bps) for the files still being hashed.
OnVerifyProgress = Callable[[int, int, float | None], Awaitable[None]]
# Receives the digest, or None when the file could not be read.
OnHashed = Callable[[str | None], Awaitable[None]]

VERIFY_PROGRESS_INTERVAL_SECONDS = 1.0


class HashCancelled(Exception):
    """Raised in the hashing thread to stop it reading once `cancel` ran."""


def _transfer_rate(moved: int, elapsed: float) -> float | None:
    """Bytes per second over `elapsed` seconds; None until both time has passed and bytes have moved."""
    return moved / elapsed if elapsed > 0 and moved > 0 else None


class TitleHasher:
    def __init__(self, *, hash_files: bool = True) -> None:
        self._hash_files = hash_files
        self._lock = asyncio.Lock()
        self._tasks: list[asyncio.Task[None]] = []
        self._bytes_total = 0
        self._bytes_done = 0
        self._cancelled = threading.Event()

    def _on_bytes(self, n: int) -> None:
        # Called from the hashing thread; a lone int add is safe under the GIL
        # and the reader only needs an approximate figure.
        if self._cancelled.is_set():
            # Cancelling the task cannot stop a to_thread call; this stops the
            # thread at its next chunk instead of reading the file to the end.
            raise HashCancelled
        self._bytes_done += n

    def submit(self, path: Path, size: int, then: OnHashed) -> None:
        """Hash `path` in the background (when hashing is on), then await `then(digest)`."""
        if self._hash_files:
            self._bytes_total += size
        self._tasks.append(asyncio.create_task(self._run(path, then)))

    async def _run(self, path: Path, then: OnHashed) -> None:
        async with self._lock:
            digest = await self._digest(path) if self._hash_files else None
        await then(digest)

    async def _digest(self, path: Path) -> str | None:
        """The file's SHA-256, or None when it could not be read."""
        started = time.monotonic()
        try:
            digest = await sha256_file(path, self._on_bytes)
        except OSError as exc:
            logger.warning("sha256 of %s failed: %s", path.name, exc)
            return None
        logger.info("sha256 %s done in %.1fs", path.name, time.monotonic() - started)
        return digest

    async def finish(self, on_progress: OnVerifyProgress | None = None) -> None:
        """Wait for every submitted file, reporting progress while any remain."""
        pending = [t for t in self._tasks if not t.done()]
        if pending:
            logger.info("verifying %d ripped file(s) still being hashed", len(pending))
            gathered = asyncio.gather(*pending)
            done_at_start = self._bytes_done
            started = time.monotonic()
            while not gathered.done():
                if on_progress is not None:
                    rate = _transfer_rate(self._bytes_done - done_at_start, time.monotonic() - started)
                    await on_progress(self._bytes_done, self._bytes_total, rate)
                await asyncio.wait({gathered}, timeout=VERIFY_PROGRESS_INTERVAL_SECONDS)
        # Re-raise anything a `then` callback raised (a PATCH that gave up).
        await asyncio.gather(*self._tasks)

    def cancel(self) -> None:
        self._cancelled.set()
        for task in self._tasks:
            task.cancel()
