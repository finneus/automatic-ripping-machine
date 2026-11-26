"""Pick among same-title TMDb movie hits (a remake and its original) by the disc's main-feature length.

TMDb's search ranks the well-known film first, which is right for most discs. A remake shares its title with the
original, though, and a disc title rarely carries the year: "Total Recall" ranks the 1990 film above the 2012 one,
"RoboCop" the 1987 film above the 2014 one, "Dune" the 2021 film above the 1984 one. The disc's longest title tells
them apart. Only hits with the query's own title compete with TMDb's first hit, and another one wins only when its
runtime fits the disc clearly better, so a disc of a film without a namesake keeps TMDb's first hit.

TMDb can also rank an unrated entry first: a fan film or placeholder whose title contains the disc's ("Cardboard Star
Wars: A New Hope" above "Star Wars" for the disc "Star Wars: A New Hope"). Behind such a first hit, rated hits whose
title is part of the query, or holds it, compete as well, and the first hit counts as unknown when TMDb lists no
runtime for it.
"""

import re
import unicodedata
from collections.abc import Sequence
from typing import Any

# How far down TMDb's ranking a namesake may sit and still compete.
POOL_SIZE = 5
# Another hit beats TMDb's first only when its runtime is at least this much closer to the disc's main feature.
CLEARLY_CLOSER_SECONDS = 5 * 60
# ...and only when it is this close at all: an extended cut runs longer than the listed runtime, a wrong film more.
MAX_OFF_SECONDS = 20 * 60

_NOT_WORD = re.compile(r"[^0-9a-z]+")


def normalized_title(text: str | None) -> str:
    """The title as plain lowercase letters and digits: case, accents, punctuation and spaces don't count, and a
    superscript digit counts as its digit ("Alien³" is "alien3", not "alien")."""
    decomposed = unicodedata.normalize("NFKD", text or "").casefold()
    return _NOT_WORD.sub("", decomposed)


def _is_named(result: dict[str, Any], wanted: str) -> bool:
    """Whether the hit's title or original title is the wanted (normalized) title."""
    return wanted in {normalized_title(result.get("title")), normalized_title(result.get("original_title"))}


def _is_related(result: dict[str, Any], wanted: str) -> bool:
    """Whether the hit's title or original title is part of the wanted (normalized) title, or holds it."""
    titles = {normalized_title(result.get("title")), normalized_title(result.get("original_title"))} - {""}
    return any(title in wanted or wanted in title for title in titles)


def is_rated(result: dict[str, Any]) -> bool:
    """Whether anyone voted on the hit; an unrated one is a placeholder, a festival short or a fan film."""
    return bool(result.get("vote_count"))


def same_title_pool(results: Sequence[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """TMDb's first hit, then the rated hits among the first `POOL_SIZE` that carry the query's title, or, behind an
    unrated first hit, a title that is part of the query or holds it.

    Unrated hits (no votes: placeholders, festival shorts) never compete. Empty when there are no results."""
    if not results:
        return []
    wanted = normalized_title(query)
    matches = _is_named if is_rated(results[0]) else _is_related
    namesakes = [r for r in results[1:POOL_SIZE] if is_rated(r) and matches(r, wanted)]
    return [results[0], *namesakes]


def _seconds_off(runtime_minutes: int | None, disc_seconds: int) -> int | None:
    """How far a listed runtime is from the disc's main feature, or None when the runtime is unknown."""
    return None if not runtime_minutes else abs(runtime_minutes * 60 - disc_seconds)


def runtime_choice(runtimes_minutes: Sequence[int | None], disc_seconds: int, *, first_rated: bool = True) -> int:
    """The index of the pool hit to take: 0 (TMDb's first) unless another hit's runtime fits the disc's main
    feature clearly better (`CLEARLY_CLOSER_SECONDS`) and closely enough (`MAX_OFF_SECONDS`).

    An unknown runtime never wins. An unknown first-hit runtime keeps the first hit (no evidence, no change) unless
    nobody rated it (`first_rated=False`): then any hit that fits the disc closely enough wins."""
    offs = [_seconds_off(m, disc_seconds) for m in runtimes_minutes]
    if not offs or (offs[0] is None and first_rated):
        return 0
    if offs[0] is None:
        # An unrated first hit with no runtime counts as a miss: any hit within MAX_OFF_SECONDS fits clearly better.
        offs[0] = MAX_OFF_SECONDS + CLEARLY_CLOSER_SECONDS
    best_off, best = min((off, i) for i, off in enumerate(offs) if off is not None)
    if best_off > MAX_OFF_SECONDS or best_off + CLEARLY_CLOSER_SECONDS > offs[0]:
        return 0
    return best
