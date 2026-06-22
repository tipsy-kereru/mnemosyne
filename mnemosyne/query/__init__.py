"""SPEC-NLQUERY-001: natural-language query + multi-turn chat layer.

Public surface:
- :class:`QueryPlan` — router output (intent + targets + scope).
- :class:`RetrievalResult` — unified retrieval payload from the executor.
- :class:`NLQueryRouter` — NL -> QueryPlan (GLiNER2 + heuristics).
- :class:`QueryExecutor` — QueryPlan -> RetrievalResult.
- :class:`AnswerSynthesizer` — RetrievalResult -> grounded answer (REQ-NL-008).
- :class:`ChatStore` — append-only chat session persistence (REQ-NL-006).
"""

from mnemosyne.query.types import Citation, QueryPlan, RetrievalResult
from mnemosyne.query.router import NLQueryRouter
from mnemosyne.query.executor import QueryExecutor
from mnemosyne.query.synthesizer import AnswerSynthesizer
from mnemosyne.query.chat_store import ChatStore

__all__ = [
    "AnswerSynthesizer",
    "Citation",
    "ChatStore",
    "NLQueryRouter",
    "QueryExecutor",
    "QueryPlan",
    "RetrievalResult",
]
