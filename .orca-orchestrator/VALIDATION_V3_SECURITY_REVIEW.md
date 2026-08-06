# wp-validation-v3 — Independent Security Validation of the v3 Outbound Enforcement Implementation

**Task:** `task_3551191472ae` · dispatch `ctx_22b8ab501a81`
**Baseline:** `main @ ed8c332` + uncommitted working tree
**Contract validated against:** `docs/ONYX_OUTBOUND_ENFORCEMENT_DESIGN.ko.md`
**Method:** read-only. No production file was edited. Synthetic fixtures and spy clients only.
No secrets read, no private notes read, no provider/Onyx calls, no dependency installs, no
network, nothing published externally. Probe files live outside the repo, in the session
scratchpad; the only file written inside the repo is this report.

## VERDICT: **FAIL** — do not open the outbound publishing gate

Four of the design's own completion criteria were checked. Three pass. The first fails, and
two P0-class defects that the design was specifically written to close are still open in the
implementation.

| Gate (§9 완료 기준) | Result | Evidence |
|---|---|---|
| 1. `pytest tests/integrations/onyx/ -q` → 168 passed | **FAIL** | 112 passed (design baseline was 108; net +4 against a required +60) |
| 2. Spy proves the client is never called on negative cases | **PASS** | probes T27, T28, T33, T36, T40, X05 |
| 3. Deny/quarantine/reject/withdraw codes match §6 verbatim | **PASS** | all 29 canonical codes present and asserted |
| 4. No secrets, private paths, or real hostnames in the diff | **PASS** | scan below |

---

## Exact commands

```bash
# repo test suite (design gate #1)
python3 -m pytest tests/integrations/onyx/ -q
# → 112 passed in 3.31s     (design requires 168)

# per-file test counts
for f in tests/integrations/onyx/test_*.py; do
  echo "$f: $(python3 -m pytest "$f" --co -q 2>/dev/null | grep -c '::')"; done
# test_acl.py:13  test_contract.py:35  test_enforcement_v3.py:4  test_observability.py:6
# test_outbound_policy.py:5  test_permissions.py:19  test_push.py:8  test_worker.py:22

# independent probe suite, derived from design §8 T01–T60 (written by this reviewer)
SP=/private/tmp/claude-501/-Users-kereru-Development-mnemosyne/284ecf43-56da-4738-8ab8-4bdeb27a73c3/scratchpad
python3 -m pytest $SP/probe_v3.py -q       # → 72 passed, 3 failed
python3 -m pytest $SP/probe_v3b.py -q      # → 1 passed,  5 failed
python3 -m pytest $SP/probe_e2e.py -q      # → 1 failed  (end-to-end through the real CLI)

# credential / privacy scan of the diff (gate #4)
git diff -- mnemosyne/ tests/ | grep -inE \
  "api[_-]?key\s*[:=]\s*['\"][^'\"]{8,}|secret\s*[:=]\s*['\"]|token\s*[:=]\s*['\"][A-Za-z0-9_-]{16,}|/Users/[a-z]+/|sk-[A-Za-z0-9]{20,}|onyx\.(app|io|com)|cloud\.onyx"
# → only match is the identifier `approved_hosts=onyx.approved_hosts` (config.py). Clean.

# canonical code inventory (gate #3) — all 29 codes PRESENT
```

**Probe coverage: 75 checks derived from design §8, of which 66 confirm correct behaviour.**

---

## BLOCKERS

### B1 — P0 — Silent orphan: tombstoned documents in `noop` state are never withdrawn (I14 / D1 still open)

`OnyxPushExporter._withdrawal_candidates` (`mnemosyne/integrations/onyx/exporter.py:142-144`)
only considers push states in `{accepted, indexed, withdraw_blocked}`. But
`push_scope` marks every unchanged document `noop`
(`exporter.py:81-85` → `sync_state.mark_noop`), which is the **steady state** for any
document that survives more than one push. Once a document is `noop`, tombstoning it
produces no withdrawal, no `withdraw_blocked`, no non-zero exit — nothing.

Reproduced end-to-end through the real CLI entry points (`probe_e2e.py`), with a spy
client and a synthetic destination:

```
preflight → push (accepted) → preflight → push (noop) → tombstone entity → preflight → push
```

Final push output:

```json
{"scope_id":"s","total":0,"pushed":0,"noop":0,"skipped":0,"failed":0,
 "withdrawn":0,"withdraw_blocked":0,"details":[]}
```

```
SILENT ORPHAN via CLI: doc mnemosyne:s:decision:e1 status 'noop' -> 'noop';
withdraw calls=[]; exit=0
```

The Onyx-side document stays live forever. This is precisely the failure mode D1 was
written to close, and §5.1's rule "`accepted | indexed` — entity tombstone → `withdraw_pending`"
never fires. The existing repo test `test_tombstone_withdrawal_is_scope_bound_and_idempotent`
passes only because it tombstones after the *first* push, before any `noop` marking.

Same defect for `failed` state (`probe_v3b.py::test_Y02`): a previously-accepted document
that later fails a push is also dropped from the candidate set permanently.

**Fix direction:** the candidate set must be "every state that implies a live document
at the destination" — `{accepted, indexed, noop, failed, withdraw_pending, withdraw_blocked}`
— i.e. everything except `pending` and `withdrawn`.

### B2 — P0 — The default `classification_ceiling` is the *most permissive* value, and the design calls it fail-closed

`_CLASSIFICATION_ORDER = ("private", "confidential", "internal", "public")` orders by
increasing openness, and `outbound_deny_reason` denies when
`index(ceiling) > index(source)` (`mapper.py:158-162`). Therefore `ceiling="private"`
(rank 0) is never greater than anything and **admits every classification**.

`Destination.classification_ceiling` defaults to `"private"` (`destinations.py:24`),
`DestinationPolicy.classification_ceiling` defaults to `"private"` (`mapper.py:39`),
`OnyxEndpoint.destination_classification` defaults to `"private"` (`config.py:50`), and
`config.py:178-180` falls back to `"private"` when the YAML key is omitted.

```
$ python3 -c "...DestinationRegistry.from_config(cfg).for_scope('s')..."
ceiling = private
  classification=private       -> PUBLISHED
  classification=confidential  -> PUBLISHED
  classification=internal      -> PUBLISHED
  classification=public        -> PUBLISHED
```

A destination stanza that simply omits `classification_ceiling` publishes confidential and
private material. `OnyxPushExporter(...)` constructed without an explicit policy does the
same (`exporter.py:58`; probe `test_X02`), while `map_entity`'s own no-policy fallback uses
`"public"` (`mapper.py:87-89`) — the two defaults disagree, and the one that governs real
pushes is the permissive one.

Design §4.2 explicitly frames this as "기본을 public → private 로 변경 (fail-closed)" and
T19 asserts `"private"` as the fail-closed default. **The design document has the polarity
inverted**, and the implementation faithfully reproduced the inversion. This needs a design
decision, not just a code change: either rename the field so its direction is unambiguous,
or make the default `"public"` (the genuinely restrictive end) and require operators to
widen it explicitly.

### B3 — P1 — `reinstate()` writes no `entity_history` row (I17 / T54 unmet)

`ExportWorker.reinstate` (`worker.py:465-505`) clears `tombstoned_at`/`valid_to`, stamps
`reinstated_by`/`reinstated_reason` into `properties`, and flips push state — but never calls
`_record_history`. Design §4.7 and §5.3 require
`entity_history: change_type='reinstated'` with actor and reason; T54 asserts it.

```
probe_v3.py::test_X03_reinstate_writes_history_row
AssertionError: no entity_history row with change_type='reinstated'
```

The reinstatement is therefore not auditable from the history table — the only durable trace
is a mutable field on the live row, which the next inbound update overwrites.

### B4 — P1 — `onyx_quarantine` is not scope-bound; cross-scope collision destroys records

D13 was closed for `onyx_source_index` (composite PK `(source_doc_id, scope_id)`,
`worker.py:168-188`, verified by `probe_v3b.py::test_Y03` — **passes**), but
`onyx_quarantine` still has `source_doc_id TEXT PRIMARY KEY` (`worker.py:199`) and
`_store_quarantine` upserts on `ON CONFLICT(source_doc_id)` (`worker.py:639`).

`source_doc_id` is derived from `(onyx_connector_id, external_document_id)`
(`contract.py:270-274`), so remapping a connector to a different scope — exactly the
operation §5.2 and I9 are guarding — silently overwrites the first scope's record:

```
probe_v3b.py::test_Y04  quarantine record for scope-a was overwritten by scope-b: ['scope-b']
probe_v3b.py::test_Y05  scope-a quarantine is unreachable after collision: 'not_found'
```

`resolve_quarantine` queries `WHERE source_doc_id=? AND scope_id=?`, so the lost record can
never be resolved or replayed. The quarantine is not merely misfiled — it is unrecoverable,
which defeats I16.

### B5 — P2 — The live-push preview mutates push state before the gate decides

`cli.py:1239-1245` runs a full `push_scope(dry_run=True)` to recompute `deny_count`. That
preview reaches `sync_store.mark_noop()` (`exporter.py:83`) before the `dry_run` branch at
`exporter.py:86`, so a read-only preflight check writes to `onyx_push_state`:

```
probe_v3b.py::test_Y06  dry-run preview mutated push_state: 'accepted' -> 'noop'
```

Harmless on its own, but it is the mechanism that drives documents into the `noop` state
that B1 then strands. Fixing B5 alone does not fix B1; fixing B1 alone leaves a
preflight command with write side effects.

### B6 — Gate #1 — Test coverage is 112/168, and four required test files do not exist

Present: `test_acl.py`, `test_contract.py`, `test_enforcement_v3.py`, `test_observability.py`,
`test_outbound_policy.py`, `test_permissions.py`, `test_push.py`, `test_worker.py`.

Absent, all required by design §8: `test_destinations.py` (T16–T19),
`test_withdrawal.py` (T20–T26), `test_client_boundary.py` (T31–T35),
`test_preflight.py` (T36–T40).

Important nuance for the coordinator: I verified the **behaviour** those files would cover
with my own probes, and most of it works. The shortfall is regression protection, not
(mostly) missing functionality — with the exceptions called out in B1–B4, which are real
behavioural gaps that the missing tests would have caught. `test_enforcement_v3.py` collapses
roughly 15 design cases into 4 tests, which is why B1 slipped through: its withdrawal test
never reaches the `noop` state.

---

## What the implementation gets right (independently verified, 66 checks)

- **Outbound policy gate (§8.1, T01–T15):** all deny codes correct, including case-sensitive
  classification (`"Public"` → `deny:classification_unknown`), `valid_to`-only tombstones,
  bogus ceilings, and missing/stale ACL snapshots. **I18 holds** — T02/T03 confirm
  `map_entity` returns a `MapResult` instead of raising `KeyError` when `classification` or
  `visibility` is absent, and records the same defaulted value in metadata. D7 is closed.
- **Section allowlist (I3):** a 100-key randomized property fuzz never leaked an
  allowlist-external key into section text; `api_token`, `note_body`, and `access_snapshot`
  never appear. **D12 is closed** — dry-run `details` contain `document_id` and codes only,
  no titles; preflight output prints destination id, host, and the cc_pair *env var name*,
  never the key, a title, or an `external_uri`.
- **Content hash (I4):** stable across `classification`/`access_snapshot` changes.
- **Scope binding (I5 / D3):** `DestinationNotBound` on unbound scopes with no global
  fallback, including the legacy single-`onyx:` config path, which is promoted to a
  `"default"` destination but deliberately given **no** auto scope binding.
- **Fingerprint (I13):** secret-free and invariant under env-value changes.
- **Re-publication guard (I10 / D2):** `_resolve_entity_type` downgrades `""`, `"../../etc"`,
  `"Decision"`, `"decision"`, and `"risk"` to `document`; an inbound entity ingested with
  `source_type="decision"` is never re-published, and neither its title nor its
  `external_uri` reaches the spy client.
- **Preflight gate (I12 / D4-a):** `deny:preflight_missing`, `deny:preflight_stale`,
  `deny:preflight_destination_changed`, and the deny-count-increase abort all fire
  **before `OnyxClient` is constructed** — confirmed by patching `OnyxClient.__init__` to a
  recorder that stayed empty.
- **Transport and host allowlist (I6 / D4-b):** remote `http` rejected, non-allowlisted host
  rejected, empty allowlist rejected, loopback `http` allowed, and
  `deny:approved_hosts_empty` raised in the CLI before client creation.
- **Credential boundary (I13):** the API key never appears in the built payload; config
  stores env var *names* only.
- **ACL-before-idempotency ordering (I1 / L1):** a redelivery with an identical
  `content_hash` but an expired ACL snapshot returns `quarantined`, not `noop`.
- **Safe watermark (I15 / D6):** `[quarantined@10:00, ingested@11:00]` does not advance past
  10:00; an all-failed batch leaves the watermark empty and records `last_error`; a clean
  batch afterwards clears `last_error` and advances.
- **Quarantine lifecycle (I16 / D5):** replay re-runs validation and ACL and re-quarantines
  when the ACL is still bad (record stays unresolved); reject preserves the record with
  `resolution='rejected'` and `resolved_by`, creating no entity; `actor=""` yields
  `reject:replay_unauthorized`.
- **Deletion (I17 / L4):** wrong-scope deletion returns `not_found` and writes no tombstone;
  repeat deletion returns `tombstoned_noop` with exactly one `deleted` history row;
  a post-tombstone content update is rejected with `reject:tombstoned_source`.
- **`owner_only` (I11 / D9):** missing owner → `quarantine:owner_unidentified`; scope
  mismatch is evaluated before the ACL-mode branch.
- **Clearance (I8):** `can_access` denies on `None`, `""`, `"guest"`, `"unknown"` from either side.
- **Mapping floor (I9):** `default_classification="confidential"` demotes a `"public"` envelope.
- **D10 / D11 closed:** `typing.get_type_hints(OnyxPushExporter.__init__)` resolves, and the
  tombstone predicate uses `json_extract`, so a live entity whose property *value* contains
  the string `"valid_to"` is still published.
- **Withdrawal mechanics, where reachable:** capable destination calls `withdraw` once and
  not `ingest`; incapable destination records `withdraw_blocked` and calls nothing;
  `withdraw_blocked → withdrawn` on capability grant; repeat pushes do not double-withdraw;
  a ceiling downgrade produces `withdraw:policy_denied`; dry-run counts without a client;
  reinstatement returns `withdrawn → pending`. The CLI exits non-zero on `withdraw_blocked`.

## Non-blocking notes

1. `OnyxClient(allowed_hosts=None)` — the default — disables the host allowlist entirely
   (`client.py:92-96`). The CLI always passes a non-empty set, so this is currently
   unreachable in production, but the safe behaviour depends on every future caller
   remembering to pass it. Consider making `allowed_hosts` required.
2. `cli.py:1258-1259` uses `os.environ[destination.cc_pair_id_env]`, raising a bare
   `KeyError` rather than a `deny:` code when the variable is unset.
3. `exporter._withdraw_pass` calls `sync_store._update_status`, a private method.
4. In dry-run, `_withdraw_pass` increments `outcome.withdrawn` for a capable destination even
   though nothing was withdrawn (`exporter.py:111-112`); the count reads as an action taken.
5. `worker.process_batch` skips `checkpoint_store.save()` when the watermark is unchanged and
   unresolved items exist (`worker.py:359`), so `documents_processed` under-counts the
   ingested documents from those batches.
6. `deny:contract_invalid` appears unreachable from `map_entity`, since every field
   `validate_outbound_document` checks is populated unconditionally a few lines earlier.
   Harmless, but the I7 guarantee is structural rather than tested.
7. Design §10 correctly flags that `docs/ONYX_READ_ONLY_EXPORT_CONTRACT.md` §9 needs updating;
   that has not been done.

## Recommendation

**Do not open the outbound gate. Return to `wp-implementation-v3` for a scoped second pass.**

Order of work:

1. **B1** — widen `_withdrawal_candidates` to every state implying a live remote document.
   This is the one defect that silently leaves data published after deletion, and it fires in
   normal steady-state operation, not at an edge.
2. **B2** — resolve the ceiling-polarity inversion. This is a **design decision first**: the
   design document itself is wrong, so patching the code without amending §4.2/§6/T19 will
   reintroduce it. Recommend renaming the field to state its direction explicitly
   (e.g. `max_openness` / `most_open_classification_allowed`) and defaulting to the
   restrictive end.
3. **B4** — migrate `onyx_quarantine` to PK `(source_doc_id, scope_id)`, mirroring the
   `onyx_source_index` migration already done in `worker._init_tables`.
4. **B3** — add the `reinstated` history row.
5. **B5** — make the deny-count recount side-effect-free (move the `mark_noop` write behind
   the `dry_run` check, or add a pure counting path).
6. **B6** — land the four missing test files. Every one of B1–B4 is a case the design's own
   T-matrix specified: B1 is a gap between T20 and T23 (no test tombstones a `noop`
   document — worth adding as T20b), B3 is T54, B4 is T55's sibling for the quarantine table.

`supports_withdrawal` must stay `False` in every shipped configuration until B1 is fixed —
with it false, a tombstone at least records `withdraw_blocked` and exits non-zero for the
document states that *are* covered. The §10 반려 게이트 (real Onyx endpoint verification,
real Markdown ingest, per-scope ACL approval) remain correctly closed and were not touched.

Re-validation after the fixes should re-run all three probe files plus the repo suite; the
probe files are self-contained, import only production code, and need no fixtures from the repo.
