"""TheDiscDB's main-movie segment maps for a job's film (`main_feature_reference`)."""

from __future__ import annotations

import logging
import sqlite3

import pytest
from arm_common import DiscType, Job, JobStatus

from arm_backend.main_feature_reference import job_imdb_id, reference_segment_maps


class _Store:
    def __init__(self, maps: frozenset[str] = frozenset(), error: Exception | None = None) -> None:
        self.maps = maps
        self.error = error
        self.asked: list[str] = []

    def main_movie_segment_maps(self, imdb_id: str) -> frozenset[str]:
        self.asked.append(imdb_id)
        if self.error is not None:
            raise self.error
        return self.maps


def _job(imdb: str | None = "tt2488496") -> Job:
    identity = {"provider": "tmdb", "external_ids": {"imdb": imdb}} if imdb is not None else None
    meta = {"identity": identity} if identity is not None else {}
    return Job(id="job_1", drive_id="d", disc_type=DiscType.BLURAY, status=JobStatus.IDENTIFIED, metadata_json=meta)


def test_job_imdb_id_reads_the_identity_and_is_none_before_one() -> None:
    assert job_imdb_id(_job()) == "tt2488496"
    assert job_imdb_id(_job(None)) is None
    assert job_imdb_id(Job(id="job_2", drive_id="d", disc_type=DiscType.BLURAY, status=JobStatus.CREATED)) is None


def test_reference_asks_the_store_for_the_films_imdb_id() -> None:
    store = _Store(frozenset({"55,56"}))
    assert reference_segment_maps(store, _job()) == frozenset({"55,56"})  # type: ignore[arg-type]
    assert store.asked == ["tt2488496"]


def test_reference_is_empty_without_a_store_or_an_imdb_id() -> None:
    store = _Store(frozenset({"55,56"}))
    assert reference_segment_maps(None, _job()) == frozenset()
    assert reference_segment_maps(store, _job(None)) == frozenset()  # type: ignore[arg-type]
    assert store.asked == []


def test_a_failed_lookup_only_costs_the_hint(caplog: pytest.LogCaptureFixture) -> None:
    store = _Store(error=sqlite3.OperationalError("no such function: json_extract"))
    with caplog.at_level(logging.WARNING, logger="arm_backend.main_feature_reference"):
        assert reference_segment_maps(store, _job()) == frozenset()  # type: ignore[arg-type]
    assert "main-movie lookup failed job_id=job_1" in caplog.text
