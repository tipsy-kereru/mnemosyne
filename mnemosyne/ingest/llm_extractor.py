"""LLM-based entity/relation extractor for mnemosyne ingestion."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from mnemosyne.ingest.llm_bridge import SCHEMA_HINTS, LLMBridge

logger = logging.getLogger(__name__)


_CHUNK_SIZE = 3000


@dataclass
class IngestEntity:
    """Entity parsed from an LLM extraction response."""

    id: str
    label: str
    type: str
    source_file: str
    confidence: str = "EXTRACTED"
    confidence_score: float = 1.0
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class IngestRelation:
    """Relation parsed from an LLM extraction response."""

    source: str
    target: str
    relation: str
    confidence: str = "EXTRACTED"
    confidence_score: float = 1.0


@dataclass
class ParsedIngestResult:
    """Aggregated extraction output from one or more LLM calls."""

    entities: list[IngestEntity] = field(default_factory=list)
    relations: list[IngestRelation] = field(default_factory=list)
    source_file: str = ""
    domain: str = "daily"


_CODE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".rb"}
_TEXT_EXTS = {".md", ".txt", ".json", ".yml", ".yaml"}


# @MX:ANCHOR: [AUTO] LLMExtractor is the primary extraction interface.
# @MX:REASON: Used by Ingester._add_file() and Updater; fan_in >= 3.
class LLMExtractor:
    """Wraps :class:`LLMBridge` and chunks large inputs."""

    def __init__(self, bridge: Optional[LLMBridge] = None) -> None:
        self.bridge = bridge or LLMBridge()

    def extract_text(
        self,
        text: str,
        source_file: str = "",
        domain: str = "daily",
        scope_id: Optional[str] = None,
        source_channel: str = "cli",
    ) -> ParsedIngestResult:
        """Extract entities + relations from a text string."""
        result = ParsedIngestResult(source_file=source_file, domain=domain)
        if not text.strip():
            return result

        seen_entity_ids: set[str] = set()
        seen_relation_keys: set[tuple[str, str, str]] = set()
        schema_hint = SCHEMA_HINTS.get(domain, "")

        for chunk in self._chunk(text, _CHUNK_SIZE):
            payload = self.bridge.extract(chunk, schema_hint=schema_hint, domain=domain)
            if payload.get("error"):
                logger.warning(
                    "Extraction error on %s: %s", source_file, payload.get("error")
                )

            for raw_node in payload.get("nodes") or []:
                entity = self._coerce_entity(raw_node, source_file)
                if entity is None or entity.id in seen_entity_ids:
                    continue
                if scope_id is not None:
                    entity.properties["scope_id"] = scope_id
                entity.properties.setdefault("source_channel", source_channel)
                seen_entity_ids.add(entity.id)
                result.entities.append(entity)

            for raw_edge in payload.get("edges") or []:
                rel = self._coerce_relation(raw_edge)
                if rel is None:
                    continue
                key = (rel.source, rel.target, rel.relation)
                if key in seen_relation_keys:
                    continue
                seen_relation_keys.add(key)
                result.relations.append(rel)

        return result

    def extract_file(
        self,
        path: Path,
        domain: str = "daily",
        scope_id: Optional[str] = None,
        source_channel: str = "cli",
    ) -> ParsedIngestResult:
        """Read ``path`` and extract entities + relations from its contents."""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.error("Could not read %s: %s", path, exc)
            return ParsedIngestResult(source_file=str(path), domain=domain)

        return self.extract_text(
            text,
            source_file=str(path),
            domain=domain,
            scope_id=scope_id,
            source_channel=source_channel,
        )

    @staticmethod
    def _chunk(text: str, size: int) -> list[str]:
        if len(text) <= size:
            return [text]
        chunks: list[str] = []
        remaining = text
        while len(remaining) > size:
            window = remaining[:size]
            split = window.rfind("\n\n")
            if split < int(size * 0.5):
                split = window.rfind("\n")
            if split <= 0:
                split = size
            chunks.append(remaining[:split])
            remaining = remaining[split:]
        if remaining.strip():
            chunks.append(remaining)
        return chunks

    @staticmethod
    def _coerce_entity(raw: Any, source_file: str) -> Optional[IngestEntity]:
        if not isinstance(raw, dict):
            return None
        eid = str(raw.get("id") or "").strip()
        if not eid:
            return None
        label = str(raw.get("label") or eid)
        etype = str(raw.get("type") or "note")
        confidence = str(raw.get("confidence") or "EXTRACTED")
        try:
            score = float(raw.get("confidence_score", 1.0))
        except (TypeError, ValueError):
            score = 1.0
        props_in = raw.get("properties")
        properties = dict(props_in) if isinstance(props_in, dict) else {}
        return IngestEntity(
            id=eid,
            label=label,
            type=etype,
            source_file=str(raw.get("source_file") or source_file),
            confidence=confidence,
            confidence_score=score,
            properties=properties,
        )

    @staticmethod
    def _coerce_relation(raw: Any) -> Optional[IngestRelation]:
        if not isinstance(raw, dict):
            return None
        source = str(raw.get("source") or "").strip()
        target = str(raw.get("target") or "").strip()
        relation = str(raw.get("relation") or "").strip()
        if not (source and target and relation):
            return None
        confidence = str(raw.get("confidence") or "EXTRACTED")
        try:
            score = float(raw.get("confidence_score", 1.0))
        except (TypeError, ValueError):
            score = 1.0
        return IngestRelation(
            source=source,
            target=target,
            relation=relation,
            confidence=confidence,
            confidence_score=score,
        )


def is_code_file(path: Path) -> bool:
    """Return True if ``path`` should be treated as source code."""
    return path.suffix.lower() in _CODE_EXTS


def is_supported_file(path: Path) -> bool:
    """Return True if ``path`` is a file the ingester knows how to read."""
    return path.suffix.lower() in (_CODE_EXTS | _TEXT_EXTS)
