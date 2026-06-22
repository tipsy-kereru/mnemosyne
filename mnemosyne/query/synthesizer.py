"""SPEC-NLQUERY-001 REQ-NL-003 + REQ-NL-008: answer synthesis with citation guard.

``AnswerSynthesizer.synthesize(question, result)`` returns grounded prose when
``LLMBridge.synthesize()`` succeeds. On LLM-unavailable/empty output it
returns structured markdown (entities + relations + excerpts) with citations
only. Every citation in the final answer is intersected with
``result.allowlist()`` so LLM-hallucinated references never reach the caller
(REQ-NL-008 — the non-negotiable safety control).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from mnemosyne.query.types import RetrievalResult

logger = logging.getLogger(__name__)


class AnswerSynthesizer:
    """REQ-NL-003/REQ-NL-008: prose-when-LLM, structured-md-when-not."""

    def __init__(self, llm_bridge: Optional[Any] = None) -> None:
        # Lazily construct LLMBridge if none supplied so callers can inject
        # a stub in tests.
        self._llm_bridge = llm_bridge

    @property
    def llm_bridge(self) -> Any:
        if self._llm_bridge is None:
            from mnemosyne.ingest.llm_bridge import LLMBridge

            self._llm_bridge = LLMBridge()
        return self._llm_bridge

    def synthesize(
        self,
        question: str,
        result: RetrievalResult,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return ``{"answer": str, "citations": List[dict], "degraded": bool}``.

        Never raises to the caller: LLM failures collapse to degraded mode.
        """
        allowlist = result.allowlist()
        all_citations = [c.to_dict() for c in result.citations]

        prose = self._try_llm(question, result, context)
        if prose:
            # REQ-NL-008: intersect any citation markers the LLM emitted with
            # the retrieval allowlist. Fabricated refs are dropped silently.
            kept = self._filter_citations_from_prose(prose, allowlist)
            if not kept and all_citations:
                # LLM produced prose but cited nothing real; keep the retrieval
                # citations verbatim and flag so callers can audit.
                kept = all_citations
            return {
                "answer": prose,
                "citations": kept,
                "degraded": False,
            }

        # Degraded mode: structured markdown, retrieval citations only.
        answer = self._structured_markdown(question, result)
        return {
            "answer": answer,
            "citations": all_citations,
            "degraded": True,
        }

    # -- LLM path ---------------------------------------------------------

    def _try_llm(
        self,
        question: str,
        result: RetrievalResult,
        context: Optional[str],
    ) -> str:
        """Call LLMBridge.synthesize(); return "" on any failure."""
        try:
            raw = self.llm_bridge.synthesize(
                question,
                context=_build_context_json(result, context),
            )
        except Exception as exc:  # pragma: no cover - provider variance
            logger.warning("LLMBridge.synthesize failed: %s", exc)
            return ""
        if not raw or not raw.strip():
            return ""
        return raw.strip()

    @staticmethod
    def _filter_citations_from_prose(
        prose: str, allowlist: set[tuple[str, str]]
    ) -> List[Dict[str, Any]]:
        """Extract ``[type:id]`` markers from *prose*, keep only allowlisted.

        The LLM is instructed to emit citations as ``[entity:func_authenticate]``
        tokens. We parse them out and drop any whose ``(type, id)`` is not in
        the retrieval allowlist (REQ-NL-008 hallucination guard).
        """
        if not allowlist:
            return []
        kept: List[Dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        pattern = re.compile(r"\[(entity|relation|excerpt):([^\]\s]+)\]")
        for m in pattern.finditer(prose):
            ctype = m.group(1)
            cid = m.group(2)
            key = (ctype, cid)
            if key in allowlist and key not in seen:
                seen.add(key)
                kept.append({"type": ctype, "id": cid})
        return kept

    # -- Degraded path ----------------------------------------------------

    @staticmethod
    def _structured_markdown(
        question: str, result: RetrievalResult
    ) -> str:
        """Build structured markdown when the LLM is unavailable/empty."""
        lines: List[str] = [f"# Results for: {question}", ""]
        if result.entities:
            lines.append("## Matched Entities")
            for e in result.entities[:10]:
                lines.append(
                    f"- **{e.get('name', e.get('id', '?'))}** "
                    f"(`{e.get('type', '?')}`) — `{e.get('id', '?')}`"
                )
            lines.append("")
        if result.relations:
            lines.append("## Relations")
            for r in result.relations[:10]:
                lines.append(
                    f"- `{r.get('source_id', '?')}` → "
                    f"**{r.get('relation_type', r.get('type', '?'))}** → "
                    f"`{r.get('target_id', '?')}`"
                )
            lines.append("")
        if result.excerpts:
            lines.append("## Excerpts")
            for ex in result.excerpts[:5]:
                path = ex.get("node_path", "?")
                summary = ex.get("summary") or (ex.get("raw_excerpt") or "")[:120]
                lines.append(f"- `{path}`: {summary}")
            lines.append("")
        if not (result.entities or result.relations or result.excerpts):
            lines.append("_No direct matches found in the graph._")
        return "\n".join(lines).strip()


def _build_context_json(
    result: RetrievalResult, context: Optional[str]
) -> str:
    """Serialize retrieval results + optional chat context for the LLM prompt.

    SPEC-NLQUERY-001 security (prompt injection): the optional chat context is
    wrapped in ``<conversation_history>`` ... ``</conversation_history>`` delimiters
    so the system prompt can instruct the model to treat it as untrusted data,
    never as instructions. Stored turns are user-authored and may contain
    injection attempts.
    """
    payload: Dict[str, Any] = {
        "entities": [
            {"id": e.get("id"), "type": e.get("type"), "name": e.get("name")}
            for e in result.entities[:20]
        ],
        "relations": [
            {
                "id": r.get("id"),
                "source_id": r.get("source_id"),
                "target_id": r.get("target_id"),
                "relation_type": r.get("relation_type", r.get("type")),
            }
            for r in result.relations[:20]
        ],
        "excerpts": [
            {"node_path": ex.get("node_path"), "summary": ex.get("summary")}
            for ex in result.excerpts[:5]
        ],
        "valid_citation_ids": [c.to_dict() for c in result.citations],
    }
    if context:
        payload["conversation_context"] = (
            f"<conversation_history>\n{context}\n</conversation_history>"
        )
    return json.dumps(payload, default=str)
