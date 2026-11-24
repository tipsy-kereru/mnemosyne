"""Isolated synthetic stores and provider configs for evidence-search tests."""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from mnemosyne.graph.knowledge_graph import Entity, KnowledgeGraph
from mnemosyne.graph.lifecycle import LifecycleStore

CALLER = "meeting-assistant"


@dataclass
class World:
    root: Path
    db: Path
    scopes: Dict[str, str]
    config: Path


def put(kg: KnowledgeGraph, entity_id: str, name: str, scope: Optional[str],
        channel: str = "meeting-test", **props: Any) -> None:
    kg.add_entity(Entity(entity_id, "note", name, dict(props), "", ""), scope_id=scope,
                  source_channel=channel)


def lifecycle_source(kg: KnowledgeGraph, source_id: str, scope: str, entity_id: str,
                     name: str, revision: int = 1, **extra: Any) -> None:
    token = {
        "source_id": source_id,
        "revision": revision,
        "source_version": f"v{revision}",
        "content_hash": f"h{revision}",
        "extractor_version": "x1",
        "ontology_version": "o1",
    }
    store = LifecycleStore(kg)
    store.apply({"action": "observe", **token, "location": f"app://{source_id}",
                 "kind": "meeting", "source_channel": "meeting-test", "scope_id": scope})
    item = {"id": entity_id, "type": "decision", "name": name, **extra}
    store.apply({"action": "replace", **token, "job_id": f"{source_id}-{revision}",
                 "complete": True, "entities": [item], "relations": [],
                 "checkpoint": {"cursor": revision}})


def write_config(path: Path, store: Path, grants: List[Dict[str, Any]],
                 caller: str = CALLER) -> Path:
    path.write_text(json.dumps({"version": 1, "store": str(store), "effective_caller": caller,
                                "grants": grants}), encoding="utf-8")
    return path


def grant(app: str, scope: str, gid: Optional[str] = None, status: str = "active",
          caller: str = CALLER) -> Dict[str, Any]:
    return {"grant_id": gid or f"g-{app}-{scope}-{status}", "caller": caller,
            "app_project": app, "scope_id": scope, "status": status}


def build_world(tmp_path: Path, noise: int = 0) -> World:
    root = tmp_path / "world"
    (root / "store").mkdir(parents=True)
    db = root / "store" / "knowledge.db"
    kg = KnowledgeGraph(str(db))
    try:
        alpha = kg.create_scope("project", "Alpha").id
        beta = kg.create_scope("project", "Beta").id
        topic = kg.create_scope("topic", "Alpha topic", parent_id=alpha).id
        sibling = kg.create_scope("topic", "Alpha sibling", parent_id=alpha).id
        put(kg, "a-budget", "Alpha budget decision", alpha,
            summary="The budget was approved for the alpha launch")
        put(kg, "a-risk", "Alpha schedule risk", alpha,
            summary="Schedule risk noted; budget overrun unlikely")
        put(kg, "b-budget", "Beta budget freeze", beta, summary="BETAONLY budget freeze")
        put(kg, "g-budget", "Global budget policy", None, summary="GLOBALONLY budget policy")
        put(kg, "t-budget", "Topic budget note", topic, summary="CHILDONLY budget note")
        put(kg, "s-budget", "Sibling budget note", sibling, summary="SIBLINGONLY budget note")
        put(kg, "a-slack", "Isolated budget", alpha, channel="work-slack", summary="ISOLATED budget")
        put(kg, "a-gone", "Retired budget", alpha, summary="TOMBSTONED budget")
        kg.tombstone_entity("a-gone", "retired")
        lifecycle_source(kg, "alpha-meeting", alpha, "a-decision", "Budget approval decision",
                         properties={"decision": "approve the budget"},
                         locator="00:12:30", excerpt="We agree the budget is approved.")
        lifecycle_source(kg, "beta-meeting", beta, "b-decision", "Beta budget decision",
                         properties={"decision": "BETAONLY freeze"},
                         locator="00:01:00", excerpt="Beta freezes the budget.")
        for i in range(noise):
            put(kg, f"n-{i}", f"noise {i}", beta, summary="budget budget budget filler")
            put(kg, f"gn-{i}", f"global noise {i}", None, summary="budget filler")
    finally:
        kg.close()
    age(db)
    scopes = {"alpha": alpha, "beta": beta, "topic": topic, "sibling": sibling}
    config = write_config(
        root / "provider.json", db,
        [grant("alpha-app", alpha), grant("beta-app", beta), grant("topic-app", topic)],
    )
    return World(root, db, scopes, config)


def age(db: Path, seconds: int = 3600) -> None:
    """Make the main store file look quiet (test-side only, never done by search)."""
    old = time.time_ns() - seconds * 1_000_000_000
    os.utime(db, ns=(old, old))


def tree_state(root: Path) -> Dict[str, Any]:
    """Name, size, mtime and content digest of everything under ``root``."""
    state: Dict[str, Any] = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_dir():
            state[rel] = "dir"
        else:
            st = p.stat()
            state[rel] = (st.st_size, st.st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
    return state
