"""Request handlers for the Mnemosyne HTTP API.

Each handler receives parsed request data and returns a (status_code, body_dict) tuple.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

from mnemosyne.graph.knowledge_graph import Entity, KnowledgeGraph, Relation

logger = logging.getLogger(__name__)

VERSION = "0.2.0"

# SPEC-NLQUERY-001 security: cap question/message length to bound LLM token
# cost and storage. 8 KiB is well above any natural-language question while
# rejecting pathological multi-MB strings.
MAX_QUESTION_BYTES = 8 * 1024


class APIError(Exception):
    """Structured error that handlers raise to produce JSON error responses."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    def to_dict(self) -> Dict[str, Any]:
        return {"error": self.code, "message": self.message, "status": self.status}


class Handlers:
    """Stateless handler methods that operate on a shared KnowledgeGraph."""

    def __init__(self, kg: KnowledgeGraph, db_path: str) -> None:
        self.kg = kg
        self.db_path = db_path

    # -- Health / Meta -------------------------------------------------------

    def health(self) -> Tuple[int, Dict[str, Any]]:
        return 200, {"status": "ok", "version": VERSION}

    def stats(self) -> Tuple[int, Dict[str, Any]]:
        stats = self.kg.get_stats()
        db_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
        stats["db_size_bytes"] = db_size
        return 200, stats

    # -- Entities ------------------------------------------------------------

    def list_entities(
        self, params: Dict[str, str]
    ) -> Tuple[int, Dict[str, Any]]:
        entity_type = params.get("type")
        scope_id = params.get("scope_id")

        cursor = self.kg.conn.cursor()
        conditions: List[str] = []
        sql_params: List[Any] = []

        if entity_type:
            conditions.append("type = ?")
            sql_params.append(entity_type)
        if scope_id:
            conditions.append("scope_id = ?")
            sql_params.append(scope_id)

        where = " AND ".join(conditions) if conditions else "1=1"
        rows = cursor.execute(
            f"SELECT * FROM entities WHERE {where}", sql_params
        ).fetchall()

        entities = [_row_to_entity_dict(r) for r in rows]
        return 200, {"entities": entities, "count": len(entities)}

    def get_entity(self, entity_id: str) -> Tuple[int, Dict[str, Any]]:
        entity = self.kg.get_entity(entity_id)
        if entity is None:
            raise APIError("NOT_FOUND", f"Entity not found: {entity_id}", 404)
        return 200, _entity_to_dict(entity)

    def create_entity(self, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        required = ("id", "type", "name")
        missing = [f for f in required if f not in body]
        if missing:
            raise APIError(
                "VALIDATION_ERROR",
                f"Missing required fields: {', '.join(missing)}",
                422,
            )

        entity = Entity(
            id=body["id"],
            type=body["type"],
            name=body["name"],
            properties=body.get("properties", {}),
            created_at="",
            updated_at="",
            version=1,
            scope_id=body.get("scope_id"),
            source_channel=body.get("source_channel", "api"),
        )
        try:
            self.kg.add_entity(
                entity,
                scope_id=entity.scope_id,
                source_channel=entity.source_channel,
            )
        except Exception as exc:
            raise APIError("CONFLICT", str(exc), 409) from exc

        return 201, _entity_to_dict(entity)

    def update_entity(
        self, entity_id: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        existing = self.kg.get_entity(entity_id)
        if existing is None:
            raise APIError("NOT_FOUND", f"Entity not found: {entity_id}", 404)

        entity = Entity(
            id=entity_id,
            type=body.get("type", existing.type),
            name=body.get("name", existing.name),
            properties=body.get("properties", existing.properties),
            created_at=existing.created_at,
            updated_at=existing.updated_at,
            version=existing.version,
            scope_id=body.get("scope_id", existing.scope_id),
            source_channel=body.get("source_channel", existing.source_channel),
        )
        try:
            self.kg.update_entity(entity)
        except KeyError as exc:
            raise APIError("NOT_FOUND", str(exc), 404) from exc

        return 200, _entity_to_dict(entity)

    # -- Relations -----------------------------------------------------------

    def list_relations(
        self, params: Dict[str, str]
    ) -> Tuple[int, Dict[str, Any]]:
        source_id = params.get("source")
        target_id = params.get("target")
        rel_type = params.get("type")

        cursor = self.kg.conn.cursor()
        conditions: List[str] = []
        sql_params: List[Any] = []

        if source_id:
            conditions.append("source_id = ?")
            sql_params.append(source_id)
        if target_id:
            conditions.append("target_id = ?")
            sql_params.append(target_id)
        if rel_type:
            conditions.append("relation_type = ?")
            sql_params.append(rel_type)

        where = " AND ".join(conditions) if conditions else "1=1"
        rows = cursor.execute(
            f"SELECT * FROM relations WHERE {where}", sql_params
        ).fetchall()

        relations = [_row_to_relation_dict(r) for r in rows]
        return 200, {"relations": relations, "count": len(relations)}

    def get_relation(self, relation_id: str) -> Tuple[int, Dict[str, Any]]:
        relation = self.kg.get_relation(relation_id)
        if relation is None:
            raise APIError("NOT_FOUND", f"Relation not found: {relation_id}", 404)
        return 200, _relation_to_dict(relation)

    def create_relation(self, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        required = ("id", "source_id", "target_id", "relation_type")
        missing = [f for f in required if f not in body]
        if missing:
            raise APIError(
                "VALIDATION_ERROR",
                f"Missing required fields: {', '.join(missing)}",
                422,
            )

        relation = Relation(
            id=body["id"],
            source_id=body["source_id"],
            target_id=body["target_id"],
            relation_type=body["relation_type"],
            properties=body.get("properties", {}),
            created_at="",
            version=1,
            scope_id=body.get("scope_id"),
            source_channel=body.get("source_channel", "api"),
        )
        try:
            self.kg.add_relation(
                relation,
                scope_id=relation.scope_id,
                source_channel=relation.source_channel,
            )
        except Exception as exc:
            raise APIError("CONFLICT", str(exc), 409) from exc

        return 201, _relation_to_dict(relation)

    # -- Query / Search ------------------------------------------------------

    def query(self, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        query_str = body.get("query")
        if not query_str:
            raise APIError("VALIDATION_ERROR", "Missing 'query' field", 422)

        result = self.kg.query(query_str)
        return 200, result

    def search(self, params: Dict[str, str]) -> Tuple[int, Dict[str, Any]]:
        q = params.get("q", "")
        limit = int(params.get("limit", "50"))

        if not q:
            raise APIError("VALIDATION_ERROR", "Missing 'q' parameter", 422)

        # Delegate to the built-in search query
        result = self.kg.query(f"search:{q}")

        # Apply limit
        if "results" in result and len(result["results"]) > limit:
            result["results"] = result["results"][:limit]
            result["truncated"] = True

        return 200, result

    # -- NL Query / Chat (SPEC-NLQUERY-001) ---------------------------------

    def ask(self, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """POST /api/v1/ask: single-shot NL query -> answer + citations."""
        question = body.get("question")
        if not question:
            raise APIError("VALIDATION_ERROR", "Missing 'question' field", 422)
        _enforce_question_cap(question)
        scope = _scope_from_body(body)
        result = _run_nl_query(self.kg, question, scope)
        return 200, result

    def chat(self, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """POST /api/v1/chat: multi-turn chat with persisted sessions."""
        message = body.get("message")
        if not message:
            raise APIError("VALIDATION_ERROR", "Missing 'message' field", 422)
        _enforce_question_cap(message, field="message")
        scope = _scope_from_body(body)
        session_id = body.get("session_id")

        from mnemosyne.query.chat_store import (
            ChatStore,
            build_context_window,
        )

        store = ChatStore(self.kg.conn)
        if session_id:
            # IDOR guard: verify the caller's project matches the session's
            # stored project_hash. 404 (not 403) avoids leaking existence.
            existing = store.get_session(
                session_id, project_hash=scope.get("project")
            )
            if existing is None:
                raise APIError(
                    "NOT_FOUND", f"chat session not found: {session_id}", 404
                )
        else:
            session_id = store.create_session(
                project_hash=scope.get("project"),
                scope_id=scope.get("scope_id"),
            )

        # Persist the user turn before synthesis so the window includes it.
        store.append_turn(session_id, "user", message)
        prior_turns = store.list_turns(session_id)
        context_window = build_context_window(prior_turns)

        result = _run_nl_query(
            self.kg, message, scope, context=context_window
        )
        # Persist the assistant turn (answer + citations) — append-only.
        store.append_turn(
            session_id, "assistant", result["answer"], result["citations"]
        )

        result["session_id"] = session_id
        result["turn_id"] = store.list_turns(session_id)[-1]["turn_id"]
        return 200, result

    def chat_list_sessions(
        self, params: Dict[str, str]
    ) -> Tuple[int, Dict[str, Any]]:
        """GET /api/v1/chat/sessions?project=<hash>."""
        from mnemosyne.query.chat_store import ChatStore

        store = ChatStore(self.kg.conn)
        project = params.get("project")
        sessions = store.list_sessions(project_hash=project)
        return 200, {"sessions": sessions, "count": len(sessions)}

    def chat_get_session(
        self, session_id: str, params: Dict[str, str]
    ) -> Tuple[int, Dict[str, Any]]:
        """GET /api/v1/chat/sessions/<id>?project=<hash>: session meta + turns.

        IDOR guard: ``project`` query param is intersected with the session's
        ``project_hash``; mismatch returns 404 (no existence leak).
        """
        from mnemosyne.query.chat_store import ChatStore

        store = ChatStore(self.kg.conn)
        meta = store.get_session(
            session_id, project_hash=params.get("project")
        )
        if meta is None:
            raise APIError(
                "NOT_FOUND", f"chat session not found: {session_id}", 404
            )
        turns = store.list_turns(session_id)
        return 200, {"session": meta, "turns": turns, "count": len(turns)}

    def chat_archive_session(
        self, session_id: str, params: Dict[str, str]
    ) -> Tuple[int, Dict[str, Any]]:
        """DELETE /api/v1/chat/sessions/<id>?project=<hash>: tombstone only."""
        from mnemosyne.query.chat_store import ChatStore

        store = ChatStore(self.kg.conn)
        if (
            store.get_session(
                session_id, project_hash=params.get("project")
            )
            is None
        ):
            raise APIError(
                "NOT_FOUND", f"chat session not found: {session_id}", 404
            )
        archived = store.archive_session(session_id)
        return 200, {
            "session_id": session_id,
            "status": "archived" if archived else "already-archived",
            "deleted": False,  # REQ-NL-006: never a row delete
        }

    # -- Projects ------------------------------------------------------------

    def list_projects(self) -> Tuple[int, Dict[str, Any]]:
        projects = self.kg.list_projects()
        return 200, {"projects": projects, "count": len(projects)}

    def get_project(self, project_hash: str) -> Tuple[int, Dict[str, Any]]:
        project = self.kg.get_project_by_hash(project_hash)
        if project is None:
            raise APIError("NOT_FOUND", f"Project not found: {project_hash}", 404)
        return 200, project

    # -- Wiki ----------------------------------------------------------------

    def wiki_status(
        self, params: Dict[str, str]
    ) -> Tuple[int, Dict[str, Any]]:
        wiki_root = params.get("wiki_root")
        if not wiki_root:
            wiki_root = str(Path.home() / "mnemosyne" / "wiki")

        from mnemosyne.wiki.llm_wiki import LLMWikiMaintainer

        maintainer = LLMWikiMaintainer(wiki_root=wiki_root)
        result = maintainer.status(db_path=self.db_path)
        return 200, result

    def wiki_lint(
        self, params: Dict[str, str]
    ) -> Tuple[int, Dict[str, Any]]:
        wiki_root = params.get("wiki_root")
        if not wiki_root:
            wiki_root = str(Path.home() / "mnemosyne" / "wiki")

        from mnemosyne.wiki.llm_wiki import LLMWikiMaintainer

        maintainer = LLMWikiMaintainer(wiki_root=wiki_root)
        report = maintainer.lint(db_path=self.db_path)
        return 200, report.to_dict()


# -- Conversion helpers ------------------------------------------------------


def _scope_from_body(body: Dict[str, Any]) -> Dict[str, str]:
    """Extract the optional scope trio (scope_id/project/source_channel)."""
    out: Dict[str, str] = {}
    for key in ("scope_id", "project", "source_channel"):
        val = body.get(key)
        if val is not None:
            out[key] = str(val)
    return out


def _enforce_question_cap(value: Any, field: str = "question") -> None:
    """SPEC-NLQUERY-001 security: reject oversized question/message strings.

    Validates length in UTF-8 bytes so multi-byte (CJK) questions are bounded
    by the same memory budget as ASCII. Raises VALIDATION_ERROR (422).
    """
    if not isinstance(value, str):
        return
    if len(value.encode("utf-8")) > MAX_QUESTION_BYTES:
        raise APIError(
            "VALIDATION_ERROR",
            f"'{field}' exceeds {MAX_QUESTION_BYTES} bytes",
            422,
        )


def _run_nl_query(
    kg: KnowledgeGraph,
    question: str,
    scope: Dict[str, str],
    context: str | None = None,
) -> Dict[str, Any]:
    """Shared NL pipeline for /ask and /chat (router -> executor -> synth)."""
    from mnemosyne.extraction.longdoc.retriever import LongDocRetriever
    from mnemosyne.query import (
        AnswerSynthesizer,
        NLQueryRouter,
        QueryExecutor,
    )

    router = NLQueryRouter()
    plan = router.route(question, scope=scope)
    retriever = LongDocRetriever(kg.conn)
    executor = QueryExecutor(kg, longdoc_retriever=retriever)
    result = executor.run(plan)
    synth = AnswerSynthesizer()
    answer = synth.synthesize(question, result, context=context)
    return {
        "answer": answer["answer"],
        "citations": answer["citations"],
        "degraded": answer["degraded"],
        "plan": {
            "intent": plan.intent,
            "target_entities": plan.target_entities,
            "target_relations": plan.target_relations,
            "confidence": plan.confidence,
        },
    }


def _row_to_entity_dict(row: Any) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "type": row["type"],
        "name": row["name"],
        "properties": json.loads(row["properties"] or "{}"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "scope_id": row["scope_id"] if "scope_id" in row.keys() else None,
        "source_channel": (
            row["source_channel"] if "source_channel" in row.keys() else "legacy"
        ),
    }


def _row_to_relation_dict(row: Any) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "source_id": row["source_id"],
        "target_id": row["target_id"],
        "relation_type": row["relation_type"],
        "properties": json.loads(row["properties"] or "{}"),
        "created_at": row["created_at"],
        "version": row["version"],
        "scope_id": row["scope_id"] if "scope_id" in row.keys() else None,
        "source_channel": (
            row["source_channel"] if "source_channel" in row.keys() else "legacy"
        ),
    }


def _entity_to_dict(entity: Entity) -> Dict[str, Any]:
    return {
        "id": entity.id,
        "type": entity.type,
        "name": entity.name,
        "properties": entity.properties,
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
        "version": entity.version,
        "scope_id": entity.scope_id,
        "source_channel": entity.source_channel,
    }


def _relation_to_dict(relation: Relation) -> Dict[str, Any]:
    return {
        "id": relation.id,
        "source_id": relation.source_id,
        "target_id": relation.target_id,
        "relation_type": relation.relation_type,
        "properties": relation.properties,
        "created_at": relation.created_at,
        "version": relation.version,
        "scope_id": relation.scope_id,
        "source_channel": relation.source_channel,
    }
