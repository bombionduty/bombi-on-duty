"""
Logging configuration.

Security rule (spec section 45): we MUST NOT log secrets. This module installs
a filter that redacts the bot token, service-account private keys, raw Telegram
initData, and task tokens if they ever appear in a log message.
"""
from __future__ import annotations

import logging
import re

from app.config import get_settings

_REDACT_PATTERNS = [
    re.compile(r"\d{6,}:[A-Za-z0-9_\-]{30,}"),       # telegram bot token
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"(initData=)[^\s&]+"),
    re.compile(r"(hash=)[a-f0-9]{32,}"),
]


class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        for pat in _REDACT_PATTERNS:
            msg = pat.sub("[REDACTED]", msg)
        record.msg = msg
        record.args = ()
        return True


def setup_logging() -> None:
    settings = get_settings()
    level = logging.DEBUG if settings.test_mode else logging.INFO
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    )
    handler.addFilter(_RedactFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Quiet noisy libraries
    for noisy in ("httpx", "apscheduler", "googleapiclient.discovery_cache"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
