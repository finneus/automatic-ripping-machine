"""Keep provider keys and bot tokens out of httpx's request log lines (#766).

httpx logs every request at INFO as `HTTP Request: GET <full URL> "HTTP/1.1 200 OK"`, and the backend keeps INFO.
OMDb takes its key as a query parameter (`apikey`), so every OMDb search, IMDb lookup and key check put the key into
`docker logs` and `/logs/arm-backend.log`; a Telegram bot token sits in the URL path (`/bot<token>/`). A filter on the
`httpx` logger masks both before the record reaches any handler, and keeps the rest of the line for troubleshooting.
"""

from __future__ import annotations

import logging
import re

HTTPX_LOGGER_NAME = "httpx"

# A secret query parameter (`?apikey=...`, `&token=...`): the name stays, the value goes.
_QUERY_SECRET_RE = re.compile(r"([?&](?:apikey|api_key|key|token|access_token)=)[^&#\s\"'<>]*", re.IGNORECASE)
# A Telegram bot token in a URL path: `/bot123456:ABC.../sendMessage`.
_BOT_TOKEN_RE = re.compile(r"(/bot)\d+:[A-Za-z0-9_-]+")


def redact_secrets(text: str) -> str:
    """`text` with the values of secret query parameters and bot tokens in URL paths replaced by `****`."""
    return _BOT_TOKEN_RE.sub(r"\1****", _QUERY_SECRET_RE.sub(r"\1****", text))


class HttpSecretRedactor(logging.Filter):
    """Rewrites a record's rendered message when it carries a secret; never drops the record."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = redact_secrets(message)
        if redacted != message:
            record.msg = redacted
            record.args = None
        return True


def install_http_log_redaction() -> None:
    """Attach the redactor to httpx's logger once; calling again is a no-op."""
    httpx_logger = logging.getLogger(HTTPX_LOGGER_NAME)
    if not any(isinstance(f, HttpSecretRedactor) for f in httpx_logger.filters):
        httpx_logger.addFilter(HttpSecretRedactor())
