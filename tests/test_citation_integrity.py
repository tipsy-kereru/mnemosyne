"""REQ-NL-008 (non-negotiable): citation integrity guard.

The synthesizer MUST drop every LLM-output citation that does not trace to a
RetrievalResult entry. This test feeds a malicious LLM stub emitting fabricated
ids and asserts zero hallucinated refs reach the response.
"""

from __future__ import annotations

from mnemosyne.query.synthesizer import AnswerSynthesizer
from mnemosyne.query.types import Citation, RetrievalResult


class _FabricatingLLM:
    """LLM stub that emits a real citation AND a fabricated one."""

    def synthesize(self, question: str, context: str = "") -> str:
        return (
            "Answer referencing [entity:real_func] and "
            "[entity:FAKE-9999] which does not exist."
        )


def _result_with_real_entity() -> RetrievalResult:
    result = RetrievalResult()
    result.entities.append({"id": "real_func", "type": "function", "name": "real"})
    result.citations.append(Citation(type="entity", id="real_func"))
    return result


def test_fabricated_citation_dropped() -> None:
    synth = AnswerSynthesizer(llm_bridge=_FabricatingLLM())
    out = synth.synthesize("q", _result_with_real_entity())
    ids = {c["id"] for c in out["citations"]}
    assert "real_func" in ids
    assert "FAKE-9999" not in ids, "hallucinated citation reached the response"
    assert out["degraded"] is False


def test_all_fabricated_collapses_to_retrieval_citations() -> None:
    """When the LLM cites only fabricated ids, fall back to retrieval citations."""

    class _AllFake:
        def synthesize(self, question: str, context: str = "") -> str:
            return "see [entity:FAKE-A] and [relation:FAKE-B]"

    synth = AnswerSynthesizer(llm_bridge=_AllFake())
    result = _result_with_real_entity()
    out = synth.synthesize("q", result)
    # Prose is still returned, but citations are the retrieval allowlist only.
    assert out["degraded"] is False
    assert {c["id"] for c in out["citations"]} == {"real_func"}


def test_empty_allowlist_drops_all_llm_citations() -> None:
    class _Cites:
        def synthesize(self, question: str, context: str = "") -> str:
            return "see [entity:ghost]"

    synth = AnswerSynthesizer(llm_bridge=_Cites())
    out = synth.synthesize("q", RetrievalResult())
    assert out["citations"] == []


def test_degraded_mode_emits_no_prose_but_keeps_citations() -> None:
    class _Broken:
        def synthesize(self, question: str, context: str = "") -> str:
            raise RuntimeError("provider down")

    synth = AnswerSynthesizer(llm_bridge=_Broken())
    out = synth.synthesize("q", _result_with_real_entity())
    assert out["degraded"] is True
    assert "_No direct matches" not in out["answer"]  # entity present
    assert any(c["id"] == "real_func" for c in out["citations"])
