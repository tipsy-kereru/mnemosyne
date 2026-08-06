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
    approvals:
      client-a:
        provider_privacy: true
        retention: true
        destination_acl: true
        withdrawal: true
        approver: security-reviewer
        approved_at: 2026-08-06T00:00:00Z

Secrets are referenced by *environment variable name*, never by value.
The config file stores ``api_key_env: ONYX_API_KEY``; the actual key is
read from the environment at call time and never logged. Live publication
also requires a complete, scope-bound ``approvals`` record; missing approval
fails closed after preflight and before client construction.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from mnemosyne.integrations.onyx.contract import Visibility
from mnemosyne.integrations.onyx.destinations import Destination


class ConfigError(ValueError):
    """Raised when sync configuration is malformed or incomplete."""


@dataclass
class OnyxEndpoint:
    """Connection details and outbound capability for the legacy destination."""

    base_url: str = ""
    api_key_env: str = "ONYX_API_KEY"
    cc_pair_id_env: str = "ONYX_MNEMOSYNE_CC_PAIR_ID"
    destination_classification: str = "public"
    destination_supports_acl: bool = False
    destination_supports_withdrawal: bool = False
    acl_ttl_hours: int = 24
    approved_hosts: tuple[str, ...] = ()

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
class ExportApproval:
    """Recorded operational approvals required before live publication."""

    provider_privacy: bool = False
    retention: bool = False
    destination_acl: bool = False
    withdrawal: bool = False
    approver: str = ""
    approved_at: str = ""

    def missing(self) -> tuple[str, ...]:
        required = (
            ("provider_privacy", self.provider_privacy),
            ("retention", self.retention),
            ("destination_acl", self.destination_acl),
            ("withdrawal", self.withdrawal),
            ("approver", bool(self.approver.strip())),
            ("approved_at", bool(self.approved_at.strip())),
        )
        return tuple(name for name, present in required if not present)


@dataclass
class SyncPolicy:
    """Operational parameters for the sync engine."""

    max_attempts: int = 5
    initial_backoff_seconds: float = 5.0
    backoff_multiplier: float = 2.0
    checkpoint_store: str = "sqlite"
    deletion_policy: str = "tombstone"
    reimport_generated_documents: bool = False
    preflight_ttl_hours: int = 24

@dataclass
class SyncConfig:
    """Top-level sync configuration."""

    onyx: OnyxEndpoint = field(default_factory=OnyxEndpoint)
    mappings: list[ConnectorMapping] = field(default_factory=list)
    sync: SyncPolicy = field(default_factory=SyncPolicy)
    destinations: dict[str, Destination] = field(default_factory=dict)
    scope_bindings: dict[str, str] = field(default_factory=dict)
    approvals: dict[str, ExportApproval] = field(default_factory=dict)
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
    def approval_for_scope(self, scope_id: str) -> ExportApproval:
        """Return the scope approval, defaulting to fail-closed."""
        return self.approvals.get(scope_id, ExportApproval())

    # ── Loading ──

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SyncConfig":
        version = int(data.get("version", 1))

        onyx_raw = data.get("onyx") or {}
        base_url = onyx_raw.get("base_url", "")
        if base_url.startswith("$"):
            base_url = os.environ.get(base_url[1:], base_url)
        onyx = OnyxEndpoint(
            base_url=base_url.rstrip("/"),
            api_key_env=onyx_raw.get("api_key_env", "ONYX_API_KEY"),
            cc_pair_id_env=onyx_raw.get(
                "cc_pair_id_env", "ONYX_MNEMOSYNE_CC_PAIR_ID"
            ),
            destination_classification=onyx_raw.get(
                "destination_classification", "public"
            ),
            destination_supports_acl=bool(
                onyx_raw.get("destination_supports_acl", False)
            ),
            destination_supports_withdrawal=bool(
                onyx_raw.get("destination_supports_withdrawal", False)
            ),
            acl_ttl_hours=int(onyx_raw.get("acl_ttl_hours", 24)),
            approved_hosts=tuple(onyx_raw.get("approved_hosts") or ()),
        )
        destinations: dict[str, Destination] = {}
        for destination_id, raw in (data.get("destinations") or {}).items():
            raw = raw or {}
            destination_url = raw.get("base_url", "")
            if destination_url.startswith("$"):
                destination_url = os.environ.get(
                    destination_url[1:], destination_url
                )
            destinations[destination_id] = Destination(
                destination_id=destination_id,
                base_url=destination_url.rstrip("/"),
                api_key_env=raw.get("api_key_env", "ONYX_API_KEY"),
                cc_pair_id_env=raw.get(
                    "cc_pair_id_env", "ONYX_MNEMOSYNE_CC_PAIR_ID"
                ),
                classification_ceiling=raw.get(
                    "classification_ceiling", "public"
                ),
                supports_acl=bool(raw.get("supports_acl", False)),
                supports_withdrawal=bool(
                    raw.get("supports_withdrawal", False)
                ),
                acl_ttl_hours=int(raw.get("acl_ttl_hours", 24)),
                approved_hosts=tuple(raw.get("approved_hosts") or ()),
            )
        bindings: dict[str, str] = {}
        for raw in data.get("scope_bindings") or []:
            if isinstance(raw, dict) and raw.get("scope_id") and raw.get(
                "destination"
            ):
                bindings[raw["scope_id"]] = raw["destination"]
        if not destinations:
            destinations["default"] = Destination(
                destination_id="default",
                base_url=onyx.base_url,
                api_key_env=onyx.api_key_env,
                cc_pair_id_env=onyx.cc_pair_id_env,
                classification_ceiling=onyx.destination_classification,
                supports_acl=onyx.destination_supports_acl,
                supports_withdrawal=onyx.destination_supports_withdrawal,
                acl_ttl_hours=onyx.acl_ttl_hours,
                approved_hosts=onyx.approved_hosts,
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

        approvals: dict[str, ExportApproval] = {}
        for scope_id, raw in (data.get("approvals") or {}).items():
            if not isinstance(raw, dict):
                raise ConfigError(
                    f"approval for scope {scope_id!r} must be a mapping"
                )
            approvals[scope_id] = ExportApproval(
                provider_privacy=bool(raw.get("provider_privacy", False)),
                retention=bool(raw.get("retention", False)),
                destination_acl=bool(raw.get("destination_acl", False)),
                withdrawal=bool(raw.get("withdrawal", False)),
                approver=str(raw.get("approver", "")),
                approved_at=str(raw.get("approved_at", "")),
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
            preflight_ttl_hours=int(sync_raw.get("preflight_ttl_hours", 24)),
        )

        return cls(
            onyx=onyx,
            mappings=mappings,
            sync=sync,
            destinations=destinations,
            scope_bindings=bindings,
            approvals=approvals,
            version=version,
        )

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
