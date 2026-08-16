"""Token redaction for every Slack-facing log, error, and stored string.

Contract R29: a Slack token must never reach a log record, an exception
message, CLI output, or ``slack_source.last_error``. Redaction is applied
at the point of writing, not at the point of display, so a leak cannot
survive in the database.
"""

from __future__ import annotations

import re

# xoxb / xoxp / xoxa / xoxr / xoxs / xoxe, plus refresh tokens.
_TOKEN_PATTERN = re.compile(r"xox[abprse]-[A-Za-z0-9-]+", re.IGNORECASE)

REDACTED = "xox*-***REDACTED***"


def redact(text: str) -> str:
    """Replace anything token-shaped with a fixed placeholder."""
    if not text:
        return ""
    return _TOKEN_PATTERN.sub(REDACTED, str(text))
