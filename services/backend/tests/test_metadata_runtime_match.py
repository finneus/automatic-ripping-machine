"""A same-title TMDb movie tie (a remake and its original) is broken by the disc's main-feature length.

Covers the pure picker (`runtime_match`), the TMDb client's `search_movie_near`, the TMDb source's
`search_title_near` capability, and the dispatcher passing the disc's longest title to it.
"""

from typing import Any

import httpx
import pytest
import respx

from arm_backend.metadata import sources as sources_mod
from arm_backend.metadata.base import LookupError, MetadataResult
from arm_backend.metadata.dispatcher import MetadataDispatcher, _main_feature_seconds, _title_search
from arm_backend.metadata.runtime_match import (
    CLEARLY_CLOSER_SECONDS,
    MAX_OFF_SECONDS,
    is_rated,
    normalized_title,
    runtime_choice,
    same_title_pool,
)
from arm_backend.metadata.sources import build_online_sources
from arm_backend.metadata.tmdb import TMDBClient
from arm_common import Config, DiscType
from arm_common.schemas import ScanResult, ScanTitle

_SEARCH = "https://api.themoviedb.org/3/search/movie"


def _config(**overrides: Any) -> Config:
    base: dict[str, Any] = dict(id=1, tmdb_api_key="tmdb-k", omdb_api_key="omdb-k")
    base.update(overrides)
    return Config(**base)


def _hit(title: str, year: int, tmdb_id: int, votes: int = 100, original: str | None = None) -> dict[str, Any]:
    hit: dict[str, Any] = {"id": tmdb_id, "title": title, "release_date": f"{year}-06-01", "vote_count": votes}
    if original is not None:
        hit["original_title"] = original
    return hit


# --- normalized_title / same_title_pool ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Total Recall", "totalrecall"),
        ("RoboCop", "robocop"),
        ("Léon: The Professional", "leontheprofessional"),
        ("Alien³", "alien3"),
        (None, ""),
    ],
)
def test_normalized_title(text: str | None, expected: str) -> None:
    assert normalized_title(text) == expected


def test_pool_is_empty_without_results() -> None:
    assert same_title_pool([], "Total Recall") == []


def test_pool_keeps_the_first_hit_and_rated_namesakes_in_the_top_five() -> None:
    results = [
        _hit("Total Recall", 1990, 1),
        _hit("Total Recall", 2012, 2),
        _hit("Total Recall", 2004, 3, votes=0),
        _hit("Imagining 'Total Recall'", 2001, 4),
        _hit("TOTAL RECALL", 1987, 5, votes=3),
        _hit("Total Recall", 2020, 6),
    ]
    assert [r["id"] for r in same_title_pool(results, "total recall")] == [1, 2, 5]


def test_pool_matches_the_original_title_and_keeps_a_differently_named_first_hit() -> None:
    results = [_hit("The Batman", 2022, 1), _hit("Le Batman", 1989, 2, original="Batman")]
    assert [r["id"] for r in same_title_pool(results, "Batman")] == [1, 2]


# TMDb's real answer for the UHD "Star Wars: A New Hope": an unrated fan film first, the film second (as "Star Wars").
_NEW_HOPE = [
    _hit("Cardboard Star Wars: A New Hope", 2026, 1797334, votes=0),
    _hit("Star Wars", 1977, 11, votes=23227),
    _hit("Maclunkey Treasure Island: A Live Staged Reading of Star Wars - A New Hope", 2025, 1822693, votes=0),
]


def test_pool_behind_an_unrated_first_hit_takes_rated_hits_whose_title_is_part_of_the_query() -> None:
    assert [r["id"] for r in same_title_pool(_NEW_HOPE, "Star Wars: A New Hope")] == [1797334, 11]


def test_pool_behind_an_unrated_first_hit_takes_a_rated_hit_that_holds_the_query() -> None:
    results = [_hit("Heat", 2026, 1, votes=0), _hit("Heat (Director's Cut)", 1995, 2), _hit("Frozen", 2013, 3)]
    assert [r["id"] for r in same_title_pool(results, "Heat")] == [1, 2]


def test_pool_behind_a_rated_first_hit_still_wants_the_query_title() -> None:
    results = [_hit("Star Wars: A New Hope", 2026, 1), _hit("Star Wars", 1977, 11, votes=23227)]
    assert [r["id"] for r in same_title_pool(results, "Star Wars: A New Hope")] == [1]


def test_is_rated() -> None:
    assert is_rated(_hit("A", 2000, 1)) is True
    assert is_rated(_hit("A", 2000, 1, votes=0)) is False
    assert is_rated({"id": 1}) is False


# --- runtime_choice --------------------------------------------------------------------------------------------------


def test_choice_takes_the_namesake_that_fits_clearly_better() -> None:
    # RoboCop 1987 (102 min) ranks first; the disc runs 117 min, the 2014 film.
    assert runtime_choice([102, 117], 117 * 60) == 1


def test_choice_keeps_the_first_hit_when_it_fits_best() -> None:
    assert runtime_choice([113, 118], 113 * 60) == 0


def test_choice_keeps_the_first_hit_when_the_other_is_not_clearly_closer() -> None:
    disc = 115 * 60
    near_miss = (disc - (CLEARLY_CLOSER_SECONDS - 60)) // 60
    assert runtime_choice([near_miss, 115], disc) == 0


def test_choice_keeps_the_first_hit_when_the_best_fit_is_still_too_far_off() -> None:
    disc = 200 * 60
    assert runtime_choice([100, (disc - MAX_OFF_SECONDS - 60) // 60], disc) == 0


def test_choice_keeps_the_first_hit_when_its_runtime_is_unknown() -> None:
    assert runtime_choice([None, 117], 117 * 60) == 0


def test_choice_replaces_an_unrated_first_hit_with_no_runtime_by_a_close_fit() -> None:
    assert runtime_choice([None, 121], 125 * 60, first_rated=False) == 1


def test_choice_keeps_an_unrated_first_hit_when_nothing_fits_closely() -> None:
    disc = 125 * 60
    assert runtime_choice([None, (disc + MAX_OFF_SECONDS + 60) // 60], disc, first_rated=False) == 0
    assert runtime_choice([None, None], disc, first_rated=False) == 0


def test_choice_ignores_namesakes_with_unknown_runtimes() -> None:
    assert runtime_choice([102, None, 117], 117 * 60) == 2


def test_choice_with_no_runtimes_keeps_the_first_hit() -> None:
    assert runtime_choice([], 100 * 60) == 0


# --- TMDBClient.search_movie_near ----------------------------------------------------------------------------------


@pytest.fixture
async def http_client():  # type: ignore[no-untyped-def]
    async with httpx.AsyncClient(timeout=5.0) as client:
        yield client


def _details(runtimes: dict[int, Any]) -> None:
    for tmdb_id, runtime in runtimes.items():
        route = respx.get(f"https://api.themoviedb.org/3/movie/{tmdb_id}")
        if isinstance(runtime, httpx.Response):
            route.mock(return_value=runtime)
        else:
            route.mock(return_value=httpx.Response(200, json={"id": tmdb_id, "runtime": runtime}))


@respx.mock
async def test_near_picks_the_remake_that_fits_the_disc(http_client) -> None:
    respx.get(_SEARCH).mock(
        return_value=httpx.Response(
            200, json={"results": [_hit("Total Recall", 1990, 861), _hit("Total Recall", 2012, 64635)]}
        )
    )
    _details({861: 113, 64635: 130})
    hit = await TMDBClient("k", http_client).search_movie_near("Total Recall", None, 130 * 60)
    assert (hit.title, hit.year, hit.payload["id"]) == ("Total Recall", 2012, 64635)


@respx.mock
async def test_near_takes_the_film_over_an_unrated_fan_film_that_ranks_first(http_client) -> None:
    """The disc "Star Wars: A New Hope" (125 min) is TMDb's "Star Wars" (121 min), not the 52 min fan film TMDb
    ranks first."""
    respx.get(_SEARCH).mock(return_value=httpx.Response(200, json={"results": _NEW_HOPE}))
    _details({1797334: 52, 11: 121})
    hit = await TMDBClient("k", http_client).search_movie_near("Star Wars: A New Hope", None, 7485)
    assert (hit.title, hit.year, hit.payload["id"]) == ("Star Wars", 1977, 11)


@respx.mock
async def test_near_sends_the_year_and_keeps_a_lone_hit_without_detail_calls(http_client) -> None:
    search = respx.get(_SEARCH).mock(return_value=httpx.Response(200, json={"results": [_hit("Heat", 1995, 949)]}))
    hit = await TMDBClient("k", http_client).search_movie_near("Heat", 1995, 170 * 60)
    assert hit.payload["id"] == 949
    assert search.calls.last.request.url.params["year"] == "1995"
    assert len(respx.calls) == 1


@respx.mock
async def test_near_keeps_the_first_hit_when_runtime_lookups_fail(http_client) -> None:
    respx.get(_SEARCH).mock(
        return_value=httpx.Response(200, json={"results": [_hit("RoboCop", 1987, 5548), _hit("RoboCop", 2014, 97020)]})
    )
    _details({5548: httpx.Response(500), 97020: 117})
    hit = await TMDBClient("k", http_client).search_movie_near("RoboCop", None, 117 * 60)
    assert hit.year == 1987


@respx.mock
async def test_near_treats_a_missing_or_zero_runtime_as_unknown(http_client) -> None:
    respx.get(_SEARCH).mock(
        return_value=httpx.Response(
            200,
            json={"results": [_hit("Dune", 2021, 438631), _hit("Dune", 1984, 841), {"title": "Dune", "vote_count": 5}]},
        )
    )
    _details({438631: 0, 841: None})
    hit = await TMDBClient("k", http_client).search_movie_near("Dune", None, 137 * 60)
    assert hit.year == 2021


@respx.mock
async def test_near_without_results_raises(http_client) -> None:
    respx.get(_SEARCH).mock(return_value=httpx.Response(200, json={"results": []}))
    with pytest.raises(LookupError, match="no results"):
        await TMDBClient("k", http_client).search_movie_near("Nothing", None, 6000)


@respx.mock
async def test_near_with_an_untitled_hit_raises(http_client) -> None:
    respx.get(_SEARCH).mock(return_value=httpx.Response(200, json={"results": [{"id": 1}]}))
    with pytest.raises(LookupError, match="missing title"):
        await TMDBClient("k", http_client).search_movie_near("Nothing", None, 6000)


# --- TmdbSource.search_title_near ----------------------------------------------------------------------------------


async def test_tmdb_source_passes_the_runtime_to_the_client(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, int | None, int]] = []

    class FakeTMDB:
        def __init__(self, key: str, http: httpx.AsyncClient) -> None:
            pass

        async def search_movie_near(self, title: str, year: int | None, runtime_seconds: int) -> MetadataResult:
            calls.append((title, year, runtime_seconds))
            return MetadataResult(title="M", year=year, kind="movie")

    monkeypatch.setattr(sources_mod, "TMDBClient", FakeTMDB)
    async with httpx.AsyncClient() as http:
        hit = await build_online_sources(http)["tmdb"].search_title_near(_config(), "RoboCop", None, 7020)
    assert hit is not None and hit.title == "M"
    assert calls == [("RoboCop", None, 7020)]


# --- dispatcher ------------------------------------------------------------------------------------------------------


def _scan(*durations: int) -> ScanResult:
    titles = [ScanTitle(index=i, duration_seconds=d) for i, d in enumerate(durations)]
    return ScanResult(disc_type=DiscType.BLURAY, volume_label="ROBOCOP", titles=titles)


def test_main_feature_is_the_longest_title() -> None:
    assert _main_feature_seconds(_scan(300, 7020, 600)) == 7020


def test_main_feature_is_unknown_without_titles() -> None:
    assert _main_feature_seconds(ScanResult(disc_type=DiscType.DVD, volume_label="X")) is None


class _Source:
    """A source with only the capabilities passed in, recording each call."""

    id = "tmdb"
    media_types = frozenset({"movie", "tv"})
    requires_key = None

    def __init__(self, calls: list[tuple[Any, ...]], *, near: bool = True, plain: bool = True) -> None:
        self._calls = calls
        if near:
            self.search_title_near = self._near
        if plain:
            self.search_title = self._plain

    def configured(self, cfg: Config) -> None:
        return None

    async def _near(self, cfg: Config, title: str, year: int | None, runtime_seconds: int) -> MetadataResult:
        self._calls.append(("near", title, year, runtime_seconds))
        return MetadataResult(title=title, year=year, kind="movie")

    async def _plain(self, cfg: Config, kind: str, title: str, year: int | None) -> MetadataResult:
        self._calls.append(("plain", kind, title, year))
        return MetadataResult(title=title, year=year, kind=kind)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("kind", "runtime", "near", "expected"),
    [
        ("movie", 7020, True, "near"),
        ("movie", None, True, "plain"),
        ("tv", 7020, True, "plain"),
        ("movie", 7020, False, "plain"),
    ],
    ids=["movie-with-runtime", "no-runtime", "tv", "source-without-near"],
)
async def test_title_search_picks_the_capability(kind: str, runtime: int | None, near: bool, expected: str) -> None:
    calls: list[tuple[Any, ...]] = []
    call = _title_search(_Source(calls, near=near), _config(), kind, "RoboCop", None, runtime)  # type: ignore[arg-type]
    assert call is not None
    await call
    assert calls[0][0] == expected


def test_title_search_is_none_for_a_source_without_a_title_search() -> None:
    assert _title_search(_Source([], near=False, plain=False), _config(), "movie", "X", None, 7020) is None  # type: ignore[arg-type]


async def test_identify_hands_the_main_feature_length_to_the_movie_search() -> None:
    calls: list[tuple[Any, ...]] = []
    async with httpx.AsyncClient() as http:
        dispatcher = MetadataDispatcher(http, sources={"tmdb": _Source(calls)})
        hit = await dispatcher.identify(_scan(300, 7020), _config(omdb_api_key=None))
    assert hit is not None and hit.title == "ROBOCOP"
    assert calls == [("near", "ROBOCOP", None, 7020)]


async def test_identify_prefer_tv_hands_the_length_to_the_movie_fallback() -> None:
    calls: list[tuple[Any, ...]] = []

    class TvMiss(_Source):
        async def _plain(self, cfg: Config, kind: str, title: str, year: int | None) -> MetadataResult | None:  # type: ignore[override]
            self._calls.append(("plain", kind, title, year))
            return None

    async with httpx.AsyncClient() as http:
        dispatcher = MetadataDispatcher(http, sources={"tmdb": TvMiss(calls)})
        hit = await dispatcher.identify(_scan(2700, 2650), _config(omdb_api_key=None), prefer_tv=True)
    assert hit is not None
    assert calls == [("plain", "tv", "ROBOCOP", None), ("near", "ROBOCOP", None, 2700)]


async def test_identify_skips_a_source_without_a_title_search() -> None:
    async with httpx.AsyncClient() as http:
        dispatcher = MetadataDispatcher(http, sources={"tmdb": _Source([], near=False, plain=False)})
        assert await dispatcher.identify(_scan(7020), _config(omdb_api_key=None)) is None
