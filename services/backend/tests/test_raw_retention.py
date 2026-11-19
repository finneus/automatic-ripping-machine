"""raw_retention: a raw rip is removed only when the policy asks for it, the rip is complete and every session is
done."""

from pathlib import Path

import pytest

from arm_backend.raw_retention import prune_raw_after_sessions
from arm_common import Config, DiscType, Job, JobStatus, SessionApplication, SessionApplicationStatus
from arm_common.enums import RetentionPolicy

from tests._fakes import FakeSession

_JOB = "job_01JZXR7K3M5Q8N4VWA00000001"


def _seed(
    tmp_path: Path,
    *,
    policy: RetentionPolicy | None = RetentionPolicy.PRUNE_AFTER_SESSION,
    job_status: JobStatus = JobStatus.RIPPED,
    sessions: tuple[SessionApplicationStatus, ...] = (SessionApplicationStatus.DONE,),
    job_id: str = _JOB,
) -> tuple[FakeSession, Path]:
    db = FakeSession()
    db.rows["config"] = [] if policy is None else [Config(id=1, default_retention_policy=policy)]
    db.rows["jobs"] = [Job(id=job_id, drive_id="drv_x", disc_type=DiscType.BLURAY, status=job_status)]
    db.rows["session_applications"] = [
        SessionApplication(id=f"sap_{i}", session_id="ses_x", job_id=job_id, status=s, overwrite=False)
        for i, s in enumerate(sessions)
    ]
    raw = tmp_path / "raw"
    (raw / job_id).mkdir(parents=True)
    (raw / job_id / "Disc_t02.mkv").write_bytes(b"left over")
    return db, raw


async def test_removes_the_raw_rip_when_every_session_is_done(tmp_path: Path) -> None:
    db, raw = _seed(tmp_path, sessions=(SessionApplicationStatus.DONE, SessionApplicationStatus.DONE))
    assert await prune_raw_after_sessions(db, _JOB, raw) is True  # type: ignore[arg-type]
    assert not (raw / _JOB).exists()


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"policy": RetentionPolicy.KEEP_FOREVER}, "keep_forever"),
        ({"policy": None}, "no config row"),
        ({"job_status": JobStatus.RIPPED_PARTIAL}, "partial rip"),
        ({"sessions": (SessionApplicationStatus.DONE, SessionApplicationStatus.FAILED)}, "a failed session"),
        ({"sessions": (SessionApplicationStatus.DONE_PARTIAL,)}, "a partly done session"),
        ({"sessions": (SessionApplicationStatus.RUNNING,)}, "a running session"),
        ({"sessions": ()}, "no session"),
    ],
    ids=lambda v: v if isinstance(v, str) else "",
)
async def test_keeps_the_raw_rip(tmp_path: Path, overrides: dict, reason: str) -> None:
    db, raw = _seed(tmp_path, **overrides)
    assert await prune_raw_after_sessions(db, _JOB, raw) is False  # type: ignore[arg-type]
    assert (raw / _JOB / "Disc_t02.mkv").exists(), reason


async def test_keeps_nothing_for_an_unknown_job(tmp_path: Path) -> None:
    db, raw = _seed(tmp_path)
    assert await prune_raw_after_sessions(db, None, raw) is False  # type: ignore[arg-type]
    assert await prune_raw_after_sessions(db, "job_01JZXR7K3M5Q8N4VWA00000009", raw) is False  # type: ignore[arg-type]


async def test_a_missing_raw_dir_is_not_reported_removed(tmp_path: Path) -> None:
    db, raw = _seed(tmp_path)
    (raw / _JOB / "Disc_t02.mkv").unlink()
    (raw / _JOB).rmdir()
    assert await prune_raw_after_sessions(db, _JOB, raw) is False  # type: ignore[arg-type]


async def test_a_malformed_job_id_never_removes_anything(tmp_path: Path) -> None:
    db, raw = _seed(tmp_path, job_id="job_not-a-ulid")
    assert await prune_raw_after_sessions(db, "job_not-a-ulid", raw) is False  # type: ignore[arg-type]
    assert (raw / "job_not-a-ulid").exists()
