"""TheDiscDB's word on which same-length title is the film, for a disc TheDiscDB does not know by its own hash.

A UHD often carries the film once per language group (same length and audio, its own opening text and credits).
TheDiscDB marks the original one `MainMovie`; another pressing of the film plays it from the same clips, so the
scanned title with that segment map is the film (`track_selection` prefers it)."""

from __future__ import annotations

import logging
import sqlite3

from arm_common import Job
from arm_common.schemas.job_metadata import JobMetadata

from arm_backend.identity.sources.thediscdb_snapshot import SnapshotStore

logger = logging.getLogger("arm_backend.main_feature_reference")


def job_imdb_id(job: Job) -> str | None:
    """The IMDb id identification gave the job, or None before it has one."""
    identity = JobMetadata.model_validate(job.metadata_json or {}).identity
    return identity.external_ids.imdb if identity is not None else None


def reference_segment_maps(store: SnapshotStore | None, job: Job) -> frozenset[str]:
    """The segment maps TheDiscDB marks the main movie for the job's film; empty without a store, an IMDb id or a
    readable index (a failed lookup only costs the hint)."""
    imdb_id = job_imdb_id(job)
    if store is None or not imdb_id:
        return frozenset()
    try:
        return store.main_movie_segment_maps(imdb_id)
    except sqlite3.Error as exc:
        logger.warning("thediscdb: main-movie lookup failed job_id=%s: %s", job.id, exc)
        return frozenset()
