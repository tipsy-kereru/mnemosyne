"""``mnemosyne evidence search|freshness`` - local, read-only evidence search.

The store, effective caller, and app-project -> scope bindings come only from
the trusted provider configuration (``--provider-config`` or
``MNEMOSYNE_EVIDENCE_PROVIDER_CONFIG``). There is deliberately no ``--store``,
``--scope`` or ``--caller`` option.

Exit codes: 0 ok/no_matches, 2 invalid_request, 3 unauthorized, 4 unavailable,
5 timeout. The JSON response is always written to stdout.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict

from mnemosyne.evidence.search import (
    STATUS_INVALID,
    STATUS_NO_MATCHES,
    STATUS_OK,
    STATUS_TIMEOUT,
    STATUS_UNAUTHORIZED,
    STATUS_UNAVAILABLE,
    evidence_freshness,
    search_evidence,
)

PROVIDER_CONFIG_ENV = "MNEMOSYNE_EVIDENCE_PROVIDER_CONFIG"

_EXIT = {
    STATUS_OK: 0,
    STATUS_NO_MATCHES: 0,
    STATUS_INVALID: 2,
    STATUS_UNAUTHORIZED: 3,
    STATUS_UNAVAILABLE: 4,
    STATUS_TIMEOUT: 5,
}


def register_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "evidence",
        help="Read-only evidence search restricted to one authorized project",
        description=(
            "Read-only evidence search. Authority comes only from the provider "
            "configuration; requests never name a scope. Never creates or "
            "modifies the store."
        ),
    )
    verbs = parser.add_subparsers(dest="evidence_command", required=True)
    for name, help_text in (
        ("search", "Return bounded, ranked, cited excerpts for one app project"),
        ("freshness", "Return the authorization+data freshness token for one app project"),
    ):
        command = verbs.add_parser(name, help=help_text)
        command.add_argument(
            "--provider-config",
            default=os.environ.get(PROVIDER_CONFIG_ENV),
            help=f"Trusted provider configuration (default: ${PROVIDER_CONFIG_ENV})",
        )
        command.add_argument("--app-project", required=True, help="Application project key")
        command.add_argument("--timeout-ms", type=int, help="Operation deadline in milliseconds")
        if name == "search":
            command.add_argument("--query", required=True, help="Search text")
            command.add_argument("--limit", type=int, help="Maximum results")
            command.add_argument("--max-excerpt-chars", type=int, help="Maximum excerpt length")
        command.set_defaults(func=run, group="evidence")


def run(args: Any) -> None:
    request: Dict[str, Any] = {"app_project": args.app_project}
    for key in ("timeout_ms", "limit", "max_excerpt_chars"):
        value = getattr(args, key, None)
        if value is not None:
            request[key] = value
    if args.evidence_command == "search":
        request["query"] = args.query
        response = search_evidence(args.provider_config, request)
    else:
        response = evidence_freshness(args.provider_config, request)
    sys.stdout.write(json.dumps(response, ensure_ascii=False, sort_keys=True) + "\n")
    code = _EXIT.get(response["status"], 4)
    if code:
        raise SystemExit(code)
