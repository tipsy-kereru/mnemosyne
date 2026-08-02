"""Sync configuration for the Onyx ↔ Mnemosyne integration.

Loads the YAML configuration described in §7 of the integration plan:

    version: 1
    onyx:
      base_url: $ONYX_BASE_URL
      api_key_env: ONYX_API_KEY
      ingestion_cc_pair_id_env: ONYX_MNEMOSYNE_CC_PAIR_ID
    mappings:
      - connector_id: client-a-github
        scope_id: client-a
        ...
    sync:
      max_attempts: 5
      initial_backoff_seconds: 5
      checkpoint_store: sqlite
      deletion_policy: tombstone
      reimport_generated_documents: false

Secrets are referenced by *environment variable name*, never by value.
The config file stores ``api_key_env: ONYX_API_KEY``; the actual key is
read from the environment at call time and never logged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from mnemosyne.integrations.onyx.contract import Visibility


class ConfigError(ValueError):
    """Raised when sync configuration is malformed or incomplete."""


@dataclass
class OnyxEndpoint:
    """Connection details for the Onyx instance.

    ``api_key_env`` and ``cc_pair_id_env`` hold the *names* of
    environment variables; the values are resolved lazily via
    :meth:`resolve_api_key` / :meth:`resolve_cc_pair_id`.
    """

    base_url: str = ""
    api_key_env: str = "ONYX_API_KEY"
    cc_pair_id_env: str = "ONYX_MNEMOSYNE_CC_PAIR_ID"

    def resolve_api_key(self) -> str:
        val = os.environ.get(self.api_key_env, "")
        if not val:
            raise ConfigError(
                f"API key environment variable {self.api_key_env!r} is not set"
            )
        return val

    def resolve_cc_pair_id(self) -> int:
        raw = os.environ.get(self.cc_pair_id_env, "")
        if not raw:
            raise ConfigError(
                f"CC pair ID environment variable "
                f"{self.cc_pair_id_env!r} is not set"
            )
        try:
            return int(raw)
        except ValueError:
            raise ConfigError(
                f"CC pair ID {raw!r} from {self.cc_pair_id_env!r} "
                f"is not an integer"
            ) from None


@dataclass
class ConnectorMapping:
    """Maps an Onyx connector to a Mnemosyne scope."""

    connector_id: str
    scope_id: str
    source_channel: str
    default_classification: str = "internal"
    acl_mode: str = "require_snapshot"  # require_snapshot | owner_only | open
    visibility: Visibility = Visibility.PROJECT


@dataclass
class SyncPolicy:
    """Operational parameters for the sync engine."""

    max_attempts: int = 5
    initial_backoff_seconds: float = 5.0
    backoff_multiplier: float = 2.0
    checkpoint_store: str = "sqlite"          # sqlite | json
    deletion_policy: str = "tombstone"        # tombstone (only safe option)
    reimport_generated_documents: bool = False


@dataclass
class SyncConfig:
    """Top-level sync configuration."""

    onyx: OnyxEndpoint = field(default_factory=OnyxEndpoint)
    mappings: list[ConnectorMapping] = field(default_factory=list)
    sync: SyncPolicy = field(default_factory=SyncPolicy)
    version: int = 1

    # ── Lookup ──

    def mapping_for_connector(
        self, connector_id: str
    ) -> Optional[ConnectorMapping]:
        """Find the scope mapping for a connector, or None."""
        for m in self.mappings:
            if m.connector_id == connector_id:
                return m
        return None

    def mapping_for_scope(self, scope_id: str) -> Optional[ConnectorMapping]:
        """Find the first connector mapping for a scope."""
        for m in self.mappings:
            if m.scope_id == scope_id:
                return m
        return None

    # ── Loading ──

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SyncConfig":
        version = int(data.get("version", 1))

        onyx_raw = data.get("onyx") or {}
        # base_url may reference an env var with $NAME; expand it.
        base_url = onyx_raw.get("base_url", "")
        if base_url.startswith("$"):
            base_url = os.environ.get(base_url[1:], base_url)
        onyx = OnyxEndpoint(
            base_url=base_url.rstrip("/"),
            api_key_env=onyx_raw.get("api_key_env", "ONYX_API_KEY"),
            cc_pair_id_env=onyx_raw.get(
                "cc_pair_id_env", "ONYX_MNEMOSYNE_CC_PAIR_ID"
            ),
        )

        mappings: list[ConnectorMapping] = []
        for raw in data.get("mappings") or []:
            vis = raw.get("visibility", "project")
            if isinstance(vis, str):
                vis = Visibility(vis)
            mappings.append(
                ConnectorMapping(
                    connector_id=raw["connector_id"],
                    scope_id=raw["scope_id"],
                    source_channel=raw.get("source_channel", ""),
                    default_classification=raw.get(
                        "default_classification", "internal"
                    ),
                    acl_mode=raw.get("acl_mode", "require_snapshot"),
                    visibility=vis,
                )
            )

        sync_raw = data.get("sync") or {}
        sync = SyncPolicy(
            max_attempts=int(sync_raw.get("max_attempts", 5)),
            initial_backoff_seconds=float(
                sync_raw.get("initial_backoff_seconds", 5.0)
            ),
            backoff_multiplier=float(sync_raw.get("backoff_multiplier", 2.0)),
            checkpoint_store=sync_raw.get("checkpoint_store", "sqlite"),
            deletion_policy=sync_raw.get("deletion_policy", "tombstone"),
            reimport_generated_documents=bool(
                sync_raw.get("reimport_generated_documents", False)
            ),
        )

        return cls(onyx=onyx, mappings=mappings, sync=sync, version=version)

    @classmethod
    def load(cls, path: str | Path) -> "SyncConfig":
        """Load configuration from a YAML file."""
        p = Path(path)
        if not p.is_file():
            raise ConfigError(f"Sync config not found: {p}")
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ConfigError(f"Sync config root must be a mapping: {p}")
        return cls.from_dict(raw)
