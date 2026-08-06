"""Scope-bound, fail-closed outbound destination configuration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from mnemosyne.integrations.onyx.config import SyncConfig
    from mnemosyne.integrations.onyx.mapper import DestinationPolicy


@dataclass(frozen=True)
class Destination:
    """One approved outbound destination; secrets are never stored."""

    destination_id: str
    base_url: str
    api_key_env: str
    cc_pair_id_env: str
    classification_ceiling: str = "public"
    supports_acl: bool = False
    supports_withdrawal: bool = False
    acl_ttl_hours: int = 24
    approved_hosts: tuple[str, ...] = ()

    def policy(self) -> "DestinationPolicy":
        from mnemosyne.integrations.onyx.mapper import DestinationPolicy

        return DestinationPolicy(
            destination_id=self.destination_id,
            classification_ceiling=self.classification_ceiling,
            supports_acl=self.supports_acl,
            supports_withdrawal=self.supports_withdrawal,
            acl_ttl_hours=self.acl_ttl_hours,
        )

    @property
    def host(self) -> str:
        return urlparse(self.base_url).hostname or ""

    def fingerprint(self) -> str:
        """Hash non-secret destination settings only."""
        payload = {
            "destination_id": self.destination_id,
            "host": self.host,
            "api_key_env": self.api_key_env,
            "cc_pair_id_env": self.cc_pair_id_env,
            "classification_ceiling": self.classification_ceiling,
            "supports_acl": self.supports_acl,
            "supports_withdrawal": self.supports_withdrawal,
            "acl_ttl_hours": self.acl_ttl_hours,
            "approved_hosts": sorted(self.approved_hosts),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


class DestinationNotBound(ValueError):
    """Raised when a scope has no explicit outbound destination binding."""


class DestinationRegistry:
    def __init__(
        self, destinations: dict[str, Destination], bindings: dict[str, str]
    ) -> None:
        self._destinations = dict(destinations)
        self._bindings = dict(bindings)

    @classmethod
    def from_config(cls, cfg: "SyncConfig") -> "DestinationRegistry":
        return cls(cfg.destinations, cfg.scope_bindings)

    def for_scope(self, scope_id: str) -> Destination:
        destination_id = self._bindings.get(scope_id)
        if not destination_id or destination_id not in self._destinations:
            raise DestinationNotBound(
                f"deny:destination_unbound: scope={scope_id}"
            )
        return self._destinations[destination_id]
