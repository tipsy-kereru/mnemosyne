"""Local, read-only, exact-scope evidence search.

Contract (``mnemosyne.evidence-search/1``)
-----------------------------------------
* Authority comes only from the trusted provider configuration
  (:mod:`mnemosyne.evidence.provider`). The request carries an ``app_project``
  key; it never carries a scope, scope ID, or caller. Missing, ambiguous,
  unauthorized, and revoked bindings are denied before the store is opened.
* The candidate set is ``entities WHERE scope_id = <bound scope>`` (plus the
  unconditional isolated-channel exclusion). Global (NULL), parent, child, and
  sibling scopes are never read. Ranking runs over that set only, with
  corpus statistics (document count, document frequency, average length)
  derived from that set alone, so other scopes cannot influence scores or order.
* Excerpts and provenance are built from the same exact-scope rows. Lifecycle
  provenance entries are additionally verified against ``lifecycle_sources``
  for the bound scope and dropped otherwise.
* The store is opened read-only without creating or modifying any file
  (:mod:`mnemosyne.evidence.store`); results are never persisted or cached.
* ``status`` is one of ``ok``, ``no_matches``, ``unauthorized``,
  ``unavailable``, ``timeout``, ``invalid_request``.

Freshness contract (``mnemosyne.evidence-freshness/1``)
------------------------------------------------------
Every response carries ``freshness``. ``freshness.token`` is a SHA-256 over

* the authorization token: caller, app project, bound scope, active grant IDs,
  and store path, all taken from the provider configuration re-read on this
  call; and
* the data token: a digest of every row of the bound scope that search can see
  (ID, type, name, properties, version, updated_at), the scope row, the
  lifecycle source set for the scope. It is computed inside the same read
  snapshot as the results. The store-wide lifecycle generation is reported for
  diagnostics but deliberately excluded: it also moves on writes to other
  scopes, which cannot change this scope's evidence.

A client may serve a cached result for ``(query, limits)`` only if a fresh call
of the ``freshness`` operation returns ``status == "ok"``, ``cacheable`` true,
and a token equal to the one stored with the cached result. A changed grant,
edit, or deletion changes the token. Any non-``ok``/``no_matches`` status, or
``cacheable == false``, means: drop the cached entry and bypass caching.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from mnemosyne.evidence.provider import (
    AuthorizationDenied,
    Binding,
    ProviderConfigError,
    authorization_token,
    load_provider_config,
    resolve_binding,
)
from mnemosyne.evidence.store import (
    Deadline,
    SearchTimeout,
    Snapshot,
    StoreUnavailable,
    check_schema,
    close_snapshot,
    open_snapshot,
    translate_error,
    verify_unchanged,
)

CONTRACT = "mnemosyne.evidence-search/1"
FRESHNESS_CONTRACT = "mnemosyne.evidence-freshness/1"

STATUS_OK = "ok"
STATUS_NO_MATCHES = "no_matches"
STATUS_UNAUTHORIZED = "unauthorized"
STATUS_UNAVAILABLE = "unavailable"
STATUS_TIMEOUT = "timeout"
STATUS_INVALID = "invalid_request"

DEFAULT_LIMIT, MAX_LIMIT = 5, 20
DEFAULT_EXCERPT_CHARS, MIN_EXCERPT_CHARS, MAX_EXCERPT_CHARS = 400, 40, 1200
DEFAULT_TIMEOUT_MS, MIN_TIMEOUT_MS, MAX_TIMEOUT_MS = 2000, 50, 10000
MAX_QUERY_CHARS = 256
MAX_QUERY_TERMS = 16
MAX_APP_PROJECT_CHARS = 256
MAX_RESPONSE_BYTES = 65536
_RESULT_BUDGET_BYTES = MAX_RESPONSE_BYTES - 4096
MAX_PROVENANCE = 5
MAX_FIELD_CHARS = 200
MAX_NAME_CHARS = 200

_SEARCH_KEYS = {"app_project", "query", "limit", "max_excerpt_chars", "timeout_ms"}
_FRESHNESS_KEYS = {"app_project", "timeout_ms"}

# Property keys that hold bookkeeping, not searchable content.
_SKIP_PROPERTY_KEYS = frozenset(
    {
        "evidence", "source_files", "source_file", "conflicts", "corrections",
        "review_required", "tombstoned_at", "valid_to", "tombstone_reason",
    }
)
_NAME_WEIGHT = 3
_K1, _B = 1.2, 0.75
_WORD = re.compile(r"\w+", re.UNICODE)
_CJK = re.compile(r"[\u1100-\u11ff\u3040-\u30ff\u3130-\u318f\u3400-\u9fff\uac00-\ud7af]")
_LEGACY_SOURCE = "legacy:unattributed"


class InvalidRequest(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class EvidenceRequest:
    app_project: str
    query: str
    limit: int
    max_excerpt_chars: int
    timeout_ms: int
    terms: Tuple[str, ...]


def _bounded_int(raw: Mapping[str, Any], key: str, default: int, lo: int, hi: int) -> int:
    if key not in raw:
        return default
    value = raw[key]
    if type(value) is not int or not lo <= value <= hi:
        raise InvalidRequest(f"{key} must be an integer between {lo} and {hi}")
    return value


def tokenize(text: str) -> List[str]:
    return [m.group().lower() for m in _WORD.finditer(text)]


def parse_request(raw: Any, *, with_query: bool) -> EvidenceRequest:
    if not isinstance(raw, Mapping):
        raise InvalidRequest("request must be an object")
    allowed = _SEARCH_KEYS if with_query else _FRESHNESS_KEYS
    unknown = sorted(str(k) for k in raw if k not in allowed)
    if unknown:
        shown = ", ".join(name[:40] for name in unknown[:5])
        more = f" (+{len(unknown) - 5} more)" if len(unknown) > 5 else ""
        raise InvalidRequest(
            f"unsupported request fields: {shown}{more}"
            " (scope and caller come only from the provider configuration)"
        )
    app_project = raw.get("app_project")
    if (
        not isinstance(app_project, str)
        or not app_project
        or len(app_project) > MAX_APP_PROJECT_CHARS
        or app_project != app_project.strip()
    ):
        raise InvalidRequest("app_project must be a trimmed, nonempty string")
    query: str = ""
    terms: Tuple[str, ...] = ()
    limit, excerpt = DEFAULT_LIMIT, DEFAULT_EXCERPT_CHARS
    if with_query:
        query = raw.get("query")  # type: ignore[assignment]
        if not isinstance(query, str) or not query.strip():
            raise InvalidRequest("query must be a nonempty string")
        if len(query) > MAX_QUERY_CHARS:
            raise InvalidRequest(f"query exceeds {MAX_QUERY_CHARS} characters")
        seen: Dict[str, None] = {}
        for token in tokenize(query):
            seen.setdefault(token)
        if not seen:
            raise InvalidRequest("query has no searchable terms")
        if len(seen) > MAX_QUERY_TERMS:
            raise InvalidRequest(f"query exceeds {MAX_QUERY_TERMS} distinct terms")
        terms = tuple(seen)
        limit = _bounded_int(raw, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        excerpt = _bounded_int(
            raw, "max_excerpt_chars", DEFAULT_EXCERPT_CHARS, MIN_EXCERPT_CHARS, MAX_EXCERPT_CHARS
        )
    timeout_ms = _bounded_int(raw, "timeout_ms", DEFAULT_TIMEOUT_MS, MIN_TIMEOUT_MS, MAX_TIMEOUT_MS)
    return EvidenceRequest(app_project, query, limit, excerpt, timeout_ms, terms)


# ---------------------------------------------------------------------------
# Documents, matching, ranking
# ---------------------------------------------------------------------------


def _term_matches(token: str, term: str) -> bool:
    if _CJK.search(term):
        return term in token
    return token.startswith(term)


@dataclass
class _Segment:
    label: str
    text: str
    weight: int


def _flatten(value: Any, path: str, out: List[Tuple[str, str]], depth: int) -> None:
    if isinstance(value, str):
        if value.strip():
            out.append((path, value))
    elif isinstance(value, bool) or value is None:
        return
    elif isinstance(value, (int, float)):
        out.append((path, str(value)))
    elif depth < 4 and isinstance(value, Mapping):
        for key in sorted(value, key=str):
            if depth == 0 and key in _SKIP_PROPERTY_KEYS:
                continue
            _flatten(value[key], f"{path}.{key}" if path else str(key), out, depth + 1)
    elif depth < 4 and isinstance(value, list):
        for index, item in enumerate(value[:200]):
            _flatten(item, f"{path}[{index}]", out, depth + 1)


class _Verifier:
    """Proves that a provenance entry belongs to the bound scope.

    A lifecycle source is trusted only if ``lifecycle_sources`` lists it for the
    bound scope. The reserved legacy source is trusted only for an entity that
    has a ``lifecycle_legacy`` backing record AND lives in the bound scope.
    """

    def __init__(self, conn: sqlite3.Connection, scope_id: str, sources: Set[str]) -> None:
        self._conn = conn
        self._scope_id = scope_id
        self._sources = sources
        self._legacy: Dict[str, bool] = {}

    def allows(self, entity_id: str, source_id: str) -> bool:
        if source_id in self._sources:
            return True
        if source_id != _LEGACY_SOURCE:
            return False
        if entity_id not in self._legacy:
            row = self._conn.execute(
                "SELECT 1 FROM lifecycle_legacy l JOIN entities e ON e.id = l.target_id "
                "WHERE l.kind = 'entity' AND l.target_id = ? AND e.scope_id = ?",
                (entity_id, self._scope_id),
            ).fetchone()
            self._legacy[entity_id] = row is not None
        return self._legacy[entity_id]


def _verified_evidence(
    entity_id: str, props: Mapping[str, Any], verifier: Optional[_Verifier]
) -> List[Mapping[str, Any]]:
    """Evidence entries whose source is provably in the bound scope."""
    if verifier is None:
        return []
    evidence = props.get("evidence")
    if not isinstance(evidence, list):
        return []
    out = []
    for item in evidence[:200]:
        if (
            isinstance(item, Mapping)
            and isinstance(item.get("source_id"), str)
            and verifier.allows(entity_id, item["source_id"])
        ):
            out.append(item)
    return out


def _segments(
    entity_id: str, name: str, props: Mapping[str, Any], verifier: Optional[_Verifier]
) -> List[_Segment]:
    segments = [_Segment("name", name, _NAME_WEIGHT)]
    leaves: List[Tuple[str, str]] = []
    _flatten(props, "", leaves, 0)
    segments.extend(_Segment(f"properties.{p}", t, 1) for p, t in leaves)
    for index, item in enumerate(_verified_evidence(entity_id, props, verifier)):
        excerpt = item.get("excerpt")
        if isinstance(excerpt, str) and excerpt.strip():
            segments.append(_Segment(f"evidence[{index}].excerpt", excerpt, 1))
    return segments


def _parse_properties(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


@dataclass
class _Match:
    entity_id: str
    tf: List[float]
    length: float


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _window(text: str, pos: int, limit: int) -> str:
    if len(text) <= limit:
        return text
    start = max(0, pos - limit // 4)
    if start + limit >= len(text):
        start = max(0, len(text) - limit)
    body = text[start : start + limit]
    if start > 0:
        body = "\u2026" + body[1:]
    if start + limit < len(text):
        body = body[:-1] + "\u2026"
    return body


def _best_excerpt(
    segments: Sequence[_Segment], terms: Sequence[str], limit: int
) -> Tuple[str, str]:
    best: Optional[Tuple[int, int, str, int]] = None  # (distinct, -index, label, pos)
    chosen: Optional[Tuple[str, str, int]] = None
    for index, seg in enumerate(segments):
        text = _collapse(seg.text)
        hit_terms: Set[str] = set()
        first = -1
        for m in _WORD.finditer(text):
            token = m.group().lower()
            for term in terms:
                if _term_matches(token, term):
                    hit_terms.add(term)
                    if first < 0:
                        first = m.start()
        if not hit_terms:
            continue
        key = (len(hit_terms), -index, seg.label, first)
        if best is None or key[:2] > best[:2]:
            best = key
            chosen = (seg.label, text, first)
    if chosen is None:
        seg = segments[0]
        return seg.label, _window(_collapse(seg.text), 0, limit)
    label, text, pos = chosen
    return label, _window(text, pos, limit)


def _clip(value: Any, limit: int = MAX_FIELD_CHARS) -> Optional[str]:
    if not isinstance(value, str):
        return None
    return value if len(value) <= limit else value[: limit - 1] + "\u2026"


def _provenance(
    entity_id: str, props: Mapping[str, Any], verifier: Optional["_Verifier"]
) -> Tuple[List[Dict[str, Any]], List[str]]:
    entries: List[Dict[str, Any]] = []
    for item in _verified_evidence(entity_id, props, verifier):
        revision = item.get("revision")
        entries.append(
            {
                "source_id": _clip(item["source_id"]),
                "revision": revision if type(revision) is int else None,
                "location": _clip(item.get("location")),
                "locator": _clip(item.get("locator")),
            }
        )
    entries.sort(key=lambda e: (e["source_id"] or "", e["revision"] or 0, e["locator"] or ""))
    source_ids = sorted({e["source_id"] for e in entries if e["source_id"]})
    return entries[:MAX_PROVENANCE], source_ids


# ---------------------------------------------------------------------------
# Digest helpers
# ---------------------------------------------------------------------------


def _feed(digest: "hashlib._Hash", *parts: object) -> None:
    for part in parts:
        data = b"\x00" if part is None else str(part).encode("utf-8", "surrogatepass")
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Scoped read
# ---------------------------------------------------------------------------


@dataclass
class _ScopedRead:
    data_token: str
    doc_count: int
    matches: List[_Match] = field(default_factory=list)
    results: List[Dict[str, Any]] = field(default_factory=list)
    total_matches: int = 0
    truncated: bool = False


def _isolation() -> Tuple[str, List[str]]:
    from mnemosyne.graph.knowledge_graph import ISOLATED_SOURCE_CHANNELS

    channels = sorted(ISOLATED_SOURCE_CHANNELS)
    marks = ",".join("?" * len(channels))
    return f"(source_channel IS NULL OR source_channel NOT IN ({marks}))", channels


def _scoped_read(
    snapshot: Snapshot, binding: Binding, request: Optional[EvidenceRequest], deadline: Deadline
) -> _ScopedRead:
    conn = snapshot.conn
    try:
        has_lifecycle = check_schema(conn)
        scope_rows = conn.execute("SELECT * FROM scopes WHERE id = ?", (binding.scope_id,)).fetchall()
        if len(scope_rows) != 1:
            raise StoreUnavailable(
                "scope_unavailable", "the authorized scope does not exist in the store"
            )
        digest = hashlib.sha256()
        scope_row = scope_rows[0]
        for column in sorted(scope_row.keys()):
            _feed(digest, "scope", column, scope_row[column])

        verifier: Optional[_Verifier] = None
        iso_sql, iso_params = _isolation()
        if has_lifecycle:
            sources: Set[str] = set()
            for src in conn.execute(
                "SELECT source_id, revision, applied_revision, state, applied_digest "
                f"FROM lifecycle_sources WHERE scope_id = ? AND {iso_sql} ORDER BY source_id",
                [binding.scope_id, *iso_params],
            ):
                sources.add(src[0])
                _feed(digest, "source", *tuple(src))
            verifier = _Verifier(conn, binding.scope_id, sources)

        read = _ScopedRead(data_token="", doc_count=0)
        terms = request.terms if request else ()
        total_len = 0.0
        df = [0] * len(terms)
        cursor = conn.execute(
            "SELECT id, type, name, properties, version, updated_at FROM entities "
            f"WHERE scope_id = ? AND {iso_sql} ORDER BY id",
            [binding.scope_id, *iso_params],
        )
        for count, row in enumerate(cursor):
            if count & 127 == 0:
                deadline.check()
            _feed(
                digest, "entity", row["id"], row["type"], row["name"], row["properties"],
                row["version"], row["updated_at"],
            )
            if not terms:
                continue
            props = _parse_properties(row["properties"])
            if "tombstoned_at" in props:
                continue
            segments = _segments(str(row["id"]), str(row["name"]), props, verifier)
            read.doc_count += 1
            counts: Dict[str, float] = {}
            length = 0.0
            for seg in segments:
                for token in tokenize(seg.text):
                    counts[token] = counts.get(token, 0.0) + seg.weight
                    length += seg.weight
            for token in tokenize(str(row["type"])):
                counts[token] = counts.get(token, 0.0) + 1
                length += 1
            total_len += length
            tf = [0.0] * len(terms)
            for token, weight in counts.items():
                for i, term in enumerate(terms):
                    if _term_matches(token, term):
                        tf[i] += weight
            if any(tf):
                for i, value in enumerate(tf):
                    if value:
                        df[i] += 1
                read.matches.append(_Match(row["id"], tf, length))
        read.data_token = digest.hexdigest()
        if not terms:
            return read

        read.total_matches = len(read.matches)
        avg = (total_len / read.doc_count) if read.doc_count else 1.0
        n = read.doc_count
        idf = [math.log(1.0 + (n - d + 0.5) / (d + 0.5)) for d in df]
        scored: List[Tuple[float, str]] = []
        for count, match in enumerate(read.matches):
            if count & 255 == 0:
                deadline.check()
            score = 0.0
            for i, freq in enumerate(match.tf):
                if freq:
                    denom = freq + _K1 * (1 - _B + _B * (match.length / avg))
                    score += idf[i] * (freq * (_K1 + 1)) / denom
            scored.append((score, match.entity_id))
        deadline.check()
        scored.sort(key=lambda item: (-item[0], item[1]))
        deadline.check()
        assert request is not None

        used = 0
        for rank, (score, entity_id) in enumerate(scored[: request.limit], start=1):
            deadline.check()
            row = conn.execute(
                "SELECT id, type, name, properties, version FROM entities "
                f"WHERE id = ? AND scope_id = ? AND {iso_sql}",
                [entity_id, binding.scope_id, *iso_params],
            ).fetchone()
            if row is None:  # cannot happen inside one snapshot; never emit unscoped data
                continue
            props = _parse_properties(row["properties"])
            entity_row_id = str(row["id"])
            label, excerpt = _best_excerpt(
                _segments(entity_row_id, str(row["name"]), props, verifier),
                terms,
                request.max_excerpt_chars,
            )
            provenance, source_ids = _provenance(entity_row_id, props, verifier)
            item = {
                "rank": rank,
                "score": round(score, 6),
                "citation": {
                    "id": f"entity:{row['id']}",
                    "entity_id": row["id"],
                    "entity_version": row["version"],
                    "source_ids": source_ids,
                },
                "type": _clip(str(row["type"])),
                "name": _clip(str(row["name"]), MAX_NAME_CHARS),
                "excerpt": excerpt,
                "excerpt_field": label,
                "excerpt_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
                "provenance": provenance,
            }
            size = len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
            if used + size > _RESULT_BUDGET_BYTES:
                read.truncated = True
                break
            used += size
            read.results.append(item)
        if len(scored) > len(read.results):
            read.truncated = True
        return read
    except sqlite3.Error as exc:
        raise translate_error(exc) from None


# ---------------------------------------------------------------------------
# Public operations
# ---------------------------------------------------------------------------


def _freshness_error(reason: str) -> Dict[str, Any]:
    return {
        "contract": FRESHNESS_CONTRACT,
        "cacheable": False,
        "bypass_reason": reason,
        "token": None,
        "authorization": None,
        "data": None,
        "validated_at": _now(),
    }


def _error(operation: str, status: str, reason: str, message: str) -> Dict[str, Any]:
    return {
        "contract": CONTRACT,
        "operation": operation,
        "status": status,
        "reason": reason,
        "message": message,
        "results": [],
        "freshness": _freshness_error(f"{status}:{reason}"),
    }


def _execute(
    operation: str, provider_config: Any, raw_request: Any, *, with_query: bool
) -> Dict[str, Any]:
    try:
        request = parse_request(raw_request, with_query=with_query)
    except InvalidRequest as exc:
        return _error(operation, STATUS_INVALID, "invalid_request", exc.message)
    deadline = Deadline(request.timeout_ms)
    try:
        config = load_provider_config(provider_config)
        binding = resolve_binding(config, request.app_project)
    except ProviderConfigError as exc:
        return _error(operation, STATUS_UNAUTHORIZED, exc.reason, exc.message)
    except AuthorizationDenied as exc:
        return _error(operation, STATUS_UNAUTHORIZED, exc.reason, exc.message)

    snapshot: Optional[Snapshot] = None
    try:
        deadline.check()
        snapshot = open_snapshot(binding.store_path, deadline)
        read = _scoped_read(snapshot, binding, request if with_query else None, deadline)
        verify_unchanged(snapshot)
        deadline.check()
        mode = snapshot.mode
    except SearchTimeout:
        return _error(operation, STATUS_TIMEOUT, "deadline_exceeded", "the search timed out")
    except StoreUnavailable as exc:
        return _error(operation, STATUS_UNAVAILABLE, exc.reason, exc.message)
    finally:
        if snapshot is not None:
            close_snapshot(snapshot)

    auth_token = authorization_token(binding)
    combined = hashlib.sha256(f"{auth_token}:{read.data_token}".encode("ascii")).hexdigest()
    response: Dict[str, Any] = {
        "contract": CONTRACT,
        "operation": operation,
        "status": STATUS_OK,
        "reason": None,
        "message": None,
        "results": read.results,
        "freshness": {
            "contract": FRESHNESS_CONTRACT,
            "cacheable": True,
            "bypass_reason": None,
            "token": combined,
            "authorization": {"token": auth_token, "basis": "provider-config-grant"},
            "data": {
                "token": read.data_token,
                "basis": "exact-scope-content-digest",
                "snapshot": mode,
            },
            "validated_at": _now(),
        },
    }
    if with_query:
        if not read.results and read.total_matches == 0:
            response["status"] = STATUS_NO_MATCHES
        response["bounds"] = {
            "limit": request.limit,
            "max_excerpt_chars": request.max_excerpt_chars,
            "max_query_chars": MAX_QUERY_CHARS,
            "max_query_terms": MAX_QUERY_TERMS,
            "max_response_bytes": MAX_RESPONSE_BYTES,
            "total_matches": read.total_matches,
            "returned": len(read.results),
            "truncated": read.truncated,
        }
    return response


def search_evidence(provider_config: Any, request: Any) -> Dict[str, Any]:
    """Run the read-only evidence search; never raises for contract conditions."""
    return _execute("search", provider_config, request, with_query=True)


def evidence_freshness(provider_config: Any, request: Any) -> Dict[str, Any]:
    """Return the current authorization+data freshness token without any excerpts."""
    return _execute("freshness", provider_config, request, with_query=False)
