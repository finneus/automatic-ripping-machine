"""Keep notification URLs out of apprise's own log lines.

ARM redacts every URL it logs itself (`redact_apprise_url`), but apprise logs
through its own `apprise` logger, which propagates to the service's root
handlers. Its messages quote the URL it was handed (e.g. "Unparseable Telegram
URL tgram://<bot token>/<chat id>"), so a bot token or webhook secret lands in
`docker logs` and `/logs/arm-backend.log`. A filter on that logger rewrites
each URL in the message to the same `<scheme>://****` form.
"""

from __future__ import annotations

import logging
import re

APPRISE_LOGGER_NAME = "apprise"

_URL_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9+.\-]*)://[^\s'\"<>]+")


def redact_urls(text: str) -> str:
    """`text` with every `scheme://...` URL cut down to `scheme://****`."""
    return _URL_RE.sub(r"\1://****", text)


class AppriseUrlRedactor(logging.Filter):
    """Rewrites a record's rendered message with its URLs redacted; never drops the record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_urls(record.getMessage())
        record.args = None
        return True


def install_apprise_log_redaction() -> None:
    """Attach the redactor to apprise's logger once; calling again is a no-op."""
    apprise_logger = logging.getLogger(APPRISE_LOGGER_NAME)
    if not any(isinstance(f, AppriseUrlRedactor) for f in apprise_logger.filters):
        apprise_logger.addFilter(AppriseUrlRedactor())
