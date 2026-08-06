# wp-validation-v4 — Independent Security Validation of the v4 Outbound Enforcement Implementation

**Task:** `task_44b9e7e8ed5a` · dispatch `ctx_dc732fedc95e`
**Baseline:** `main @ ed8c332` + uncommitted working tree
**Contract validated against:** `docs/ONYX_OUTBOUND_ENFORCEMENT_DESIGN.ko.md` (amended)
**Prior report re-checked:** `.orca-orchestrator/VALIDATION_V3_SECURITY_REVIEW.md` (B1–B6)
**Method:** read-only. No production or test file in the repo was edited. Synthetic fixtures
and spy clients only. No secrets read, no private notes read, no Onyx call, no network, no
dependency install, nothing published. Probe files live in the session scratchpad; the only
file written inside the repo is this report.

## VERDICT

**B1–B5: all five CLOSED.** 79 independent probes, 79 pass, 0 behavioural blockers found.

**Design §9 completion gate: still FAIL on criterion 1 only** — test coverage is 118/168 and
the four design-mandated test files are still absent (B6 open). No code defect blocks the
outbound gate; the shortfall is regression protection for the fixes just landed.

| Gate (§9 완료 기준) | Result | Evidence |
|---|---|---|
| 1. `pytest tests/integrations/onyx/ -q` → 168 passed | **FAIL** | 118 passed in 3.28s (v3 was 112; +6) |
| 2. Spy proves the client is never called on negative cases | **PASS** | C13, C26, E02, E02b, E03–E07 |
| 3. Deny/quarantine/reject/withdraw codes match §6 verbatim | **PASS** | all 29 canonical codes present, inventory below |
| 4. No secrets, private paths, or real hostnames in the diff | **PASS** | scan below |

---

## Exact commands

```bash
python3 -m pytest tests/integrations/onyx/ -q
# → 118 passed in 3.28s     (design requires 168)

for f in tests/integrations/onyx/test_*.py; do
  echo "$f: $(python3 -m pytest "$f" --co -q 2>/dev/null | grep -c '::')"; done
# test_acl.py:13  test_contract.py:35  test_enforcement_v3.py:8  test_observability.py:6
# test_outbound_policy.py:5  test_permissions.py:19  test_push.py:8  test_worker.py:24

SP=/private/tmp/claude-501/-Users-kereru-Development-mnemosyne/\
bbef07c9-1877-476a-a2fc-74aaf4cc077f/scratchpad
python3 -m pytest $SP/probe_b.py $SP/probe_e2e.py $SP/probe_regress.py \
                  $SP/probe_migrate.py -q
# → 79 passed in 0.56s
#   probe_b.py       23  B1–B5 targeted
#   probe_e2e.py     12  through the real CLI entry points, OnyxClient replaced by a recorder
#   probe_regress.py 42  invariants v4 must not have broken
#   probe_migrate.py  2  legacy-schema migration

# gate #4 scan, including the untracked new files
{ git diff -- mnemosyne/ tests/; cat mnemosyne/integrations/onyx/destinations.py \
  tests/integrations/onyx/test_enforcement_v3.py \
  tests/integrations/onyx/test_outbound_policy.py; } | grep -inE \
  "api[_-]?key[[:space:]]*[:=][[:space:]]*['\"][^'\"]{8,}|secret[[:space:]]*[:=]|\
token[[:space:]]*[:=][[:space:]]*['\"][A-Za-z0-9_-]{16,}|/Users/[a-z]+/|\
sk-[A-Za-z0-9]{20,}|onyx\.(app|io|com)|cloud\.onyx"
# → 2 matches, both benign: the identifier `approved_hosts=onyx.approved_hosts`
#   (config.py) and the synthetic literal api_key="test-key" in a test.
```

---

## B1 — CLOSED — silent orphan from the `noop` steady state

`_withdrawal_candidates` (`exporter.py:142-149`) now admits
`{accepted, indexed, noop, failed, withdraw_pending, withdraw_blocked}` — every state that
implies a live remote document — and excludes only `pending` and `withdrawn`.

Reproduced end-to-end through the real CLI, the exact scenario that failed in v3
(`probe_e2e.py::test_E01`): `preflight → push (accepted) → preflight → push (noop) →
tombstone → preflight → push`.

```
final push: {"withdrawn":0,"withdraw_blocked":1,...}   exit code 2
push_state: 'noop' -> 'withdraw_blocked'
```

The v3 result for the identical sequence was `status 'noop' -> 'noop'; withdraw calls=[];
exit=0`. The silent orphan is gone.

Seven exporter-level probes confirm the full state space:

| Probe | Case | Result |
|---|---|---|
| `test_B1_noop_then_tombstone_is_withdrawn` | capable sink | one `withdraw(document_id)`, state `withdrawn` |
| `test_B1_noop_then_tombstone_blocks_without_capability` | incapable sink | `withdraw_blocked=1`, client never called |
| `test_B1_failed_state_is_a_withdrawal_candidate` | previously accepted, then `failed` | withdrawn |
| `test_B1_withdraw_is_idempotent` | three further pushes | exactly one `withdraw` call |
| `test_B1_blocked_then_capability_granted_transitions` | capability granted later | `withdraw_blocked → withdrawn` |
| `test_B1_deleted_entity_row_is_withdrawn` | entity row deleted from `noop` | withdrawn |
| `test_B1_ceiling_downgrade_withdraws_from_noop` | ceiling `internal → public` | withdrawn, reason `withdraw:policy_denied` |
| `test_B1_dry_run_withdrawal_...` | dry-run | counts only, no client, no state change |

## B2 — CLOSED — ceiling default is the restrictive end

All four defaults the v3 report named are now `"public"`:
`Destination.classification_ceiling` (`destinations.py:24`),
`DestinationPolicy.classification_ceiling` (`mapper.py:39`),
`OnyxEndpoint.destination_classification` (`config.py:50`), and the YAML fallback
(`config.py:177`, `config.py:150`). `map_entity`'s implicit no-policy fallback
(`mapper.py:87-89`) is `"public"` too, so the v3 "the two defaults disagree" finding is
resolved — `test_B2_no_policy_map_entity_matches_configured_default` asserts they produce the
identical deny code.

With `_CLASSIFICATION_ORDER = (private, confidential, internal, public)` ordered by
increasing openness and the gate denying when `index(ceiling) > index(classification)`
(`mapper.py:158-162`), `classification_ceiling` reads correctly as *the most sensitive
classification the destination may hold*:

```
ceiling = public (default)   private ✗  confidential ✗  internal ✗  public ✓
ceiling = internal           private ✗  confidential ✗  internal ✓  public ✓
```

No rename is needed — the field name was never inverted; only the default was. The amended
design agrees with the code: §4.1 line 169, §4.2 line 213, and T19 line 547 all state
`"public"` as the fail-closed default (`test_B2_doc_and_code_agree_on_polarity`).
An exporter constructed with no explicit policy is now fail-closed
(`test_B2_exporter_without_policy_is_fail_closed`: a `confidential` entity is skipped, the
client is never called) — the v3 case where "the one that governs real pushes is the
permissive one" no longer holds.

## B3 — CLOSED — `reinstate()` is auditable

`worker.reinstate` (`worker.py:502-546`) now calls `_record_history(..., "reinstated", ...)`
after clearing the tombstone.

```
probe_b.py::test_B3_reinstate_writes_history_row  PASS
  entity_history change_type='reinstated' × 1
  properties.reinstated_by     == 'alice'
  properties.reinstated_reason == 'mistaken deletion'
  live row: tombstoned_at / valid_to removed
```

`actor` and `reason` are both mandatory — either empty yields
`reject:replay_unauthorized` and writes no history row
(`test_B3_reinstate_requires_actor_and_reason`). §5.3's `withdrawn → pending` flip is
present (`test_B3_reinstate_returns_withdrawn_docs_to_pending`).

## B4 — CLOSED — quarantine is scope-bound and the legacy table migrates

`onyx_quarantine` is now `PRIMARY KEY (source_doc_id, scope_id)` (`worker.py:210-224`) and
`_store_quarantine` upserts on the composite key (`worker.py:680`).

| Probe | Assertion | Result |
|---|---|---|
| `test_B4_quarantine_is_scope_bound` | same `source_doc_id` in `scope-b` and `scope-c` | both rows coexist; both independently resolvable to `rejected` |
| `test_B4_legacy_quarantine_table_is_migrated` | pre-v4 `source_doc_id TEXT PRIMARY KEY` table with one row | row preserved with its `scope_id`, PK is composite, `onyx_quarantine_old` dropped |
| `test_B4_migration_is_idempotent` | `_init_tables` run three times | record count stays 1 |
| `test_B4_source_index_stays_scope_bound` | two connectors, same `source_doc_id`, two scopes | two index rows, no overwrite (D13 still closed) |
| `probe_migrate.py::test_M02` | legacy `onyx_source_index` single-PK table | migrated, row preserved |

The v3 failures `test_Y04` (record overwritten) and `test_Y05` (unreachable after collision)
do not reproduce.

## B5 — CLOSED — the preview is side-effect free

`mark_noop` now sits behind the `dry_run` check (`exporter.py:85-86`), and `_withdraw_pass`
counts without writing in dry-run (`exporter.py:113-117`).

```
probe_b.py::test_B5_dry_run_push_does_not_mutate_push_state
  every onyx_push_state row compared field-by-field before/after → identical
  status stays 'accepted' (v3: 'accepted' -> 'noop')
probe_b.py::test_B5_dry_run_creates_no_rows_for_new_entities
  dry-run over an unpushed scope → list_scope() == []
```

The live-push deny-count recount (`cli.py:1241-1249`) runs through this same dry-run path, so
the preflight-gated push no longer writes before deciding — confirmed transitively by the
E-series probes, which drive it through the real CLI.

---

## Invariants re-verified (42 regression probes, all pass)

- **ACL before idempotency (I1 / L1 / T41):** a redelivery with an identical `content_hash`
  and an expired snapshot returns `quarantined` / `quarantine:acl_snapshot_stale`, and an
  emptied snapshot returns `quarantine:acl_snapshot_empty` — never `noop` (C01, C02).
- **Safe watermark (I15 / D6):** `_safe_watermark` unit table (C03); a
  `[quarantined@10:00, ingested@11:00]` batch does not advance past 10:00 (C04); an
  all-unresolved batch leaves the watermark empty and records `last_error` (C05); a clean
  batch afterwards clears the error and advances (C06). Never regresses.
- **Quarantine lifecycle (I16 / D5):** replay re-runs validate + ACL and re-quarantines when
  the ACL is still bad, leaving the record unresolved (C07); a repaired replay ingests and
  stamps `resolution='replayed'` + `resolved_by` (C08); reject preserves the record, creates
  no entity (C09); empty actor, bogus decision, and doc/scope mismatch all yield
  `reject:replay_unauthorized` (C10).
- **Deletion (I17 / L4):** wrong-scope deletion is `not_found` with no tombstone; repeat
  deletion is `tombstoned_noop` with exactly one `deleted` history row; a post-tombstone
  content update is `reject:tombstoned_source` (C11).
- **Re-publication guard (I10 / D2):** `_resolve_entity_type` downgrades `decision`,
  `Decision`, `risk`, `requirement`, `""`, `../../etc` to `document` and passes `github`,
  `slack`, `file` through (C12); an inbound entity is never re-published and neither its
  title nor its `external_uri` reaches the spy client or the outcome details (C13).
- **Transport / host allowlist (I6):** remote `http` and non-allowlisted host raise
  `ValueError` before any socket; loopback `http` and allowlisted `https` are accepted (C14).
- **Credential boundary (I13):** the API key never appears in the built payload or its repr
  (C15); the preflight output prints destination id, host, and the cc_pair *env var name*
  only, with no title, no `external_uri`, no key (E08); live-push client construction
  resolves the key from the environment and passes a non-empty `allowed_hosts` (E10).
- **Section allowlist (I3) and content hash (I4):** a 100-key randomized property fuzz never
  leaks an allowlist-external key, `api_token`, or `note_body` into section text (C16); the
  hash is stable across `access_snapshot` changes (C17).
- **Outbound contract (I7):** an allowed document passes `validate_outbound_document` with
  `sync_origin='mnemosyne'` and `do_not_reimport is True` (C18).
- **Deny-code inventory (§6):** nine of the ten outbound codes are reachable from
  `outbound_deny_reason` and all match §6 verbatim (C19); all 29 canonical codes are present
  in the source (C20, inventory below).
- **D10 / D11:** `typing.get_type_hints(OnyxPushExporter.__init__)` resolves (C21); a live
  entity whose property *value* contains the string `"valid_to"` is still published (C22).
- **Clearance and mapping floor (I8 / I9):** `can_access` denies on `None`, `""`, `"guest"`,
  `"unknown"` from either side (C23); `default_classification="confidential"` demotes a
  `"public"` envelope (C24); `owner_only` without an owner is
  `quarantine:owner_unidentified`, and scope mismatch is evaluated first (C25).
- **Negative push (§5.1 / gate 2):** the four-entity fixture {public-live, private-live,
  public-tombstoned, private-tombstoned} publishes exactly one document, the other three
  document IDs never reach the spy, and no `onyx_push_state` row is created for them (C26).
- **Preflight gate (I12):** `deny:preflight_missing`, `deny:preflight_stale`,
  `deny:preflight_destination_changed`, the deny-count-increase abort,
  `deny:approved_hosts_empty`, and `deny:destination_unbound` all fire with `OnyxClient`
  never constructed — verified by replacing `OnyxClient` with a recorder that stayed empty
  in every case (E02b–E07). A real subprocess confirms the deny exits non-zero and writes no
  push state (E02).

### Canonical code inventory (29/29 present)

```
mapper.py       deny:type_not_publishable  deny:origin_not_republishable  deny:tombstoned
                deny:classification_unknown  deny:classification_exceeds_destination
                deny:visibility_unknown  deny:destination_cannot_represent_acl
                deny:acl_snapshot_missing_or_stale  deny:destination_ceiling_invalid
                deny:contract_invalid
destinations.py deny:destination_unbound
client.py/cli.py deny:approved_hosts_empty  deny:host_not_approved  deny:insecure_transport
cli.py          deny:preflight_missing  deny:preflight_stale  deny:preflight_destination_changed
acl.py          quarantine:no_mapping  quarantine:scope_mismatch  quarantine:acl_snapshot_empty
                quarantine:acl_snapshot_stale  quarantine:owner_unidentified
worker.py       reject:contract_violation  reject:tombstoned_source  reject:replay_unauthorized
exporter.py     withdraw:tombstoned  withdraw:entity_missing  withdraw:policy_denied
                withdraw:blocked_no_capability
```

---

## Residual findings (none blocking)

**R1 — P1 — Gate #1 unmet; the four required test files are still absent.**
`test_destinations.py` (T16–T19), `test_withdrawal.py` (T20–T26),
`test_client_boundary.py` (T31–T35), and `test_preflight.py` (T36–T40) do not exist. The
repo gained 6 tests (112 → 118), not the required 60. Concretely: no repo test tombstones a
`noop` document (the exact B1 case), and none covers the quarantine cross-scope collision
(B4). Both behaviours are correct today and both are unprotected against regression. This is
the only §9 criterion that fails.

**R2 — P2 — Crash-window orphan.** `pending` is excluded from the candidate set. A document
that the destination accepted but whose process died between `record_push` (writes `pending`)
and `mark_accepted` is never withdrawn on a later tombstone (`probe_regress.py::test_C27`).
Same class as B1, far narrower. Widening to include `pending` would trade this for extra
withdraw attempts on documents that were never sent; the call is the designer's.

**R3 — P2 — Never-published documents are "withdrawn".** A document whose only push attempt
failed (state `failed`, never accepted remotely) still triggers a `withdraw()` call when
later tombstoned (`test_C28`). Fails safe — a DELETE for a document that does not exist — but
the outcome count and the log read as a real withdrawal.

**R4 — P2 — dry-run `withdrawn` counter overstates action.** For a capable destination the
dry-run branch increments `outcome.withdrawn` although nothing was withdrawn
(`exporter.py:114-115`; `test_C29` shows `withdrawn=1` with the row still `accepted`).
Carried over unchanged from the v3 non-blocking note 4.

**R5 — P2 — The deny-count-increase abort reports `deny:preflight_stale`** (`cli.py:1249`).
§6 defines no code for it, so an operator sees a TTL message for what is a policy or data
change. Either add a code to §6 or reuse `deny:preflight_destination_changed`.

**R6 — P2 — CLI deny paths raise bare `ValueError`.** The process exits non-zero with a
Python traceback rather than a clean coded error (subprocess check in E02: `returncode != 0`,
`deny:preflight_missing` on stderr). Safe, but the operator-facing surface is a stack trace.

**R7 — P2 — `cli.py:1259`** still uses `int(os.environ[destination.cc_pair_id_env])`, raising
a bare `KeyError` instead of a `deny:` code when the variable is unset. Carried over from v3
note 2.

**R8 — P3 — Doc/code divergence created by the fixes.** The design was amended for B2 only.
§4.4 (line 261) still describes the withdrawal candidate set as `accepted/indexed` — the
narrow set that *caused* B1 — and the §5.1 diagram (line 379) says the same. §4.7
(lines 325–326) documents only the `onyx_source_index` PK migration, not the
`onyx_quarantine` one landed for B4. The implementation is stricter and safer than the text;
the text should be brought up to it before it is used as a contract again.

**R9 — P3 — `exporter._withdraw_pass` still calls the private `sync_store._update_status`**
(`exporter.py:127`). Carried over from v3 note 3.

**R10 — P3 — Legacy `onyx_quarantine` tables lacking a `scope_id` column** migrate with
`scope_id=''` (`probe_migrate.py::test_M01`). The record is preserved but is not addressable
by a real scope. Hypothetical — no shipped schema lacked the column.

**R11 — P3 — `deny:contract_invalid` remains structurally unreachable** from `map_entity`,
since `validate_outbound_document` checks only fields populated unconditionally a few lines
earlier (C19 reaches 9 of the 10 outbound codes). The I7 guarantee is structural, not tested.
Carried over from v3 note 6.

**R12 — Unrelated pre-existing failures.** `tests/test_cli.py` has two failing version
assertions (`0.1.0` expected, `0.9.0` shipped). Present at `HEAD ed8c332` and untouched by
this work; `tests/test_cli.py` and `tests/test_cli_groups.py` are otherwise 93 passed.

---

## Reserved gates confirmed intact (§10)

`supports_withdrawal` defaults to `False` in `Destination` (`destinations.py:26`),
`DestinationPolicy` (`mapper.py:41`), `OnyxEndpoint` (`config.py:52`), and both config parse
paths (`config.py:180`, `config.py:200`). The only `True` values in the tree are four test
fixtures driving spy clients. `client.withdraw` issues
`DELETE {base_url}{INGESTION_PATH}/{document_id}` (`client.py:199-229`) — still unverified
against a real Onyx API, correctly held behind the §10 reservation. No Onyx endpoint was
contacted during this validation.

## Recommendation

The five blockers this pass was dispatched to check are closed, and I found no new
behavioural defect. The outbound gate still may not open on the design's own terms, for one
reason only: **§9 criterion 1**. Land the four missing test files — in particular a T20b that
tombstones a `noop` document and a T55-sibling for the quarantine table, the two cases that
would have caught B1 and B4 — then re-run this probe suite plus the repo suite. The probe
files are self-contained, import only production code, and need no repo fixtures.
