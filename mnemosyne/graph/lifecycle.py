"""Source evidence and approved user changes; SQLite is the canonical state.

``revision`` is a connector-supplied authoritative, increasing observation order,
not an arrival timestamp or a hash. Connectors must revalidate the source before
submitting a completed extraction. Unordered notifications must be reconciled at
that boundary, never assigned revisions in their arrival order here.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class LifecycleError(ValueError):
    """A lifecycle precondition failed; no partial mutation was committed."""


_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_LOCK = threading.Lock()
_TOKEN = ("revision", "source_version", "content_hash", "extractor_version", "ontology_version")
_RESERVED = {
    "source_file",
    "source_files",
    "evidence",
    "corrections",
    "conflicts",
    "review_required",
}


def writer_lock(db_path):
    key = str(Path(db_path).resolve())
    with _LOCKS_LOCK:
        return _LOCKS.setdefault(key, threading.RLock())


def _json(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _now():
    return datetime.now(timezone.utc).isoformat()


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _text(data, key):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise LifecycleError(f"{key} must be a nonempty string")
    return value


def prepare_lifecycle_backup(conn, db_path):
    """Back up an existing pre-lifecycle database before ANY schema migration."""
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='lifecycle_state'").fetchone():
        return None
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone():
        return None
    path = Path(db_path)
    if str(path) == ":memory:":
        return None
    backup = path.with_name(f"{path.name}.pre-lifecycle-{uuid.uuid4().hex}.bak")
    # SQLite backup includes committed WAL content, unlike copying the DB file.
    fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    dest = sqlite3.connect(str(backup))
    try:
        conn.backup(dest)
        if dest.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise LifecycleError("pre-migration backup failed integrity check")
    finally:
        dest.close()
    return str(backup)


def init_lifecycle_schema(conn, db_path):
    """Additive migration. Existing unattributed rows are preserved verbatim."""
    with writer_lock(db_path):
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='lifecycle_state'").fetchone():
            return
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='lifecycle_state'").fetchone():
                return
            conn.execute(
                "CREATE TABLE lifecycle_state (id INTEGER PRIMARY KEY CHECK(id=1), generation INTEGER NOT NULL, wiki_dirty INTEGER NOT NULL, writing INTEGER NOT NULL)"
            )
            conn.execute("INSERT INTO lifecycle_state VALUES (1,0,0,0)")
            conn.execute("""CREATE TABLE lifecycle_sources (
                source_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, source_version TEXT NOT NULL,
                content_hash TEXT NOT NULL, extractor_version TEXT NOT NULL, ontology_version TEXT NOT NULL,
                location TEXT NOT NULL, kind TEXT NOT NULL, scope_id TEXT, source_channel TEXT NOT NULL,
                applied_revision INTEGER, applied_digest TEXT, state TEXT NOT NULL, checkpoint TEXT,
                note_text TEXT, updated_at TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE lifecycle_versions (
                source_id TEXT NOT NULL, revision INTEGER NOT NULL, token TEXT NOT NULL,
                state TEXT NOT NULL, observed_at TEXT NOT NULL, applied_at TEXT, note_text TEXT,
                PRIMARY KEY(source_id, revision))""")
            conn.execute("""CREATE TABLE lifecycle_evidence (
                source_id TEXT NOT NULL, revision INTEGER NOT NULL, kind TEXT NOT NULL,
                target_id TEXT NOT NULL, payload TEXT NOT NULL, active INTEGER NOT NULL,
                PRIMARY KEY(source_id,revision,kind,target_id))""")
            conn.execute(
                "CREATE INDEX lifecycle_evidence_active ON lifecycle_evidence(active,kind,target_id)"
            )
            conn.execute("""CREATE TABLE lifecycle_managed (
                kind TEXT NOT NULL, target_id TEXT NOT NULL, scope_id TEXT,
                PRIMARY KEY(kind,target_id))""")
            conn.execute("""CREATE TABLE lifecycle_legacy (
                kind TEXT NOT NULL, target_id TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(kind,target_id))""")
            conn.execute("""CREATE TABLE lifecycle_approvals (
                approval_id TEXT PRIMARY KEY, actor TEXT NOT NULL, generation INTEGER NOT NULL,
                change_json TEXT NOT NULL, created_at TEXT NOT NULL, consumed INTEGER NOT NULL DEFAULT 0)""")
            conn.execute("""CREATE TABLE lifecycle_changes (
                record_id TEXT PRIMARY KEY, approval_id TEXT NOT NULL, actor TEXT NOT NULL,
                action TEXT NOT NULL, target_kind TEXT NOT NULL, target_id TEXT NOT NULL,
                scope_id TEXT, change_json TEXT NOT NULL, active INTEGER NOT NULL,
                generation INTEGER NOT NULL, created_at TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE lifecycle_jobs (
                job_id TEXT PRIMARY KEY, request_digest TEXT NOT NULL, result TEXT NOT NULL,
                completed_at TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE lifecycle_reviews (
                record_id TEXT NOT NULL, source_id TEXT NOT NULL, revision INTEGER NOT NULL,
                detail TEXT NOT NULL, PRIMARY KEY(record_id,source_id,revision))""")
            # A committed gate is always closed. BEGIN IMMEDIATE serializes all
            # SQLite writers; even legacy raw-SQL writers cannot resurrect rows.
            for table, kind in (("entities", "entity"), ("relations", "relation")):
                for op, row in (("INSERT", "NEW"), ("UPDATE", "OLD"), ("DELETE", "OLD")):
                    identities = f"({row}.id, NEW.id)" if op == "UPDATE" else f"({row}.id)"
                    conn.execute(f"""CREATE TRIGGER lifecycle_guard_{table}_{op.lower()}
                        BEFORE {op} ON {table}
                        WHEN (SELECT writing FROM lifecycle_state WHERE id=1)=0
                        AND EXISTS(SELECT 1 FROM lifecycle_managed WHERE kind='{kind}' AND target_id IN {identities})
                        BEGIN SELECT RAISE(ABORT, 'lifecycle-managed record: use lifecycle API'); END""")
                    conn.execute(f"""CREATE TRIGGER lifecycle_dirty_{table}_{op.lower()}
                        AFTER {op} ON {table}
                        WHEN (SELECT writing FROM lifecycle_state WHERE id=1)=0
                        AND ((SELECT generation FROM lifecycle_state WHERE id=1)>0 OR EXISTS(SELECT 1 FROM lifecycle_approvals))
                        BEGIN UPDATE lifecycle_state SET generation=generation+1,wiki_dirty=1 WHERE id=1; END""")


class LifecycleStore:
    def __init__(self, kg):
        self.kg = kg
        self.conn = kg.conn
        self.lock = writer_lock(kg.db_path)

    def status(self):
        row = self.conn.execute(
            "SELECT generation,wiki_dirty FROM lifecycle_state WHERE id=1"
        ).fetchone()
        return {"generation": row["generation"], "wiki_dirty": bool(row["wiki_dirty"])}

    def inspect(self, target_kind, target_id):
        """Operator history, including hidden evidence; never an answer query."""
        with self.lock:
            self.conn.execute("BEGIN")
            try:
                scope = self._target_scope(target_kind, target_id)
                if target_kind == "source":
                    evidence = self.conn.execute(
                        "SELECT * FROM lifecycle_evidence WHERE source_id=? ORDER BY revision,kind,target_id",
                        (target_id,),
                    ).fetchall()
                    source = self._source(target_id)
                    versions = [
                        dict(r)
                        for r in self.conn.execute(
                            "SELECT * FROM lifecycle_versions WHERE source_id=? ORDER BY revision",
                            (target_id,),
                        )
                    ]
                else:
                    evidence = self.conn.execute(
                        "SELECT * FROM lifecycle_evidence WHERE kind=? AND target_id=? ORDER BY source_id,revision",
                        (target_kind, target_id),
                    ).fetchall()
                    source, versions = None, []
                changes = self.conn.execute(
                    "SELECT * FROM lifecycle_changes WHERE target_kind=? AND target_id=? ORDER BY generation",
                    (target_kind, target_id),
                ).fetchall()
                return {
                    "target_kind": target_kind,
                    "target_id": target_id,
                    "scope_id": scope,
                    "source": source,
                    "versions": versions,
                    "evidence": [
                        {**dict(r), "payload": json.loads(r["payload"])} for r in evidence
                    ],
                    "changes": [
                        {**dict(r), "change": json.loads(r["change_json"])} for r in changes
                    ],
                    **self.status(),
                }
            finally:
                self.conn.rollback()

    @contextmanager
    def _transaction(self):
        with self.lock:
            if self.conn.in_transaction:
                raise LifecycleError("lifecycle mutation cannot join an existing transaction")
            synchronous = self.conn.execute("PRAGMA synchronous").fetchone()[0]
            self.conn.execute("PRAGMA synchronous=FULL")
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                self.conn.execute("UPDATE lifecycle_state SET writing=1 WHERE id=1")
                yield
                self.conn.execute("UPDATE lifecycle_state SET writing=0 WHERE id=1")
                self.conn.commit()
            except BaseException:
                self.conn.rollback()
                raise
            finally:
                self.conn.execute(f"PRAGMA synchronous={synchronous}")

    def assert_unmanaged(self, kind, target_id):
        if self.conn.execute(
            "SELECT 1 FROM lifecycle_managed WHERE kind=? AND target_id=?", (kind, target_id)
        ).fetchone():
            raise LifecycleError("lifecycle-managed record: use lifecycle API")

    def apply(self, request: dict) -> dict:
        if not isinstance(request, dict):
            raise LifecycleError("request must be an object")
        # Validate JSON before opening a transaction, including nonfinite numbers.
        try:
            request = json.loads(_json(request))
        except (ValueError, TypeError) as exc:
            raise LifecycleError("request must contain finite JSON values") from exc
        action = _text(request, "action")
        handlers = {
            "observe": self._observe,
            "replace": self._replace,
            "delete": self._delete,
            "approve": self._approve,
            "execute": self._execute,
        }
        if action not in handlers:
            raise LifecycleError("unknown lifecycle action")
        with self._transaction():
            digest = _digest(request)
            job_id = (
                _text(request, "job_id") if action in {"replace", "delete", "execute"} else None
            )
            if job_id:
                job = self.conn.execute(
                    "SELECT * FROM lifecycle_jobs WHERE job_id=?", (job_id,)
                ).fetchone()
                if job:
                    if job["request_digest"] != digest:
                        raise LifecycleError("job_id reused for a different request")
                    stored = json.loads(job["result"])
                    return {
                        **stored,
                        "status": "duplicate",
                        "applied_generation": stored["generation"],
                        **self.status(),
                    }
            result = handlers[action](request)
            result.update(self.status())
            if job_id:
                self.conn.execute(
                    "INSERT INTO lifecycle_jobs VALUES (?,?,?,?)",
                    (job_id, digest, _json(result), _now()),
                )
        self.kg.nx_graph = self.kg._build_networkx()
        return result

    def _bump(self, *, dirty=True):
        self.conn.execute(
            "UPDATE lifecycle_state SET generation=generation+1, wiki_dirty=MAX(wiki_dirty,?) WHERE id=1",
            (int(dirty),),
        )

    def _source(self, source_id):
        row = self.conn.execute(
            "SELECT * FROM lifecycle_sources WHERE source_id=?", (source_id,)
        ).fetchone()
        if row is None:
            raise LifecycleError("unknown source_id")
        return dict(row)

    def _validate_token(self, req):
        if type(req.get("revision")) is not int or req["revision"] <= 0:
            raise LifecycleError("revision must be a positive authoritative integer")
        for key in _TOKEN[1:]:
            _text(req, key)
        return {key: req[key] for key in _TOKEN}

    def _observe(self, req):
        sid = _text(req, "source_id")
        if sid.startswith("legacy:"):
            raise LifecycleError("legacy: is reserved for unattributed migration evidence")
        token = self._validate_token(req)
        location, kind, channel = (
            _text(req, key) for key in ("location", "kind", "source_channel")
        )
        from mnemosyne.graph.knowledge_graph import ISOLATED_SOURCE_CHANNELS

        if channel in ISOLATED_SOURCE_CHANNELS:
            raise LifecycleError("isolated source channel cannot enter lifecycle graph")
        scope = req.get("scope_id")
        if scope is not None and (not isinstance(scope, str) or not scope):
            raise LifecycleError("scope_id must be null or a nonempty string")
        prior = self.conn.execute(
            "SELECT * FROM lifecycle_sources WHERE source_id=?", (sid,)
        ).fetchone()
        if prior:
            if any(
                prior[k] != v
                for k, v in (("kind", kind), ("scope_id", scope), ("source_channel", channel))
            ):
                raise LifecycleError("source identity scope/kind/channel cannot change")
            if token["revision"] < prior["revision"]:
                raise LifecycleError("stale source observation")
            if token["revision"] == prior["revision"]:
                if any(prior[k] != v for k, v in token.items()) or prior["location"] != location:
                    raise LifecycleError("same revision has different metadata")
                return {"status": "duplicate", "source_id": sid}
            self.conn.execute(
                """UPDATE lifecycle_sources SET revision=?,source_version=?,content_hash=?,
                extractor_version=?,ontology_version=?,location=?,state='pending',updated_at=? WHERE source_id=?""",
                (*token.values(), location, _now(), sid),
            )
        else:
            self.conn.execute(
                """INSERT INTO lifecycle_sources
                (source_id,revision,source_version,content_hash,extractor_version,ontology_version,
                 location,kind,scope_id,source_channel,state,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,'pending',?)""",
                (sid, *token.values(), location, kind, scope, channel, _now()),
            )
        self.conn.execute(
            "INSERT INTO lifecycle_versions (source_id,revision,token,state,observed_at) VALUES (?,?,?,'pending',?)",
            (sid, token["revision"], _json(token), _now()),
        )
        self._bump(dirty=False)
        return {"status": "observed", "source_id": sid}

    def _fence(self, req):
        source = self._source(_text(req, "source_id"))
        token = self._validate_token(req)
        if any(source[k] != v for k, v in token.items()):
            raise LifecycleError("stale extraction: source or processing rules changed")
        if not isinstance(req.get("checkpoint"), dict):
            raise LifecycleError("checkpoint must be an object")
        return source

    def _enroll(self, kind, target_id, scope):
        existing = self.conn.execute(
            "SELECT scope_id FROM lifecycle_managed WHERE kind=? AND target_id=?", (kind, target_id)
        ).fetchone()
        if existing:
            if existing["scope_id"] != scope:
                raise LifecycleError("target_id collision across scopes")
            return
        table = "entities" if kind == "entity" else "relations"
        row = self.conn.execute(f"SELECT * FROM {table} WHERE id=?", (target_id,)).fetchone()
        if row:
            from mnemosyne.graph.knowledge_graph import ISOLATED_SOURCE_CHANNELS

            if row["scope_id"] != scope or row["source_channel"] in ISOLATED_SOURCE_CHANNELS:
                raise LifecycleError("legacy target scope/channel collision")
            # We cannot reconstruct per-source provenance from old merged rows.
            # Preserve them explicitly as unattributed, independently supported.
            payload = dict(row)
            payload["properties"] = json.loads(payload["properties"] or "{}")
            self.conn.execute(
                "INSERT INTO lifecycle_legacy VALUES (?,?,?)", (kind, target_id, _json(payload))
            )
        self.conn.execute("INSERT INTO lifecycle_managed VALUES (?,?,?)", (kind, target_id, scope))

    def _validated_payloads(self, req, source):
        if req.get("complete") is not True:
            raise LifecycleError("only complete, validated extraction may replace evidence")
        payloads = []
        for plural, kind in (("entities", "entity"), ("relations", "relation")):
            items = req.get(plural)
            if not isinstance(items, list):
                raise LifecycleError(f"{plural} must be a complete array")
            seen = set()
            for item in items:
                if not isinstance(item, dict):
                    raise LifecycleError("evidence item must be an object")
                identity = _text(item, "id")
                if identity in seen:
                    raise LifecycleError("duplicate target in evidence set")
                seen.add(identity)
                keys = (
                    ("type", "name")
                    if kind == "entity"
                    else ("source_id", "target_id", "relation_type")
                )
                payload = {"id": identity, **{key: _text(item, key) for key in keys}}
                props = item.get("properties", {})
                if not isinstance(props, dict) or _RESERVED.intersection(props):
                    raise LifecycleError("invalid properties or reserved provenance field")
                payload["properties"] = props
                # Bounded location/excerpt are evidence, not a second raw store.
                for key, limit in (("locator", 512), ("excerpt", 1200)):
                    if key in item:
                        if not isinstance(item[key], str) or len(item[key]) > limit:
                            raise LifecycleError(f"{key} exceeds evidence limit")
                        payload[key] = item[key]
                self._enroll(kind, identity, source["scope_id"])
                payloads.append((kind, identity, payload))
        entity_ids = {identity for kind, identity, _ in payloads if kind == "entity"}
        for kind, _, payload in payloads:
            if kind == "relation":
                for endpoint in (payload["source_id"], payload["target_id"]):
                    # Complete source evidence must carry its endpoint entities;
                    # otherwise another source's deletion could silently sever it.
                    if endpoint not in entity_ids:
                        raise LifecycleError(
                            "relation endpoint missing from complete source evidence"
                        )
        return payloads

    def _replace(self, req, *, approved_note=False):
        source = self._fence(req)
        payloads = self._validated_payloads(req, source)
        note = req.get("note_text")
        if source["kind"] == "user-note":
            if not isinstance(note, str) or not note.strip():
                raise LifecycleError("user-note requires canonical note_text")
        elif note is not None:
            raise LifecycleError("external source full text is not stored as a user note")
        applied_digest = _digest({"payloads": payloads, "note_text": note, "action": "replace"})
        if source["applied_revision"] == source["revision"]:
            if source["applied_digest"] != applied_digest:
                raise LifecycleError("applied revision cannot be rewritten with different evidence")
            return {"status": "duplicate", "source_id": source["source_id"]}
        if (
            source["kind"] == "user-note"
            and source["applied_revision"] is not None
            and not approved_note
        ):
            raise LifecycleError("user-note revision requires a bound revise-note approval")
        sid, revision = source["source_id"], source["revision"]
        self.conn.execute("UPDATE lifecycle_evidence SET active=0 WHERE source_id=?", (sid,))
        self.conn.executemany(
            "INSERT INTO lifecycle_evidence VALUES (?,?,?,?,?,1)",
            [
                (sid, revision, kind, identity, _json(payload))
                for kind, identity, payload in payloads
            ],
        )
        self.conn.execute("UPDATE lifecycle_sources SET note_text=? WHERE source_id=?", (note, sid))
        self._finish_source(source, applied_digest, req["checkpoint"], "applied")
        self._bump()
        review = self._project()
        return {
            "status": "review" if review else "applied",
            "source_id": sid,
            "entities": sum(k == "entity" for k, _, _ in payloads),
            "relations": sum(k == "relation" for k, _, _ in payloads),
        }

    def _delete(self, req):
        source = self._fence(req)
        if source["kind"] == "user-note":
            raise LifecycleError(
                "user-authored notes use approved archive/exclude, not source deletion"
            )
        proof = req.get("deletion", {})
        if not isinstance(proof, dict):
            raise LifecycleError("deletion requires confirmation")
        if proof.get("kind") == "reconciliation":
            if (
                proof.get("complete") is not True
                or not proof.get("scope")
                or not proof.get("boundary")
            ):
                raise LifecycleError("incomplete or unbounded reconciliation is not deletion")
            if proof["scope"] != source["scope_id"]:
                raise LifecycleError("reconciliation scope differs from source")
        elif proof.get("kind") != "explicit":
            raise LifecycleError("deletion requires an explicit signal or complete reconciliation")
        digest = _digest({"action": "delete", "deletion": proof})
        if source["applied_revision"] == source["revision"]:
            if source["applied_digest"] != digest:
                raise LifecycleError("deletion needs a new source revision")
            return {"status": "duplicate", "source_id": source["source_id"]}
        self.conn.execute(
            "UPDATE lifecycle_evidence SET active=0 WHERE source_id=?", (source["source_id"],)
        )
        self._finish_source(source, digest, req["checkpoint"], "deleted")
        self._bump()
        self._project()
        return {"status": "applied", "source_id": source["source_id"]}

    def _finish_source(self, source, digest, checkpoint, state):
        self.conn.execute(
            """UPDATE lifecycle_sources SET applied_revision=?,applied_digest=?,state=?,
            checkpoint=?,updated_at=? WHERE source_id=?""",
            (source["revision"], digest, state, _json(checkpoint), _now(), source["source_id"]),
        )
        self.conn.execute(
            "UPDATE lifecycle_versions SET state=?,applied_at=?,note_text=(SELECT note_text FROM lifecycle_sources WHERE source_id=?) WHERE source_id=? AND revision=?",
            (state, _now(), source["source_id"], source["source_id"], source["revision"]),
        )

    def _target_scope(self, kind, identity):
        if kind == "source":
            return self._source(identity)["scope_id"]
        if kind not in {"entity", "relation"}:
            raise LifecycleError("target_kind must be source, entity or relation")
        row = self.conn.execute(
            "SELECT scope_id FROM lifecycle_managed WHERE kind=? AND target_id=?", (kind, identity)
        ).fetchone()
        if row:
            return row["scope_id"]
        table = "entities" if kind == "entity" else "relations"
        row = self.conn.execute(f"SELECT scope_id FROM {table} WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise LifecycleError("unknown target")
        return row["scope_id"]

    def _validate_change(self, change):
        if not isinstance(change, dict):
            raise LifecycleError("change must be an object")
        action = _text(change, "action")
        if action not in {"correct", "retract", "archive", "exclude", "restore", "revise-note"}:
            raise LifecycleError("unsupported user change")
        if "record_id" in change and action not in {"restore", "retract"}:
            raise LifecycleError("record_id is only valid for explicit restoration or retraction")
        if "supersedes" in change and action != "correct":
            raise LifecycleError("supersedes is only valid for a correction")
        kind, identity = _text(change, "target_kind"), _text(change, "target_id")
        if "scope_id" not in change or change["scope_id"] != self._target_scope(kind, identity):
            raise LifecycleError("approval scope does not match target")
        if action == "revise-note":
            if kind != "source" or self._source(identity)["kind"] != "user-note":
                raise LifecycleError("revise-note must target a user-authored source")
            replacement = change.get("replacement")
            if not isinstance(replacement, dict) or replacement.get("source_id") != identity:
                raise LifecycleError("revise-note must bind the exact replacement")
            if self._fence(replacement)["applied_revision"] is None:
                raise LifecycleError("revise-note requires an existing user note")
            if (
                not isinstance(replacement.get("note_text"), str)
                or not replacement["note_text"].strip()
            ):
                raise LifecycleError("revise-note requires canonical note_text")
        if action == "correct":
            if kind == "source":
                raise LifecycleError("correct a claim; user-note edits use a new source version")
            if _text(change, "property") in _RESERVED or "value" not in change:
                raise LifecycleError("correction must name a non-provenance property and value")
            if not isinstance(change.get("effective_scope"), dict):
                raise LifecycleError("correction requires an explicit effective_scope")
            # This API supports the entire selected claim. Temporal/conditional
            # predicates cannot silently become unconditional overrides.
            if change["effective_scope"] != {"kind": "claim"}:
                raise LifecycleError("supported effective_scope is {'kind':'claim'}")
        if action in {"restore", "retract"} or change.get("supersedes"):
            record_id = (
                change.get("supersedes") if action == "correct" else _text(change, "record_id")
            )
            row = self.conn.execute(
                "SELECT * FROM lifecycle_changes WHERE record_id=? AND active=1", (record_id,)
            ).fetchone()
            allowed = {"archive", "exclude"} if action == "restore" else {"correct"}
            if (
                row is None
                or row["action"] not in allowed
                or row["target_kind"] != kind
                or row["target_id"] != identity
                or row["scope_id"] != change["scope_id"]
            ):
                raise LifecycleError("change does not match an active target record")
            if (
                action == "correct"
                and json.loads(row["change_json"])["property"] != change["property"]
            ):
                raise LifecycleError("superseded correction must target the same claim")

    def _approve(self, req):
        aid, actor = _text(req, "approval_id"), _text(req, "actor")
        change = req.get("change")
        self._validate_change(change)
        generation = self.status()["generation"]
        if (
            type(req.get("expected_generation")) is not int
            or req["expected_generation"] != generation
        ):
            raise LifecycleError("stale approval generation")
        prior = self.conn.execute(
            "SELECT * FROM lifecycle_approvals WHERE approval_id=?", (aid,)
        ).fetchone()
        if prior:
            if (
                prior["actor"] != actor
                or prior["generation"] != generation
                or prior["change_json"] != _json(change)
            ):
                raise LifecycleError("approval_id reused for a different approval")
            return {"status": "duplicate", "approval_id": aid}
        self.conn.execute(
            "INSERT INTO lifecycle_approvals VALUES (?,?,?,?,?,0)",
            (aid, actor, generation, _json(change), _now()),
        )
        return {"status": "approved", "approval_id": aid}

    def _execute(self, req):
        approval = self.conn.execute(
            "SELECT * FROM lifecycle_approvals WHERE approval_id=?", (_text(req, "approval_id"),)
        ).fetchone()
        if approval is None or approval["actor"] != _text(req, "actor"):
            raise LifecycleError("approval missing or actor differs")
        if approval["consumed"] or approval["generation"] != self.status()["generation"]:
            raise LifecycleError("approval consumed or stale")
        change = json.loads(approval["change_json"])
        self._validate_change(change)
        kind, identity, action = change["target_kind"], change["target_id"], change["action"]
        if kind != "source":
            self._enroll(kind, identity, change["scope_id"])
        if action == "correct":
            active = self.conn.execute(
                "SELECT record_id,change_json FROM lifecycle_changes WHERE action='correct' AND active=1 AND target_kind=? AND target_id=?",
                (kind, identity),
            ).fetchall()
            for row in active:
                if json.loads(row["change_json"])["property"] == change["property"] and row[
                    "record_id"
                ] != change.get("supersedes"):
                    raise LifecycleError("explicitly supersede the active correction")
        withdrawn = (
            change.get("supersedes")
            if action == "correct"
            else (change.get("record_id") if action in {"restore", "retract"} else None)
        )
        if withdrawn:
            self.conn.execute(
                "UPDATE lifecycle_changes SET active=0 WHERE record_id=?", (withdrawn,)
            )
        if action == "revise-note":
            self._replace(change["replacement"], approved_note=True)
        else:
            self._bump()
        record_id = "change-" + uuid.uuid4().hex
        self.conn.execute(
            "INSERT INTO lifecycle_changes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                record_id,
                approval["approval_id"],
                approval["actor"],
                action,
                kind,
                identity,
                change["scope_id"],
                _json(change),
                int(action not in {"restore", "retract"}),
                self.status()["generation"],
                _now(),
            ),
        )
        self.conn.execute(
            "UPDATE lifecycle_approvals SET consumed=1 WHERE approval_id=?",
            (approval["approval_id"],),
        )
        self._project()
        return {"status": "applied", "record_id": record_id}

    def _project(self):
        """Recompute managed current rows; evidence/history is never deleted."""
        changes = [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM lifecycle_changes WHERE active=1 ORDER BY generation,record_id"
            )
        ]
        hidden = {
            (r["target_kind"], r["target_id"])
            for r in changes
            if r["action"] in {"archive", "exclude"}
        }
        corrections = {}
        for row in changes:
            if row["action"] == "correct":
                corrections.setdefault((row["target_kind"], row["target_id"]), []).append(row)
        supports = {}
        for row in self.conn.execute("""SELECT e.*,s.location,s.scope_id,s.source_channel,s.state FROM lifecycle_evidence e
                JOIN lifecycle_sources s USING(source_id) WHERE e.active=1 ORDER BY e.source_id,e.target_id"""):
            if ("source", row["source_id"]) not in hidden:
                supports.setdefault((row["kind"], row["target_id"]), []).append(
                    (dict(row), json.loads(row["payload"]))
                )
        for row in self.conn.execute("SELECT * FROM lifecycle_legacy"):
            payload = json.loads(row["payload"])
            supports.setdefault((row["kind"], row["target_id"]), []).insert(
                0,
                (
                    {
                        "source_id": "legacy:unattributed",
                        "revision": 0,
                        "location": "",
                        "scope_id": payload["scope_id"],
                        "source_channel": payload["source_channel"],
                    },
                    payload,
                ),
            )
        projected = {}
        review = False
        self.conn.execute("UPDATE lifecycle_sources SET state='applied' WHERE state='review'")
        for key, items in supports.items():
            if key in hidden:
                continue
            kind, identity = key
            first_meta, first = items[0]
            payload = {
                k: first[k]
                for k in (
                    ("type", "name")
                    if kind == "entity"
                    else ("source_id", "target_id", "relation_type")
                )
            }
            properties, conflicts, provenance = {}, {}, []
            for meta, item in items:
                for field in payload:
                    if item[field] != payload[field]:
                        raise LifecycleError(
                            f"incompatible identity for {kind} {identity}: {field}"
                        )
                provenance.append(
                    {
                        "source_id": meta["source_id"],
                        "revision": meta["revision"],
                        "location": meta["location"],
                        **{k: item[k] for k in ("locator", "excerpt") if k in item},
                    }
                )
                for prop, value in item["properties"].items():
                    if prop in _RESERVED:
                        continue
                    if prop not in properties:
                        properties[prop] = value
                    elif properties[prop] != value:
                        conflicts.setdefault(prop, []).append(
                            {
                                "existing": properties[prop],
                                "incoming": value,
                                "source_id": meta["source_id"],
                                "revision": meta["revision"],
                                "resolution": "unresolved",
                            }
                        )
            if conflicts:
                review = True
                properties["conflicts"] = conflicts
                for meta, _ in items:
                    if meta["revision"]:
                        self.conn.execute(
                            "UPDATE lifecycle_sources SET state='review' WHERE source_id=? AND state != 'pending'",
                            (meta["source_id"],),
                        )
            correction_refs = []
            correction_conflict = False
            for correction in corrections.get(key, []):
                change = json.loads(correction["change_json"])
                prop = change["property"]
                for meta, item in items:
                    if prop in item["properties"] and item["properties"][prop] != change["value"]:
                        review = True
                        correction_conflict = True
                        self.conn.execute(
                            "INSERT OR IGNORE INTO lifecycle_reviews VALUES (?,?,?,?)",
                            (
                                correction["record_id"],
                                meta["source_id"],
                                meta["revision"],
                                _json(
                                    {
                                        "property": prop,
                                        "source_value": item["properties"][prop],
                                        "corrected_value": change["value"],
                                    }
                                ),
                            ),
                        )
                        if meta["revision"]:
                            self.conn.execute(
                                "UPDATE lifecycle_sources SET state='review' WHERE source_id=? AND state != 'pending'",
                                (meta["source_id"],),
                            )
                properties[prop] = change["value"]
                correction_refs.append(
                    {
                        "record_id": correction["record_id"],
                        "property": prop,
                        "effective_scope": change["effective_scope"],
                    }
                )
            if correction_refs:
                properties["corrections"] = correction_refs
            properties["evidence"] = provenance
            locations = sorted({meta["location"] for meta, _ in items if meta["location"]})
            properties["source_files"] = locations
            properties["source_file"] = locations[0] if locations else "graph://legacy-unattributed"
            properties["review_required"] = bool(conflicts or correction_conflict)
            projected[key] = {
                **payload,
                "properties": properties,
                "scope_id": first_meta["scope_id"],
                "source_channel": first_meta["source_channel"],
            }
        # Relations with no currently visible endpoints are not answer evidence.
        visible_ids = {key[1] for key in projected if key[0] == "entity"}
        visible_ids.update(
            r[0]
            for r in self.conn.execute(
                "SELECT id FROM entities WHERE id NOT IN (SELECT target_id FROM lifecycle_managed WHERE kind='entity')"
            )
        )
        projected = {
            key: value
            for key, value in projected.items()
            if key[0] == "entity"
            or (value["source_id"] in visible_ids and value["target_id"] in visible_ids)
        }
        # Remove dependent legacy edges from the current projection, retaining
        # them as legacy evidence so restoration can re-evaluate their endpoints.
        for row in self.conn.execute("SELECT * FROM relations").fetchall():
            if row["source_id"] not in visible_ids or row["target_id"] not in visible_ids:
                self._enroll("relation", row["id"], row["scope_id"])
        now = _now()
        for kind, table in (("relation", "relations"), ("entity", "entities")):
            managed = self.conn.execute(
                "SELECT target_id FROM lifecycle_managed WHERE kind=?", (kind,)
            ).fetchall()
            for row in managed:
                identity = row[0]
                if (kind, identity) not in projected:
                    old = self.conn.execute(
                        f"SELECT * FROM {table} WHERE id=?", (identity,)
                    ).fetchone()
                    if old and kind == "entity":
                        self._history(old, now, "inactive", old["version"] + 1)
                    self.conn.execute(f"DELETE FROM {table} WHERE id=?", (identity,))
        for kind, table in (("entity", "entities"), ("relation", "relations")):
            for (item_kind, identity), payload in projected.items():
                if item_kind != kind:
                    continue
                old = self.conn.execute(f"SELECT * FROM {table} WHERE id=?", (identity,)).fetchone()
                props = _json(payload["properties"])
                if old and all(
                    old[k] == (props if k == "properties" else v) for k, v in payload.items()
                ):
                    continue
                version = old["version"] + 1 if old else self.status()["generation"]
                created = old["created_at"] if old else now
                if kind == "entity":
                    values = (
                        identity,
                        payload["type"],
                        payload["name"],
                        props,
                        created,
                        now,
                        version,
                        payload["scope_id"],
                        payload["source_channel"],
                    )
                    self.conn.execute(
                        """INSERT INTO entities (id,type,name,properties,created_at,updated_at,version,scope_id,source_channel)
                        VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET type=excluded.type,name=excluded.name,
                        properties=excluded.properties,updated_at=excluded.updated_at,version=excluded.version,
                        scope_id=excluded.scope_id,source_channel=excluded.source_channel,content_hash=NULL""",
                        values,
                    )
                    self._history(
                        {
                            "id": identity,
                            "type": payload["type"],
                            "name": payload["name"],
                            "properties": props,
                        },
                        now,
                        "projected",
                        version,
                    )
                else:
                    self.conn.execute(
                        """INSERT INTO relations (id,source_id,target_id,relation_type,properties,created_at,version,scope_id,source_channel)
                        VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET properties=excluded.properties,version=excluded.version,
                        source_id=excluded.source_id,target_id=excluded.target_id,relation_type=excluded.relation_type,
                        scope_id=excluded.scope_id,source_channel=excluded.source_channel""",
                        (
                            identity,
                            payload["source_id"],
                            payload["target_id"],
                            payload["relation_type"],
                            props,
                            created,
                            version,
                            payload["scope_id"],
                            payload["source_channel"],
                        ),
                    )
        # Persistent hybrid caches/embeddings must not retain obsolete claims.
        for table in ("search_cache", "embeddings"):
            if self.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone():
                if table == "search_cache":
                    self.conn.execute("DELETE FROM search_cache")
                else:
                    self.conn.execute(
                        "DELETE FROM embeddings WHERE entity_id IN (SELECT target_id FROM lifecycle_managed WHERE kind='entity')"
                    )
        return review

    def _history(self, row, now, action, version):
        self.conn.execute(
            "INSERT INTO entity_history (entity_id,type,name,properties,changed_at,change_type,version) VALUES (?,?,?,?,?,?,?)",
            (row["id"], row["type"], row["name"], row["properties"], now, action, version),
        )

    def mark_wiki_clean(self, generation):
        with self._transaction():
            result = self.conn.execute(
                "UPDATE lifecycle_state SET wiki_dirty=0 WHERE id=1 AND generation=?", (generation,)
            )
            return result.rowcount == 1
