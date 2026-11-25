"""scan_data: blkid label fallback plus the video-layout sniff for ISO images and discs in a drive."""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path

import pytest
from arm_common import DiscType

from arm_ripper.scan import data as data_module


class _Proc:
    returncode = 0

    def __init__(self, stdout: bytes) -> None:
        self._stdout = stdout

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, b""

    def kill(self) -> None:  # pragma: no cover - only reached on timeout
        pass

    async def wait(self) -> None:  # pragma: no cover - only reached on timeout
        pass


@pytest.fixture
def blkid_label(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _exec(*_args: object, **_kwargs: object) -> _Proc:
        return _Proc(b"Half_Baked\n")

    monkeypatch.setattr(data_module.asyncio, "create_subprocess_exec", _exec)


def _image(tmp_path: Path, payload: bytes) -> str:
    iso = tmp_path / "movie.iso"
    iso.write_bytes(b"\0" * 4096 + payload + b"\0" * 4096)
    return str(iso)


def test_sniff_finds_utf16_bdmv(tmp_path: Path) -> None:
    assert data_module.sniff_video_image(_image(tmp_path, "BDMV".encode("utf-16-be"))) is DiscType.BLURAY


def test_sniff_finds_ascii_video_ts(tmp_path: Path) -> None:
    assert data_module.sniff_video_image(_image(tmp_path, b"VIDEO_TS")) is DiscType.DVD


def test_sniff_none_for_plain_data(tmp_path: Path) -> None:
    assert data_module.sniff_video_image(_image(tmp_path, b"just some files")) is None


def test_sniff_none_when_unreadable(tmp_path: Path) -> None:
    assert data_module.sniff_video_image(str(tmp_path / "missing.iso")) is None


@pytest.mark.usefixtures("blkid_label")
def test_scan_data_iso_with_bdmv_is_bluray(tmp_path: Path) -> None:
    out = asyncio.run(data_module.scan_data(_image(tmp_path, "BDMV".encode("utf-16-be"))))
    assert out.disc_type is DiscType.BLURAY
    assert out.volume_label == "Half_Baked"
    assert out.titles == []


@pytest.mark.usefixtures("blkid_label")
def test_scan_data_iso_without_layout_is_data(tmp_path: Path) -> None:
    out = asyncio.run(data_module.scan_data(_image(tmp_path, b"backup files")))
    assert out.disc_type is DiscType.DATA
    assert out.volume_label == "Half_Baked"


@pytest.mark.usefixtures("blkid_label")
def test_scan_data_files_a_disc_with_bdmv_as_a_bluray(monkeypatch: pytest.MonkeyPatch) -> None:
    """#674: a Blu-ray in a drive whose MakeMKV scan failed is a video job with no titles, not a data disc."""
    sniffed: list[str] = []

    def _sniff(path: str) -> DiscType | None:
        sniffed.append(path)
        return DiscType.BLURAY

    monkeypatch.setattr(data_module, "sniff_video_image", _sniff)
    out = asyncio.run(data_module.scan_data("/dev/sr0"))
    assert (out.disc_type, out.volume_label, out.titles) == (DiscType.BLURAY, "Half_Baked", [])
    assert sniffed == ["/dev/sr0"]


@pytest.mark.usefixtures("blkid_label")
def test_scan_data_files_a_disc_without_a_video_layout_as_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data_module, "sniff_video_image", lambda _path: None)
    assert asyncio.run(data_module.scan_data("/dev/sr0")).disc_type is DiscType.DATA


class _HangingProc:
    def __init__(self) -> None:
        self.killed = False
        self.waited = False

    async def communicate(self) -> tuple[bytes, bytes]:
        await asyncio.sleep(3600)
        return b"", b""  # pragma: no cover - never reached

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> None:
        self.waited = True


def test_scan_data_blkid_timeout_kills_reaps_and_returns_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _HangingProc()

    async def _exec(*_args: object, **_kwargs: object) -> _HangingProc:
        return proc

    real_wait_for = asyncio.wait_for

    async def _fast_wait_for(awaitable: object, timeout: float) -> object:
        return await real_wait_for(awaitable, timeout=0.01)  # type: ignore[arg-type]

    monkeypatch.setattr(data_module.asyncio, "create_subprocess_exec", _exec)
    monkeypatch.setattr(data_module.asyncio, "wait_for", _fast_wait_for)
    out = asyncio.run(data_module.scan_data("/dev/sr0"))
    assert out.disc_type is DiscType.UNKNOWN
    assert out.volume_label is None
    assert proc.killed
    assert proc.waited


def test_classify_folder_with_bdmv_dir_is_bluray(tmp_path: Path) -> None:
    folder = tmp_path / "MY_DISC"
    (folder / "BDMV").mkdir(parents=True)
    result = data_module._classify_folder(str(folder))
    assert result.disc_type == DiscType.BLURAY
    assert result.volume_label == "MY_DISC"


def test_classify_folder_without_bdmv_is_dvd(tmp_path: Path) -> None:
    folder = tmp_path / "MY_DVD"
    folder.mkdir()
    result = data_module._classify_folder(str(folder))
    assert result.disc_type == DiscType.DVD
    assert result.volume_label == "MY_DVD"


def test_classify_folder_with_bdmv_file_is_dvd(tmp_path: Path) -> None:
    folder = tmp_path / "ODD_DISC"
    folder.mkdir()
    (folder / "BDMV").write_bytes(b"not a dir")
    assert data_module._classify_folder(str(folder)).disc_type == DiscType.DVD


def test_blkid_stdout_returns_stdout_and_spawns_exact_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[object, ...]] = []

    async def _exec(*args: object, **_kwargs: object) -> _Proc:
        seen.append(args)
        return _Proc(b"Half_Baked\n")

    monkeypatch.setattr(data_module.asyncio, "create_subprocess_exec", _exec)
    assert asyncio.run(data_module._blkid_stdout("/dev/sr0")) == b"Half_Baked\n"
    assert seen == [("blkid", "-o", "value", "-s", "LABEL", "/dev/sr0")]


def test_blkid_stdout_timeout_kills_reaps_and_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _HangingProc()

    async def _exec(*_args: object, **_kwargs: object) -> _HangingProc:
        return proc

    real_wait_for = asyncio.wait_for

    async def _fast_wait_for(awaitable: object, timeout: float) -> object:
        return await real_wait_for(awaitable, timeout=0.01)  # type: ignore[arg-type]

    monkeypatch.setattr(data_module.asyncio, "create_subprocess_exec", _exec)
    monkeypatch.setattr(data_module.asyncio, "wait_for", _fast_wait_for)
    assert asyncio.run(data_module._blkid_stdout("/dev/sr0")) is None
    assert proc.killed
    assert proc.waited


def test_sniffed_video_type_logs_found_layout(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    path = _image(tmp_path, "BDMV".encode("utf-16-be"))
    with caplog.at_level(logging.INFO, logger="arm_ripper.scan.data"):
        kind = asyncio.run(data_module._sniffed_video_type(path))
    assert kind is DiscType.BLURAY
    assert [r.getMessage() for r in caplog.records] == [
        f"image {path} carries a bluray layout; classifying as bluray with no titles"
    ]


def test_sniffed_video_type_none_without_layout(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="arm_ripper.scan.data"):
        kind = asyncio.run(data_module._sniffed_video_type(_image(tmp_path, b"backup files")))
    assert kind is None
    assert caplog.records == []


def test_sniffed_video_type_gives_up_on_a_read_that_hangs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A damaged disc can hold the read in the kernel's retries; the disc is then classified by its label alone."""
    release = threading.Event()

    def _hang(_path: str) -> DiscType | None:
        release.wait(5)
        return DiscType.BLURAY

    monkeypatch.setattr(data_module, "sniff_video_image", _hang)
    monkeypatch.setattr(data_module, "SNIFF_TIMEOUT_SECONDS", 0.05)
    with caplog.at_level(logging.WARNING, logger="arm_ripper.scan.data"):
        kind = asyncio.run(data_module._sniffed_video_type("/dev/sr0"))
    release.set()
    assert kind is None
    assert [r.getMessage() for r in caplog.records] == [
        "reading /dev/sr0 for a video layout took over 0.05s; classifying it by its label only"
    ]
