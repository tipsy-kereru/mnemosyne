# Read-only evidence search

`mnemosyne evidence search|freshness` and `mnemosyne.evidence.search_evidence|evidence_freshness`
return a small set of citable excerpts from exactly one authorized project scope. The operation is
local and read-only: it never creates, migrates, indexes, checkpoints, or writes the store, and it
persists no results.

## Authority: trusted provider configuration only

The store, the effective caller, and every `(caller, app_project) -> scope` binding come from a
provider configuration file (`--provider-config`, or `MNEMOSYNE_EVIDENCE_PROVIDER_CONFIG`). It is
re-read on every call, so grant changes take effect on the next call. A request can carry only
`app_project`, `query`, `limit`, `max_excerpt_chars`, `timeout_ms`; any other field (`scope`,
`scope_id`, `caller`, ...) is rejected as `invalid_request`. The CLI has no store, scope, or caller
option.

```json
{
  "version": 1,
  "store": "knowledge.db",
  "effective_caller": "meeting-assistant",
  "grants": [
    {"grant_id": "g-1", "caller": "meeting-assistant", "app_project": "weekly-sync",
     "scope_id": "<scope id in the store>", "status": "active"}
  ]
}
```

`store` is resolved relative to the configuration file. The file is strictly validated (unknown keys,
duplicate `grant_id`, null/empty IDs, unknown `status` all deny everything), and on POSIX it must not
be group/world writable. Resolution for `(effective_caller, app_project)`:

| Situation | Result |
|---|---|
| No grant | `unauthorized` / `unbound` |
| Only revoked grants | `unauthorized` / `revoked` |
| Active grants naming more than one scope | `unauthorized` / `ambiguous` |
| Config missing / invalid | `unauthorized` / `provider_config_missing` / `provider_config_invalid` |
| Exactly one active scope (a revoked grant plus an active replacement is a rotation) | proceeds |

All denials happen before the store is opened.

## Exact-scope retrieval

Candidates are `entities WHERE scope_id = <bound scope>` (isolated channels such as `work-slack` and
tombstoned entities excluded). Global (`NULL`), parent, child, and sibling scopes are never read.
Ranking is BM25 computed over that candidate set alone (document count, document frequency, and
average length come from the bound scope), so other scopes cannot influence scores or order. The
FTS index is not used and never rebuilt. Query terms match whole tokens by prefix (substring for
CJK). Excerpts and provenance come from the same rows; a provenance entry (and its excerpt text) is
used only if its `source_id` belongs to `lifecycle_sources` of the bound scope, or is the reserved
`legacy:unattributed` marker on an entity that has a `lifecycle_legacy` backing record and lives in
the bound scope. Unverifiable entries are dropped before ranking.

## Response

`status`: `ok`, `no_matches`, `unauthorized`, `unavailable`, `timeout`, `invalid_request`.
`unavailable` reasons: `store_missing`, `store_uninitialized`, `store_unreadable`,
`store_schema_unsupported`, `scope_unavailable`, `store_busy`, `store_too_large`,
`store_snapshot_unsupported`, `store_changed_during_read`. `timeout` reason: `deadline_exceeded`.

Each result: `rank`, `score`, `citation` (`id` = `entity:<entity id>`, `entity_id`,
`entity_version`, `source_ids`), `type`, `name`, `excerpt`, `excerpt_field`, `excerpt_sha256`,
`provenance` (`source_id`, `revision`, `location`, `locator`). Results are ordered by score then
entity ID, so identical data gives identical citations.

Bounds: query <= 256 characters and <= 16 distinct terms; `limit` 1..20 (default 5);
`max_excerpt_chars` 40..1200 (default 400); `timeout_ms` 50..10000 (default 2000); <= 5 provenance
entries per result; response results are cut to fit 64 KiB (`bounds.truncated`).

## Non-mutating store access

Opening a WAL database with `mode=ro` creates `-wal`/`-shm` files when absent, a live WAL reader
writes read marks into `-shm`, and `PRAGMA journal_mode` cannot detect WAL under `immutable=1`. A raw
read of the database file would also drop other in-process connections' POSIX advisory locks. So the
access mode is chosen from the side files of the canonical (symlink-resolved) path alone:

| Side files | Access | Notes |
|---|---|---|
| none (or an empty `-wal`) | `mode=ro&immutable=1`; nothing is touched | a writer appearing during the read is detected and reported as `store_changed_during_read` |
| `-wal` content, `-shm`, or `-journal` | private copy of the main file and side files in a temporary directory, removed after the read | the store directory, including `-shm`, is never written; WAL recovery and hot-journal rollback run on the copy, yielding the last committed state |

The original file is only ever opened `immutable`. Copies are retried while the main file or a side
file header changes, refused above 256 MiB (`store_too_large`, decided from `stat` before any read),
and unsupported on SQLite builds without `serialize` (`store_snapshot_unsupported`).

A missing store creates nothing, not even parent directories.

## Freshness contract (`mnemosyne.evidence-freshness/1`)

Every response has `freshness`. On success it holds `cacheable: true` and `token`, the SHA-256 of

* the authorization token: caller, app project, bound scope, active grant IDs, store path;
* the data token: digest of every searchable row of the bound scope (ID, type, name, properties,
  version, updated_at), the scope row, and the scope's lifecycle source set, computed in the same
  read snapshot as the results.

The store-wide lifecycle generation is deliberately neither reported nor hashed: it moves on writes
to other scopes, so exposing it would leak cross-project activity. The lifecycle source set for the
scope contributes each source's revision, applied revision, state and applied digest, and the set of
entities with a scoped `lifecycle_legacy` backing record contributes its membership, so deleting a
source or changing legacy backing changes the token even when no excerpt text changes.

Client rule for a small in-memory cache keyed by `(app_project, query, limits)`: reuse an entry only
if a fresh `freshness` call returns `status == "ok"`, `cacheable == true`, and the same `token`.
Edits, deletions, lifecycle replacement/deactivation, and grant changes (scope rebinding or a new
grant ID) change the token. Every non-`ok`/`no_matches` response, and any response with
`cacheable == false` (always with `token: null` and a `bypass_reason`), means: evict and bypass the
cache. The data token costs one pass over the bound scope's rows.

## Limitations

* Entities only; relations are not searched. Property text nested deeper than 4 levels is not
  searched.
* Cost is linear in the size of the bound scope (bounded by `timeout_ms`; expiry at any stage,
  including cleanup before the response is returned, yields `timeout`, never a late success).
* Local filesystem paths only; UNC/network store paths are reported `store_unreadable`.
* A live, crashed, or journaled store is read from a private copy (whole main file and side files,
  so cost and the 256 MiB cap depend on the entire database, including other projects). A private
  copy may contain a complete commit that concurrent source readers have not yet been shown (never
  a torn one); if the writer then fails before syncing, that commit could be lost, so evidence from
  it is consistent with its token but not yet durable. The token changes on the next read if so.
  Timestamp-based change detection is best effort at filesystem timestamp resolution.
* An idle store with no side files is read with `immutable=1`; a writer appearing mid-read is
  detected by file-state comparison, and a non-WAL store written with an in-memory journal cannot be
  proven idle by files alone.
* Rows excluded from search (tombstoned) still participate in the data token, so editing them
  invalidates caches conservatively.
* Authorization is only as trustworthy as the provider configuration file's filesystem permissions.
