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
