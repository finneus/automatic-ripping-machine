import asyncio
import logging
from pathlib import Path

from arm_common import DiscType
from arm_common.schemas import ScanResult
from arm_ripper.source import is_folder_source

logger = logging.getLogger("arm_ripper.scan.data")


# How much of an image to read when sniffing for a video disc layout. The UDF
# directory tree of a Blu-ray or DVD image sits near the start of the image
# (the metadata partition of a UDF 2.5 BD-R backup lands within the first few
# MB), so 64 MB is plenty and reads in well under a second from local disk.
_SNIFF_BYTES = 64 * 1024 * 1024

# Directory names that only a video disc carries, in both encodings UDF uses
# for file identifiers (8-bit compressed and UTF-16BE) plus plain ISO 9660.
_VIDEO_SIGNATURES: tuple[tuple[str, DiscType], ...] = (("BDMV", DiscType.BLURAY), ("VIDEO_TS", DiscType.DVD))

# How long the sniff may read before the disc is classified by its label alone. A drive reads 64 MB in a few seconds;
# a damaged disc can keep a read in the kernel's retries for minutes.
SNIFF_TIMEOUT_SECONDS = 60.0


def sniff_video_image(path: str) -> DiscType | None:
    """Classify an image or disc MakeMKV could not open by the directory names it carries.

    A Blu-ray or DVD that makemkvcon crashes on (seen with a DVDFab UDF 2.50
    backup: full BDMV tree, makemkvcon exits with SIGSEGV) or whose scan
    times out (a UHD whose key MakeMKV is still fetching) must not be filed as
    a data disc: that hides the title search on the job page and routes it to
    the data-copy session, which copies the whole disc. The file system is
    not encrypted, so its names read even when the streams can't be. Returns
    BLURAY, DVD, or None when no video-disc directory name appears in the
    first 64 MB.
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(_SNIFF_BYTES)
    except OSError:
        return None
    for name, kind in _VIDEO_SIGNATURES:
        if name.encode("ascii") in head or name.encode("utf-16-be") in head:
            return kind
    return None


async def scan_data(device_path: str) -> ScanResult:
    """Last-resort fallback: read the volume label via blkid.

    An ISO image or a disc in a drive is also sniffed for a Blu-ray/DVD
    directory layout, so a video disc MakeMKV cannot open or scan in time
    still becomes a video job (with no titles) rather than a data disc.
    """
    if is_folder_source(device_path):
        return _classify_folder(device_path)
    stdout = await _blkid_stdout(device_path)
    if stdout is None:
        return ScanResult(disc_type=DiscType.UNKNOWN)

    label = stdout.decode(errors="replace").strip() or None
    kind = await _sniffed_video_type(device_path)
    return ScanResult(disc_type=kind or DiscType.DATA, volume_label=label)


def _classify_folder(device_path: str) -> ScanResult:
    """A disc folder MakeMKV listed nothing in: a Blu-ray when it holds BDMV, else a DVD, named after the folder.

    blkid has no volume to read in a folder, so the tree alone decides.
    """
    folder = Path(device_path)
    folder_type = DiscType.BLURAY if (folder / "BDMV").is_dir() else DiscType.DVD
    return ScanResult(disc_type=folder_type, volume_label=folder.name)


async def _blkid_stdout(device_path: str) -> bytes | None:
    """Run `blkid` for the device's volume label and return its stdout; None when it hangs past 15 s (killed and
    reaped).
    """
    proc = await asyncio.create_subprocess_exec(
        "blkid",
        "-o",
        "value",
        "-s",
        "LABEL",
        device_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return None
    return stdout


async def _sniffed_video_type(device_path: str) -> DiscType | None:
    """The video disc type the directory names of an image or a disc reveal, logged when found; None without a
    Blu-ray / DVD layout, or when the read outlasts SNIFF_TIMEOUT_SECONDS.
    """
    try:
        kind = await asyncio.wait_for(asyncio.to_thread(sniff_video_image, device_path), timeout=SNIFF_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        logger.warning(
            "reading %s for a video layout took over %ss; classifying it by its label only",
            device_path,
            SNIFF_TIMEOUT_SECONDS,
        )
        return None
    if kind is not None:
        logger.info(
            "image %s carries a %s layout; classifying as %s with no titles", device_path, kind.value, kind.value
        )
    return kind
