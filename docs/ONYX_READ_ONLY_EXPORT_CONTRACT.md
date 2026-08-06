# Onyx Read-Only Export Contract

**Status:** enforcement implemented and verified; external export remains blocked pending operational approval  
**Contract version:** `1.0`  
**Last reviewed:** 2026-08-06

> **Implementation gate:** stable IDs, content hashes, CLI path overrides,
> dry-run routing, outbound classification/ACL/tombstone enforcement,
> withdrawal/suppression lifecycle, and the inbound ACL/tombstone worker are
> implemented and tested. External Onyx publication remains blocked pending
> destination ACL binding, provider/privacy approval, retention approval, and
> live-export preflight review.

This contract defines the boundary for publishing Mnemosyne knowledge to an
Onyx index that is read-only from the user's point of view:

```text
Obsidian Markdown -> Mnemosyne personal DB -> generated Wiki/knowledge
                                      |
                                      v
                           Onyx read-only index/search
```

The contract does not authorize Onyx edits to flow back into the personal
vault or Mnemosyne database. The existing Onyx export-worker code supports an
opposite, separately testable `Onyx -> Mnemosyne` ingestion path; enabling that
path is a different decision and is not implied by this read-only contract.

## 1. Scope and non-goals

### In scope

- Stable identity for an exported document and its Mnemosyne source entity.
- Content fingerprinting and idempotent no-op behavior.
- Scope, classification, visibility, and ACL boundaries.
- Tombstone behavior for withdrawal or access revocation.
- Provider, credential, and personal-data gates before external calls.

### Out of scope

- Reimplementing Onyx connectors or authentication in Mnemosyne.
- Ingesting a personal vault, raw notes, or generated Wiki pages as part of
  this contract.
- Treating `scope_id` as an authorization mechanism.
- Bidirectional synchronization or automatic write-back from Onyx.
- Storing API keys, tokens, or provider payloads in this repository.

## 2. Export boundary

The current personal CLI boundary keeps the source, generated Wiki, and local
knowledge database explicit:

| Boundary | Required behavior |
|---|---|
| Source | Use an explicit Obsidian source path; tag ingestion with `source_channel=obsidian` (or the deployment's equivalent). |
| Local state | Use an explicitly selected personal `--db-path` and `--raw-root`; do not place SQLite or raw storage in an iCloud-synchronized vault. |
| Generated output | Keep `--wiki-root` separate from source paths and exclude it from future ingestion. |
| Export input | Select only curated, publishable entity types; do not publish a raw database dump. |
| Export direction | Mnemosyne may send an index document to Onyx; Onyx is not a source of edits for this flow. |
| Loop guard | Documents originating from Mnemosyne set `do_not_reimport=true`; generated documents are excluded from re-ingestion. |

The export adapter MUST preserve provenance (`scope_id`, source channel, source
URI/revision when available, and update time) while avoiding personal source
paths or note bodies in logs.

## 3. Stable identity

IDs are deterministic and are not derived from collection time or section
order. Unsafe ID characters are sanitized to path-safe `-` segments by the
implementation.

| Identifier | Format | Meaning |
|---|---|---|
| Onyx source document | `onyx:{connector_id}:{external_document_id}` | Stable identity when consuming an Onyx document. |
| Mnemosyne source version | `{source_doc_id}#{revision-or-hash}` | One source revision; `latest` is used when no revision is available. |
| Mnemosyne entity | `{scope_id}:{entity_type}:{canonical_name}` | Stable entity identity within a scope; the same name in two scopes is different. |
| Read-only Onyx document | `mnemosyne:{scope_id}:{entity_type}:{entity_id}` | Stable `document.id` for publication; republishing updates the same Onyx document. |

A connector or entity with a missing identity component is invalid. The
stable ID is not an ACL: a caller MUST still apply classification and ACL
checks before returning or publishing the document.

## 4. Content hash and idempotency

`content_hash` is `sha256:<hex>` over normalized section text:

1. Strip trailing whitespace from each section's `text`.
2. Sort normalized section texts.
3. Join them with a newline and compute SHA-256.

The hash is an integrity and no-op key, not an identity replacement:

- Same stable document ID + same hash => no-op; do not create a duplicate.
- Same stable document ID + changed hash => publish/update a new version and
  retain the prior Mnemosyne history.
- A supplied hash that differs from recomputation is a validation error; do
  not publish it.
- Hashing MUST NOT include secrets, ACL tokens, or volatile collection time.

The publication adapter may carry the hash in its sync-state store even when
Onyx's ingestion payload carries only the document sections and metadata.

## 5. ACL, scope, and classification

`scope_id` routes data; it does not grant access. The source system or an
explicit deployment policy remains the authority for authorization.

An ACL snapshot has `users`, `groups`, and `captured_at`. For an incoming
Onyx document, the implemented default policy is:

- `require_snapshot`: empty, malformed, or stale snapshots are default-deny
  and quarantine the document instead of ingesting it.
- Snapshot freshness defaults to 24 hours.
- Missing connector-to-scope mapping is quarantine, not inference.
- `owner_only` is permitted for an explicitly isolated personal scope; the
  owner is represented by the scope boundary rather than a group ACL.
- `open` is an explicit deployment choice, never an implicit fallback.

For publication to Onyx, the adapter MUST select a destination whose ACL and
classification are at least as restrictive as the source policy. `private`
and restricted material MUST NOT be published to a shared/project index.
When the destination cannot represent the source ACL, quarantine or skip the
export; do not broaden visibility. ACL data may be a snapshot for routing,
but Mnemosyne does not replace Onyx's user-permission system.

The `mnemosyne/integrations/onyx/mapper.py` and `exporter.py` enforcement
adapter now deny or quarantine private/restricted/tombstoned entities when the
destination policy cannot safely represent them. ACL freshness is checked
before idempotency/no-op decisions, and blocked outcomes exclude note body and
credentials.

## 6. Tombstones and history

Withdrawal, deletion, or access revocation is a state change, not physical
erasure:

1. Keep the entity row and provenance.
2. Record `tombstoned_at` and `valid_to` (equal at the transition time).
3. Append a deletion/tombstone history record.
4. Mark the source as historical-only for Mnemosyne queries and downstream
   export decisions.
5. If the Onyx deployment has a delete/withdraw API, propagate the stable
   document ID as a withdrawal; otherwise suppress it from subsequent
   read-only publication and retain the local tombstone.

No adapter or maintenance command may delete the underlying knowledge row to
implement this contract. A later reinstatement is a new explicit state
transition with provenance; it does not erase the tombstone history.

The inbound `Onyx -> Mnemosyne` worker implements the local tombstone/history
transition. Outbound suppression/withdrawal is implemented locally, but actual
external publication remains disabled until the operational gates in §7 pass.

## 7. Provider and privacy gates

Local CLI routing and external provider use are separate gates:

- Do not run real personal-document ingest or external export until the
  provider, retention behavior, and allowed data classification are explicitly
  approved for the deployment.
- The LLM bridge honors `MNEMOSYNE_LLM`; otherwise it detects configured
  provider credentials and falls back to the local `claude` CLI path. This
  fallback is current implementation behavior, not privacy approval; a
  deployment MUST explicitly approve every provider path before processing
  personal content. Provider selection MUST be recorded before processing
  personal content; auto-detection is not approval to transmit data.
- A dry-run MUST precede the first export for a new scope and must be reviewed
  for destination, document count, stable IDs, hashes, and classification.
- Configuration stores environment-variable names such as `ONYX_API_KEY` and
  `ONYX_MNEMOSYNE_CC_PAIR_ID`, never the corresponding values.
- API keys and bearer tokens are resolved at call time, never serialized into
  an Envelope, metadata, test fixture, or log. Logs MUST redact document
  bodies and credentials.
- Provider failure, missing credentials, or an unapproved destination stops
  the export; it MUST NOT silently fall back to a less restrictive privacy
  policy.

## 8. Contract-shaped payload

The following is a synthetic shape, not a personal document and not a
credential-bearing fixture. The stable `document.id` and sync-state hash are
required; ACL and tombstone fields are policy metadata and MUST be enforced by
the adapter even if a particular Onyx API version stores them outside the
Document body.

```json
{
  "contract_version": "1.0",
  "document": {
    "id": "mnemosyne:personal:decision:personal-decision-example",
    "semantic_identifier": "[decision] Example decision",
    "title": "Example decision",
    "sections": [{"text": "Synthetic content only."}],
    "source": "mnemosyne",
    "from_ingestion_api": true,
    "doc_updated_at": "2026-08-05T00:00:00Z",
    "metadata": {
      "scope_id": "personal",
      "source_channel": "obsidian",
      "content_hash": "sha256:<recomputed-hex>",
      "classification": "private",
      "visibility": "private",
      "acl_snapshot": {"users": ["owner"], "groups": [], "captured_at": "2026-08-05T00:00:00Z"},
      "tombstone": false,
      "do_not_reimport": true
    }
  }
}
```

The current client sends the Onyx ingestion request with a configured
`cc_pair_id`; that ID and the bearer token are configuration/transport
values, not content fields. Deployments MUST verify that the selected Onyx
API version preserves the metadata needed for ACL and withdrawal enforcement.

## 9. Implementation evidence and gates

The contract is partly grounded in the current implementation and synthetic
tests; external publication remains blocked by operational and destination
gates:

- CLI personal overrides: `mnemosyne/cli.py`, `mnemosyne/ingest/cli.py`,
  `mnemosyne/graph/cli.py`, `tests/test_cli.py`, and
  `tests/test_cli_groups.py`.
- IDs, hashing, Envelope validation, and loop prevention:
  `mnemosyne/integrations/onyx/contract.py` and
  `tests/integrations/onyx/test_contract.py`.
- ACL freshness, scope binding, and quarantine: `mnemosyne/integrations/onyx/acl.py`,
  `mnemosyne/integrations/onyx/config.py`, and
  `tests/integrations/onyx/test_acl.py`.
- At-least-once processing, ACL-before-noop, checkpoint safety, version
  history, and tombstones: `mnemosyne/integrations/onyx/worker.py`,
  `mnemosyne/integrations/onyx/checkpoint.py`, and
  `tests/integrations/onyx/test_worker.py`.
- Outbound policy, explicit section allowlist, live-row tombstone suppression,
  destination URL validation, and retry state:
  `mnemosyne/integrations/onyx/mapper.py`,
  `mnemosyne/integrations/onyx/exporter.py`,
  `mnemosyne/integrations/onyx/client.py`, and
  `tests/integrations/onyx/test_outbound_policy.py`.
- Live publication requires a complete, scope-bound operational approval
  record for provider/privacy, retention, destination ACL capability, and
  withdrawal/suppression verification; missing fields fail closed before
  `OnyxClient` construction.
- The CLI enforces preflight freshness, destination fingerprint stability,
  approved-host allowlisting, and the operational approval record before live
  publication.

Before enabling an external scope, all of the following are required:

- Provider and privacy approval recorded.
- Personal source, raw root, database, and generated Wiki paths explicitly
  separated.
- Synthetic dry-run reviewed; no personal note content is required for this
  check.
- Stable ID and content-hash no-op checks pass.
- ACL/destination mapping is explicit; missing or stale ACL is deny/quarantine.
- Tombstone and withdrawal behavior is verified for the target Onyx API.
- Credentials are available only through environment/secret storage.
