"""#766: provider keys and bot tokens never reach the log through httpx's request lines."""

import logging

import httpx
import pytest

from arm_backend import http_log_redaction as red

_KEY = "c0ffee42"
_TOKEN = "123456789:" + "A" * 35


@pytest.fixture
def clean_httpx_logger():
    httpx_logger = logging.getLogger(red.HTTPX_LOGGER_NAME)
    saved = list(httpx_logger.filters)
    for f in saved:
        httpx_logger.removeFilter(f)
    yield httpx_logger
    for f in list(httpx_logger.filters):
        httpx_logger.removeFilter(f)
    for f in saved:
        httpx_logger.addFilter(f)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            f'HTTP Request: GET https://www.omdbapi.com/?apikey={_KEY}&s=alien "HTTP/1.1 200 OK"',
            'HTTP Request: GET https://www.omdbapi.com/?apikey=****&s=alien "HTTP/1.1 200 OK"',
        ),
        (f"https://x.test/a?s=1&API_KEY={_KEY}#frag", "https://x.test/a?s=1&API_KEY=****#frag"),
        (
            f"https://x.test/a?key={_KEY}&token=t0k&access_token=abc",
            "https://x.test/a?key=****&token=****&access_token=****",
        ),
        (f"https://api.telegram.org/bot{_TOKEN}/sendMessage", "https://api.telegram.org/bot****/sendMessage"),
    ],
)
def test_redact_secrets_masks_values_and_keeps_the_rest(text: str, expected: str) -> None:
    assert red.redact_secrets(text) == expected


def test_redact_secrets_leaves_ordinary_parameters_alone() -> None:
    text = "https://api.themoviedb.org/3/search/movie?query=monkey&keyword=x&year=1999"
    assert red.redact_secrets(text) == text


def test_filter_renders_args_only_when_something_was_masked() -> None:
    leaking = logging.LogRecord("httpx", logging.INFO, __file__, 1, "GET %s", (f"https://o.test/?apikey={_KEY}",), None)
    assert red.HttpSecretRedactor().filter(leaking) is True
    assert leaking.getMessage() == "GET https://o.test/?apikey=****"
    assert leaking.args is None
    clean = logging.LogRecord("httpx", logging.INFO, __file__, 1, "GET %s", ("https://o.test/?s=x",), None)
    assert red.HttpSecretRedactor().filter(clean) is True
    assert clean.args == ("https://o.test/?s=x",)


def test_install_is_idempotent(clean_httpx_logger) -> None:
    red.install_http_log_redaction()
    red.install_http_log_redaction()
    assert sum(isinstance(f, red.HttpSecretRedactor) for f in clean_httpx_logger.filters) == 1


async def test_a_real_httpx_request_line_carries_no_key(clean_httpx_logger, caplog) -> None:
    """The real leak: httpx's own INFO line for an OMDb request with the key in the query."""
    red.install_http_log_redaction()
    caplog.set_level(logging.INFO, logger=red.HTTPX_LOGGER_NAME)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"Response": "False"}))
    async with httpx.AsyncClient(transport=transport) as client:
        await client.get("https://www.omdbapi.com/", params={"apikey": _KEY, "s": "alien"})
    lines = [r.getMessage() for r in caplog.records if r.name == red.HTTPX_LOGGER_NAME]
    assert lines, "httpx logged nothing; the test no longer exercises the leak"
    assert not any(_KEY in line for line in lines)
    assert any("apikey=****" in line for line in lines)
