import logging

import apprise
import pytest

from arm_backend.notifications import apprise_log_redaction as red

_TOKEN = "123456789:" + "A" * 35


@pytest.fixture
def clean_apprise_logger():
    apprise_logger = logging.getLogger(red.APPRISE_LOGGER_NAME)
    saved = list(apprise_logger.filters)
    for f in saved:
        apprise_logger.removeFilter(f)
    yield apprise_logger
    for f in list(apprise_logger.filters):
        apprise_logger.removeFilter(f)
    for f in saved:
        apprise_logger.addFilter(f)


def test_redact_urls_keeps_only_the_scheme() -> None:
    assert red.redact_urls(f"Unparseable Telegram URL tgram://{_TOKEN}/42?image=yes") == (
        "Unparseable Telegram URL tgram://****"
    )


def test_redact_urls_handles_several_urls_and_quotes() -> None:
    text = "a 'https://api.telegram.org/bot1:x/send' and <ntfys://user:pw@host/topic> end"
    assert red.redact_urls(text) == "a 'https://****' and <ntfys://****> end"


def test_redact_urls_leaves_text_without_urls_alone() -> None:
    assert red.redact_urls("Sent Telegram notification.") == "Sent Telegram notification."


def test_filter_renders_args_before_redacting_and_keeps_the_record() -> None:
    record = logging.LogRecord("apprise", logging.ERROR, __file__, 1, "bad url %s (%d)", (f"tgram://{_TOKEN}", 3), None)
    assert red.AppriseUrlRedactor().filter(record) is True
    assert record.getMessage() == "bad url tgram://**** (3)"
    assert record.args is None


def test_install_is_idempotent(clean_apprise_logger) -> None:
    red.install_apprise_log_redaction()
    red.install_apprise_log_redaction()
    assert sum(isinstance(f, red.AppriseUrlRedactor) for f in clean_apprise_logger.filters) == 1


def test_apprise_own_error_line_carries_no_token(clean_apprise_logger, caplog) -> None:
    """The real leak: a bot token pasted as a whole URL composes an unparseable URL, and apprise logs it verbatim."""
    red.install_apprise_log_redaction()
    caplog.set_level(logging.DEBUG, logger=red.APPRISE_LOGGER_NAME)
    assert not apprise.Apprise().add(f"tgram://tgram%3A%2F%2F{_TOKEN.replace(':', '%3A')}%2F42?image=yes")
    messages = [r.getMessage() for r in caplog.records if r.name == red.APPRISE_LOGGER_NAME]
    assert messages, "apprise logged nothing; the test no longer exercises the leak"
    assert not any("A" * 35 in m for m in messages)
