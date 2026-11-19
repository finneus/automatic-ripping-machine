"""Remove a job's raw rip once its sessions are done, when the operator asked for it.

`config.default_retention_policy = prune_after_session` removes `/raw/<job_id>/` after the last session applied to
the job finishes, so the leftovers of a rip (titles no session used, the source of an encode) stop filling the raw
disk. It only ever removes a rip that ended `ripped` whose every session ended `done`: a partial rip, or a session
that failed or only partly finished, keeps its raw files for a retry. `keep_forever` (the default) keeps everything.
"""

import asyncio
import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from arm_backend.constants import CONFIG_SINGLETON_ID
from arm_backend.job_files import remove_raw_dir
from arm_common import Config, Job, JobStatus, SessionApplication, SessionApplicationStatus
from arm_common.enums import RetentionPolicy

logger = logging.getLogger("arm_backend.raw_retention")


async def _prune_enabled(db: AsyncSession) -> bool:
    """Whether the retention policy removes raw rips after their sessions."""
    cfg = (await db.execute(select(Config).where(col(Config.id) == CONFIG_SINGLETON_ID))).scalar_one_or_none()
    return cfg is not None and cfg.default_retention_policy == RetentionPolicy.PRUNE_AFTER_SESSION


async def _rip_complete(db: AsyncSession, job_id: str) -> bool:
    """Whether the job's rip ended with every title ripped."""
    job = (await db.execute(select(Job).where(col(Job.id) == job_id))).scalar_one_or_none()
    return job is not None and job.status == JobStatus.RIPPED


async def _all_sessions_done(db: AsyncSession, job_id: str) -> bool:
    """Whether at least one session was applied to the job and every one of them ended `done`."""
    applications = (
        (await db.execute(select(SessionApplication).where(col(SessionApplication.job_id) == job_id))).scalars().all()
    )
    return bool(applications) and all(a.status == SessionApplicationStatus.DONE for a in applications)


async def prune_raw_after_sessions(db: AsyncSession, job_id: str | None, raw_root: Path) -> bool:
    """Remove `raw_root/<job_id>/` when the policy asks for it, the rip is complete and every session is done.

    Call it after the commit that settled a session. Returns True when the directory was removed. Never raises:
    a removal that fails is logged by `remove_raw_dir` and the raw rip stays."""
    if job_id is None:
        return False
    if not (await _prune_enabled(db) and await _rip_complete(db, job_id) and await _all_sessions_done(db, job_id)):
        return False
    try:
        removed = await asyncio.to_thread(remove_raw_dir, job_id, raw_root)
    except ValueError as exc:
        logger.warning("raw retention: not removing raw rip of job_id=%s: %s", job_id, exc)
        return False
    if removed:
        logger.info("raw retention: removed the raw rip of job_id=%s, every session is done", job_id)
    return bool(removed)
