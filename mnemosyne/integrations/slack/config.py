"""Credential and source configuration for the Slack integration.

Contract §7. Two rules shape everything here:

- R27: the bot token is read from the environment and nowhere else. The
  config file names an environment *variable*; it never holds a value.
  A config that carries a literal token is refused outright rather than
  quietly used, because accepting it would put a secret on disk.
- R30: an over-permissioned token is refused. Only ``channels:read``,
  ``channels:history``, and ``users:read`` are needed; a token that can
  also read private channels, DMs, or files is rejected before it is
  used, which enforces the public-channels-only policy at the credential
  layer as well as the ACL layer.

No token is ever returned to a caller that logs, stores, or prints it —
see :func:`mnemosyne.integrations.slack.redact.redact`, applied at every
write and output path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from mnemosyne.integrations.slack.redact import redact

DEFAULT_TOKEN_ENV = "MNEMOSYNE_SLACK_BOT_TOKEN"

#: The least privilege this integration can work with.
REQUIRED_SCOPES: tuple[str, ...] = (
    "channels:read",
    "channels:history",
    "users:read",
)

#: Scopes that must not be granted. Their presence means the token can
#: reach content this integration is contractually forbidden to touch.
FORBIDDEN_SCOPES: tuple[str, ...] = (
    "groups:history",
    "groups:read",
    "im:history",
    "im:read",
    "mpim:history",
    "mpim:read",
    "files:read",
    "chat:write",
)

CODE_CREDENTIAL_MISSING = "blocked:credential_missing"
CODE_OVERBROAD_SCOPE = "reject:overbroad_scope"
CODE_TOKEN_IN_CONFIG = "reject:token_in_config"


class SlackCredentialError(Exception):
    """The token is absent, or the config tried to carry one."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(redact(message or code))


class SlackScopeError(Exception):
    """The token grants more than this integration is allowed to hold."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(redact(message or code))


@dataclass
class SlackSourceConfig:
    team_id: str
    channel_id: str
    scope_id: str
    acl_mode: str = "require_snapshot"


@dataclass
class SlackConfig:
    token_env: str = DEFAULT_TOKEN_ENV
    sources: list[SlackSourceConfig] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Optional[dict[str, Any]]) -> "SlackConfig":
        raw = dict(data or {})

        # A config file is not a place for a secret. Refuse rather than
        # ignore: silently dropping it would leave the token on disk with
        # the operator believing it was consumed.
        for forbidden_key in ("token", "bot_token", "api_key", "secret"):
            if forbidden_key in raw:
                raise SlackCredentialError(
                    CODE_TOKEN_IN_CONFIG,
                    f"config key {forbidden_key!r} must not exist; "
                    f"use token_env with an environment variable name",
                )

        token_env = raw.get("token_env", DEFAULT_TOKEN_ENV)
        if not isinstance(token_env, str) or not token_env.strip():
            raise SlackCredentialError(
                CODE_TOKEN_IN_CONFIG, "token_env must be a variable name"
            )
        if redact(token_env) != token_env or token_env.lower().startswith("xox"):
            raise SlackCredentialError(
                CODE_TOKEN_IN_CONFIG,
                "token_env holds a token value, not a variable name",
            )

        sources = []
        for entry in raw.get("sources", []) or []:
            sources.append(
                SlackSourceConfig(
                    team_id=str(entry["team_id"]),
                    channel_id=str(entry["channel_id"]),
                    scope_id=str(entry["scope_id"]),
                    acl_mode=str(entry.get("acl_mode", "require_snapshot")),
                )
            )
        return cls(token_env=token_env, sources=sources)

    @classmethod
    def load(cls, path: str | Path) -> "SlackConfig":
        # Imported lazily so the CLI's no-config paths never load a parser.
        import yaml

        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Slack config not found: {p}")
        return cls.from_dict(yaml.safe_load(p.read_text(encoding="utf-8")) or {})

    def resolve_token(self) -> str:
        """Read the token from the environment at call time (R27/R28)."""
        value = os.environ.get(self.token_env, "").strip()
        if not value:
            raise SlackCredentialError(
                CODE_CREDENTIAL_MISSING,
                f"environment variable {self.token_env} is not set",
            )
        return value


def assert_scopes_allowed(granted: Iterable[str]) -> None:
    """Refuse a token that can reach forbidden content (R30)."""
    scopes = {s.strip() for s in granted if s and s.strip()}
    overbroad = sorted(scopes & set(FORBIDDEN_SCOPES))
    if overbroad:
        raise SlackScopeError(
            CODE_OVERBROAD_SCOPE,
            f"token grants forbidden scopes: {', '.join(overbroad)}",
        )


def parse_scope_header(header: Optional[str]) -> list[str]:
    """Split Slack's ``X-OAuth-Scopes`` comma-separated header."""
    if not header:
        return []
    return [part.strip() for part in header.split(",") if part.strip()]
