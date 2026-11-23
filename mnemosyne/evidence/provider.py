"""Trusted provider configuration for read-only evidence search.

The provider configuration is the ONLY source of authority. It names the store,
the effective caller, and the grants that bind ``(caller, app_project)`` to one
exact scope. Nothing in a request (scope name, scope ID, caller hint) can widen
or substitute that binding; the request vocabulary does not even admit them.

The file is re-read on every operation. Grant changes therefore take effect on
the next call, and the effective grant is folded into the authorization token
(see :func:`authorization_token`).

Schema (``version`` 1)::

    {
      "version": 1,
      "store": "knowledge.db",              # relative to this file
      "effective_caller": "meeting-assistant",
      "grants": [
        {"grant_id": "g-1", "caller": "meeting-assistant",
         "app_project": "weekly-sync", "scope_id": "scope-weekly",
         "status": "active"}                 # or "revoked"
      ]
    }
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Tuple

CONFIG_VERSION = 1
MAX_CONFIG_BYTES = 1 << 20
MAX_IDENT_CHARS = 256

STATUS_ACTIVE = "active"
STATUS_REVOKED = "revoked"

_TOP_KEYS = {"version", "store", "effective_caller", "grants"}
_GRANT_KEYS = {"grant_id", "caller", "app_project", "scope_id", "status"}


class ProviderConfigError(Exception):
    """Provider configuration is absent or not trustworthy."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


class AuthorizationDenied(Exception):
    """The effective caller has no usable binding for the requested app project."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class Grant:
    grant_id: str
    caller: str
    app_project: str
    scope_id: str
    status: str


@dataclass(frozen=True)
class ProviderConfig:
    store_path: Path
    effective_caller: str
    grants: Tuple[Grant, ...]


@dataclass(frozen=True)
class Binding:
    """The one exact scope the effective caller may read for an app project."""

    caller: str
    app_project: str
    scope_id: str
    grant_ids: Tuple[str, ...]
    store_path: Path


def _ident(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > MAX_IDENT_CHARS
        or any(ord(ch) < 0x20 for ch in value)
    ):
        raise ProviderConfigError(
            "provider_config_invalid", f"{field} must be a trimmed, nonempty string"
        )
    return value


def load_provider_config(path: "str | os.PathLike[str] | None") -> ProviderConfig:
    """Load and strictly validate the provider configuration, or raise."""
    if path is None or str(path) == "":
        raise ProviderConfigError("provider_config_missing", "no provider configuration supplied")
    cfg_path = Path(path)
    try:
        st = cfg_path.stat()
    except FileNotFoundError:
        raise ProviderConfigError(
            "provider_config_missing", "provider configuration not found"
        ) from None
    except OSError as exc:
        raise ProviderConfigError(
            "provider_config_invalid", f"provider configuration unreadable: {exc.strerror}"
        ) from None
    if not stat.S_ISREG(st.st_mode):
        raise ProviderConfigError("provider_config_invalid", "provider configuration is not a file")
    if st.st_size > MAX_CONFIG_BYTES:
        raise ProviderConfigError("provider_config_invalid", "provider configuration too large")
    if os.name == "posix" and st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise ProviderConfigError(
            "provider_config_invalid", "provider configuration is group/world writable"
        )
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        raise ProviderConfigError(
            "provider_config_invalid", "provider configuration is not valid JSON"
        ) from None
    if not isinstance(raw, dict) or set(raw) - _TOP_KEYS:
        raise ProviderConfigError("provider_config_invalid", "unexpected provider configuration")
    if raw.get("version") != CONFIG_VERSION or isinstance(raw.get("version"), bool):
        raise ProviderConfigError("provider_config_invalid", "unsupported configuration version")
    store = raw.get("store")
    if not isinstance(store, str) or not store:
        raise ProviderConfigError("provider_config_invalid", "store must be a nonempty path")
    store_path = Path(store).expanduser()
    if not store_path.is_absolute():
        store_path = cfg_path.resolve().parent / store_path
    caller = _ident(raw.get("effective_caller"), "effective_caller")
    grants_raw = raw.get("grants")
    if not isinstance(grants_raw, list):
        raise ProviderConfigError("provider_config_invalid", "grants must be an array")
    grants = []
    seen_ids = set()
    for item in grants_raw:
        if not isinstance(item, Mapping) or set(item) != _GRANT_KEYS:
            raise ProviderConfigError("provider_config_invalid", "malformed grant")
        grant = Grant(
            grant_id=_ident(item["grant_id"], "grant_id"),
            caller=_ident(item["caller"], "caller"),
            app_project=_ident(item["app_project"], "app_project"),
            scope_id=_ident(item["scope_id"], "scope_id"),
            status=_ident(item["status"], "status"),
        )
        if grant.status not in (STATUS_ACTIVE, STATUS_REVOKED):
            raise ProviderConfigError("provider_config_invalid", "unknown grant status")
        if grant.grant_id in seen_ids:
            raise ProviderConfigError("provider_config_invalid", "duplicate grant_id")
        seen_ids.add(grant.grant_id)
        grants.append(grant)
    return ProviderConfig(store_path=store_path, effective_caller=caller, grants=tuple(grants))


def resolve_binding(config: ProviderConfig, app_project: str) -> Binding:
    """Resolve the exact scope for ``app_project`` or raise :class:`AuthorizationDenied`.

    Active grants naming more than one distinct scope are ambiguous and denied;
    a revoked grant without an active replacement is denied as revoked; no grant
    at all is unbound.
    """
    matching = [
        g
        for g in config.grants
        if g.caller == config.effective_caller and g.app_project == app_project
    ]
    active = [g for g in matching if g.status == STATUS_ACTIVE]
    if not active:
        if matching:
            raise AuthorizationDenied("revoked", "the grant for this app project was revoked")
        raise AuthorizationDenied("unbound", "no grant binds this app project to a scope")
    scopes = {g.scope_id for g in active}
    if len(scopes) != 1:
        raise AuthorizationDenied("ambiguous", "the app project maps to more than one scope")
    return Binding(
        caller=config.effective_caller,
        app_project=app_project,
        scope_id=next(iter(scopes)),
        grant_ids=tuple(sorted(g.grant_id for g in active)),
        store_path=config.store_path,
    )


def authorization_token(binding: Binding) -> str:
    """Digest of exactly what the authorization decision depends on."""
    canonical = json.dumps(
        {
            "caller": binding.caller,
            "app_project": binding.app_project,
            "scope_id": binding.scope_id,
            "grants": list(binding.grant_ids),
            "store": str(binding.store_path),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

