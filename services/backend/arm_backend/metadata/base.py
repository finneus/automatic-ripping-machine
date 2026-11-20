"""Result and error types every metadata provider client shares."""

from dataclasses import dataclass, field
from typing import Any, Literal

import httpx


@dataclass(slots=True)
class MetadataResult:
    title: str
    year: int | None
    kind: Literal["movie", "tv", "music"]
    payload: dict[str, Any] = field(default_factory=dict)
    # Stamped by the dispatcher's _call wrapper (the one place that knows
    # which client produced the hit); None for results built outside it.
    provider: str | None = None


class LookupError(Exception):
    """Provider returned no usable result, or auth/transport failed."""


class LookupTimeout(LookupError):
    """Provider exceeded its per-call timeout budget."""


def json_object(response: httpx.Response, provider: str) -> dict[str, Any]:
    """The JSON object a provider answered with.

    A body that is not JSON (a proxy error page, a captive portal) or not a JSON object raises LookupError, so one
    misbehaving provider counts as that provider's miss instead of failing the whole identify with a 500.
    """
    try:
        body = response.json()
    except ValueError as e:
        raise LookupError(f"{provider} returned non-JSON response") from e
    if not isinstance(body, dict):
        raise LookupError(f"{provider} returned a JSON response that is not an object")
    return body
