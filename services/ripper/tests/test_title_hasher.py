"""TitleHasher: hashing ripped titles while the rip continues (D-125)."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from arm_ripper.rip import hashing
from arm_ripper.rip.title_hasher import TitleHasher, _transfer_rate


def test_transfer_rate_is_bytes_per_second() -> None:
    assert _transfer_rate(100, 2.0) == 50.0


def test_transfer_rate_is_none_when_no_bytes_moved() -> None:
    assert _transfer_rate(0, 2.0) is None


def test_transfer_rate_is_none_when_no_time_has_passed() -> None:
    assert _transfer_rate(100, 0.0) is None


def test_transfer_rate_is_none_for_a_negative_elapsed() -> None:
    assert _transfer_rate(100, -1.0) is None


async def test_cancel_stops_the_hashing_thread_mid_file(tmp_path: Path, monkeypatch) -> None:
    """D-125 follow-up: cancelling the task cannot stop asyncio.to_thread, so
    the thread itself must stop reading; a wiped raw dir's file must not be
    read to the end at full disk bandwidth."""
    monkeypatch.setattr(hashing, "_CHUNK", 1)
    path = tmp_path / "t00.mkv"
    path.write_bytes(b"x" * 10_000)
    hasher = TitleHasher()
    first_chunk, release = threading.Event(), threading.Event()
    chunks = 0
    real_on_bytes = hasher._on_bytes

    def on_bytes(n: int) -> None:
        nonlocal chunks
        chunks += 1
        if chunks == 1:
            first_chunk.set()
            release.wait(5)
        real_on_bytes(n)

    hasher._on_bytes = on_bytes  # type: ignore[method-assign]

    async def then(digest: str | None) -> None:
        raise AssertionError("a cancelled hash must not report a digest")

    hasher.submit(path, 10_000, then)
    while not first_chunk.is_set():
        await asyncio.sleep(0.01)
    hasher.cancel()
    release.set()
    await asyncio.sleep(0.3)
    assert chunks <= 2


async def test_hashing_off_reports_each_title_at_once_without_reading_it(tmp_path: Path, monkeypatch) -> None:
    """ARM_HASH_TITLES=false: no re-read; each title gets None and finish has nothing left to verify."""
    import arm_ripper.rip.title_hasher as title_hasher

    async def must_not_hash(*_a, **_k):
        raise AssertionError("hashing is off")

    monkeypatch.setattr(title_hasher, "sha256_file", must_not_hash)
    hasher = TitleHasher(hash_files=False)
    digests: list[str | None] = []

    async def then(digest: str | None) -> None:
        digests.append(digest)

    hasher.submit(tmp_path / "t00.mkv", 10_000, then)
    progress: list[tuple[int, int, float | None]] = []

    async def on_progress(done: int, total: int, rate: float | None) -> None:
        progress.append((done, total, rate))

    await hasher.finish(on_progress)
    assert digests == [None]
    assert hasher._bytes_total == 0


async def test_hashing_on_reports_the_digest(tmp_path: Path) -> None:
    path = tmp_path / "t00.mkv"
    path.write_bytes(b"abc")
    hasher = TitleHasher()
    digests: list[str | None] = []

    async def then(digest: str | None) -> None:
        digests.append(digest)

    hasher.submit(path, 3, then)
    await hasher.finish()
    assert digests == ["ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"]


async def test_an_unreadable_title_reports_no_digest(tmp_path: Path) -> None:
    hasher = TitleHasher()
    digests: list[str | None] = []

    async def then(digest: str | None) -> None:
        digests.append(digest)

    hasher.submit(tmp_path / "missing.mkv", 3, then)
    await hasher.finish()
    assert digests == [None]
