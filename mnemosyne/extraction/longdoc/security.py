"""SPEC-LONGDOC-001 REQ-LD-008 (partial): path-traversal guard.

Shared validator used by ``LongDocIndexer`` to reject file paths that escape
the raw directory: ``..`` segments or absolute paths not nested under the
configured raw root. Full security review (memory bounds, >1000-page reject)
lands in the mandatory REVIEW phase per SPEC-LONGDOC-001 §10.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote


class LongDocPathError(ValueError):
    """Raised when a long-doc source path fails the traversal guard."""


def validate_longdoc_path(path: "str | Path", raw_root: "str | Path") -> Path:
    """Validate that *path* resolves inside *raw_root*.

    Returns the resolved ``Path``. Raises ``LongDocPathError`` on:
        - any ``..`` segment in the input (before resolution)
        - the input being absolute AND not under *raw_root*
        - the resolved real path escaping *raw_root* after symlink expansion

    The lexical ``..`` guard is hardened against:
        - percent-encoded escapes (``%2e%2e``) via ``urllib.parse.unquote``
        - Windows-style backslash separators (``..\\..\\``) via normalization

    REQ-LD-008 partial. The full streaming / OOM hardening is REVIEW-phase.
    """
    if not isinstance(path, Path):
        path = Path(path)
    if not isinstance(raw_root, Path):
        raw_root = Path(raw_root)

    # Cheap lexical guard: reject explicit parent-segment escapes regardless
    # of how they resolve. ``os.path.normpath`` collapses them; we inspect the
    # raw parts so an attempt is never silently normalised away. Harden against
    # percent-encoding (%2e%2e) and Windows backslash separators so the guard
    # is not bypassed by alternate encodings of the same intent.
    decoded = unquote(str(path))
    normalized = decoded.replace("\\", "/")
    for part in Path(normalized).parts:
        if part == "..":
            raise LongDocPathError(
                f"Rejected long-doc path containing '..': {path}"
            )

    # Absolute paths must be anchored under raw_root.
    if path.is_absolute():
        try:
            resolved_root = raw_root.resolve()
        except OSError:
            resolved_root = raw_root
        try:
            resolved = path.resolve()
        except OSError as exc:
            raise LongDocPathError(
                f"Cannot resolve long-doc path {path}: {exc}"
            ) from exc
        try:
            resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise LongDocPathError(
                f"Long-doc path {path} is outside raw root {raw_root}"
            ) from exc
        return resolved

    # Relative paths are taken as raw-root-relative.
    return raw_root / path


# ---------------------------------------------------------------------------
# Minimal secret redaction (REVIEW-phase finding: redaction-missing)
# ---------------------------------------------------------------------------

# Stdlib-only patterns matching common credential shapes. Idempotent and never
# raises on malformed input. Deliberately conservative: redacts recognizable
# credential carriers without rewriting arbitrary free text.
_REDACT_PATTERNS: list[tuple["re.Pattern[str]", str]] = [
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        "[REDACTED:private-key]",
    ),
    (re.compile(r"gh[ps]_[A-Za-z0-9]{36,}"), "[REDACTED:github-token]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED:aws-key]"),
    (re.compile(r"whsec_[A-Za-z0-9]+"), "[REDACTED:webhook]"),
    (
        re.compile(r"(postgres(?:ql)?://)([^:]+):([^@]+)@"),
        r"\1[REDACTED:user-pass]@",
    ),
    (
        re.compile(
            r"(?i)(?:api[_-]?key|bearer|token|authorization)[\"'\s:=]+[A-Za-z0-9_\-\.]{20,}"
        ),
        "[REDACTED:api-key]",
    ),
    (
        re.compile(
            r"(?m)^([A-Z_]*(?:SECRET|TOKEN|KEY|PASSWORD|API_KEY)[=:])(.+)$"
        ),
        r"\1[REDACTED:value]",
    ),
    (
        re.compile(
            r"(?i)(session[_-]?id|csrf[_-]?token|connect\.sid|_session)=[A-Za-z0-9_\-\.]{16,}"
        ),
        "[REDACTED:cookie]",
    ),
]


def redact(text: "str | None") -> str:
    """Redact common secret patterns from *text*.

    REVIEW-phase mitigation: ``raw_excerpt`` and ``entity_refs`` are new
    write paths accepting effectively user-controlled content. Redacting
    recognisable credentials before persisting keeps secret-like substrings
    out of the retrievable ``tree_nodes`` columns. Idempotent and safe on
    ``None`` (returns empty string).
    """
    if not text or not isinstance(text, str):
        return ""
    out = text
    for pattern, replacement in _REDACT_PATTERNS:
        out = pattern.sub(replacement, out)
    return out
