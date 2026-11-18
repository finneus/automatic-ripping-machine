"""Apply a session while the disc rips, driven through the real routers.

The review countdown starts the rip after `manual_wait_seconds`; an operator
who chooses the session after that must not have to wait out the rip. The
apply parks (`waiting_identify`, no tasks) and rip-complete fans it out.
Both routers share one FakeSession.
"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arm_backend import session_drain as session_drain_mod
from arm_backend.db import get_session
from arm_backend.jwt_utils import issue_access_token
from arm_backend.routers import jobs as jobs_router
from arm_backend.routers import ripper as ripper_router
from arm_common import (
    ContainerFormat,
    JobStatus,
    MediaType,
    Session,
    SessionApplicationStatus,
    TrackStatus,
    TranscodePreset,
    TranscodeTool,
    User,
)

from tests._fakes import FakeSession
from tests.test_ripper_router import _OWNER_HEADERS, _config, _drive, _Hub, _job, _movie_preset, _track

_JOB = "job_01JZXR7K3M5Q8N4VWA00000001"


def _seed_ripping_job(db: FakeSession) -> None:
    """A movie job mid-rip with its one track still in progress, and a session to apply."""
    db.rows["users"] = [User(id="usr_admin", username="admin", password_hash="x", password_must_change=False)]
    db.rows["drives"] = [_drive()]
    db.rows["config"] = [_config(hold_for_review=True)]
    db.rows["jobs"] = [_job(status=JobStatus.RIPPING)]
    db.rows["jobs"][0].media_type = MediaType.MOVIE
    db.rows["tracks"] = [_track("t1", status=TrackStatus.IN_PROGRESS)]
    db.rows["rip_presets"] = [_movie_preset("rpr_x")]
    db.rows["transcode_presets"] = [
        TranscodePreset(
            id="tpr_x",
            name="Plex 1080p H.265",
            media_type=MediaType.MOVIE,
            is_builtin=True,
            tool=TranscodeTool.HANDBRAKE,
            container=ContainerFormat.MKV,
            encoder="preset",
        )
    ]
    db.rows["sessions"] = [
        Session(
            id="ses_x",
            name="My Plex",
            media_type=MediaType.MOVIE,
            is_builtin=False,
            rip_preset_id="rpr_x",
            transcode_preset_id="tpr_x",
            output_path_template="{title} ({year})/{title} - {transcode_slug}.{ext}",
        )
    ]
    db.rows["session_applications"] = []
    db.rows["transcode_tasks"] = []


def _make_app(db: FakeSession, hub: _Hub) -> tuple[FastAPI, dict[str, str]]:
    signing_key = secrets.token_bytes(32)
    app = FastAPI()
    app.state.signing_key = signing_key
    app.state.ws_hub = hub
    app.include_router(ripper_router.router)
    app.include_router(jobs_router.router)

    async def _override_session() -> FakeSession:
        return db

    app.dependency_overrides[get_session] = _override_session
    token, _ = issue_access_token("usr_admin", "admin", signing_key)
    return app, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def media_root(tmp_path: Path) -> Path:
    from arm_backend import config as bcfg

    bcfg.settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


def test_apply_while_ripping_parks_and_locks_the_job_row(media_root: Path) -> None:
    """The apply takes the job row FOR UPDATE and parks with no tasks: the
    tracks exist but have not been ripped yet."""
    db = FakeSession()
    _seed_ripping_job(db)
    app, auth = _make_app(db, _Hub())
    with TestClient(app) as client:
        r = client.post(f"/api/jobs/{_JOB}/transcode", json={"session_id": "ses_x"}, headers=auth)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session_application"]["status"] == "waiting_identify"
    assert body["tasks"] == []
    assert db.rows["transcode_tasks"] == []
    assert db.locked[0] == "jobs"


def test_session_applied_while_ripping_is_fanned_out_at_rip_complete(
    media_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The parked application is drained by rip-complete like one applied
    before the rip: it is queued with a task for the ripped track."""

    async def _no_auto_apply(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(session_drain_mod, "maybe_auto_apply_session", _no_auto_apply)
    db = FakeSession()
    _seed_ripping_job(db)
    hub = _Hub()
    app, auth = _make_app(db, hub)
    with TestClient(app) as client:
        r = client.post(f"/api/jobs/{_JOB}/transcode", json={"session_id": "ses_x"}, headers=auth)
        assert r.status_code == 200, r.text
        db.rows["tracks"][0].status = TrackStatus.DONE
        r = client.post(f"/api/ripper/jobs/{_JOB}/rip-complete", json={}, headers=_OWNER_HEADERS)

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ripped"
    application = db.rows["session_applications"][0]
    assert application.status == SessionApplicationStatus.QUEUED
    tasks = db.rows["transcode_tasks"]
    assert [t.source_track_id for t in tasks] == ["t1"]
    assert tasks[0].session_application_id == application.id
