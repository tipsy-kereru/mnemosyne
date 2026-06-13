"""
SPEC-HEADROOM-001 wiki budget pruning (REQ-005).

Ranks markdown documents under ``mnemosyne/wiki/**/*.md`` by an
importance x recency x access-frequency score, then prunes the lowest-scoring
documents and merges near-duplicates until the token budget is met.

Ranking model (plan-phase decision R4):
- importance: derived from the document's front-matter ``importance`` key when
  present, else a per-type default (functions/classes weighted higher), else
  ``1.0``.
- recency: exponential decay from the document's ``mtime``. ``RECENCY_HALFLIFE_DAYS``
  controls how fast old documents fade; default ~180 days.
- access_frequency: ``mnemosyne`` does not track access frequency today. We
  default to a constant (``1.0``). When an access-log source is wired in,
  swap ``_access_frequency`` to read from it.

Token counting (REQ-005, AC12):
- ``count_tokens`` tries the optional ``mnemosyne-core`` Rust token counter at
  import time. If the symbol is absent (e.g. cargo not available at install
  time), it falls back to the ``len(text) // 4`` heuristic without error.

The module is importable and callable independently of any CLI; ``prune_wiki_budget``
returns a structured ``BudgetResult``. A thin CLI / ``--stats`` wrapper can be
layered on top by callers that need it.
"""

import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

# --- Token counting (AC12) ---------------------------------------------------

_RUST_TOKEN_COUNTER: Optional[Callable[[str], int]] = None
try:  # pragma: no cover - import-time guard, environment dependent
    import mnemosyne_core as _mc  # type: ignore

    _candidate = getattr(_mc, "count_tokens", None) or getattr(_mc, "token_count", None)
    if callable(_candidate):
        _RUST_TOKEN_COUNTER = _candidate
except Exception:
    # Optional dependency; absence is the expected path in environments
    # where the Rust crate was not built.
    _RUST_TOKEN_COUNTER = None


def count_tokens(text: str) -> int:
    """Return a token count for ``text``.

    Uses the ``mnemosyne-core`` Rust counter when available; otherwise falls
    back to the ``len(text) // 4`` heuristic. Never raises.
    """
    if _RUST_TOKEN_COUNTER is not None:
        try:
            return int(_RUST_TOKEN_COUNTER(text))
        except Exception:
            # A Rust-side failure must not break pruning.
            pass
    return len(text) // 4


# --- Ranking -----------------------------------------------------------------

RECENCY_HALFLIFE_DAYS = 180.0
DEFAULT_ACCESS_FREQUENCY = 1.0

# Higher-importance entity types (per CLAUDE.md coding/daily/legal schemas).
_TYPE_IMPORTANCE: Dict[str, float] = {
    "function": 1.2,
    "class": 1.2,
    "api": 1.3,
    "bug": 1.1,
    "task": 1.0,
    "feature": 1.1,
    "note": 0.8,
    "default": 1.0,
}

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


@dataclass
class DocScore:
    """A ranked document and its computed score components."""

    path: str
    score: float
    importance: float
    recency: float
    access_freq: float
    tokens: int


@dataclass
class MergedDoc:
    """A document absorbed into a kept representative."""

    path: str
    into: str  # path of the representative that absorbed it


@dataclass
class BudgetResult:
    """Structured outcome of ``prune_wiki_budget``."""

    kept: List[DocScore] = field(default_factory=list)
    pruned: List[DocScore] = field(default_factory=list)
    merged: List[MergedDoc] = field(default_factory=list)
    total_tokens: int = 0


def _recency_score(mtime: float, now: Optional[float] = None) -> float:
    """Exponential decay from mtime; recent docs -> ~1.0, old docs -> ~0.0.

    ``RECENCY_HALFLIFE_DAYS`` is the half-life: a doc older than that scores 0.5.
    """
    now = now if now is not None else time.time()
    age_seconds = max(0.0, now - mtime)
    age_days = age_seconds / 86400.0
    return math.pow(0.5, age_days / RECENCY_HALFLIFE_DAYS)


def _importance_from_doc(path: Path, text: str) -> float:
    """Derive an importance weight from front-matter or filename/type hints."""
    fm = _FRONTMATTER_RE.match(text)
    if fm:
        importance_match = re.search(
            r"^importance:\s*([0-9.]+)\s*$", fm.group(1), re.MULTILINE
        )
        if importance_match:
            try:
                return float(importance_match.group(1))
            except ValueError:
                pass
        type_match = re.search(r"^type:\s*(\w+)\s*$", fm.group(1), re.MULTILINE)
        if type_match:
            return _TYPE_IMPORTANCE.get(type_match.group(1).lower(), _TYPE_IMPORTANCE["default"])
    return _TYPE_IMPORTANCE["default"]


def _access_frequency(_path: Path) -> float:
    """Access frequency signal.

    TODO(SPEC-HEADROOM-001 R4): mnemosyne does not track access frequency today.
    When an access-log source is wired in, read it here. For now a constant
    preserves the ranking formula's shape without inventing data.
    """
    return DEFAULT_ACCESS_FREQUENCY


def _normalize_for_dedup(text: str) -> str:
    """Normalize text for near-duplicate detection (strip whitespace/case)."""
    return re.sub(r"\s+", " ", text).strip().lower()


def prune_wiki_budget(
    wiki_root: Path,
    token_budget: int,
    now: Optional[float] = None,
) -> BudgetResult:
    """Rank, merge near-duplicates, and prune markdown docs to fit ``token_budget``.

    Args:
        wiki_root: Directory containing ``**/*.md`` documents.
        token_budget: Maximum total tokens to keep across surviving documents.
        now: Override for ``time.time()`` (used in tests for deterministic recency).

    Returns:
        ``BudgetResult`` partitioning every input doc into exactly one of
        ``kept`` / ``pruned`` / ``merged``.
    """
    wiki_root = Path(wiki_root)
    if not wiki_root.exists():
        return BudgetResult()

    docs: List[DocScore] = []
    for md_path in sorted(wiki_root.rglob("*.md")):
        try:
            text = md_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        importance = _importance_from_doc(md_path, text)
        recency = _recency_score(md_path.stat().st_mtime, now=now)
        access_freq = _access_frequency(md_path)
        score = importance * recency * access_freq
        docs.append(
            DocScore(
                path=str(md_path),
                score=score,
                importance=importance,
                recency=recency,
                access_freq=access_freq,
                tokens=count_tokens(text),
            )
        )

    if not docs:
        return BudgetResult()

    # --- Merge near-duplicates (keep highest-scoring representative) ---
    by_norm: Dict[str, List[int]] = {}
    norm_cache: Dict[int, str] = {}
    for idx, d in enumerate(docs):
        try:
            text = Path(d.path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        norm = _normalize_for_dedup(text)
        norm_cache[idx] = norm
        by_norm.setdefault(norm, []).append(idx)

    merged: List[MergedDoc] = []
    surviving_indices = list(range(len(docs)))
    for norm, indices in by_norm.items():
        if len(indices) <= 1:
            continue
        # Representative = highest score (ties broken by lower path for determinism)
        representative = max(
            indices, key=lambda i: (docs[i].score, -ord(Path(docs[i].path).name[0]) if Path(docs[i].path).name else 0)
        )
        for idx in indices:
            if idx == representative:
                continue
            merged.append(MergedDoc(path=docs[idx].path, into=docs[representative].path))
            if idx in surviving_indices:
                surviving_indices.remove(idx)

    surviving = sorted(
        (docs[i] for i in surviving_indices), key=lambda d: d.score, reverse=True
    )

    # --- Greedily keep top-scored docs until budget is exhausted ---
    kept: List[DocScore] = []
    pruned: List[DocScore] = []
    running = 0
    for doc in surviving:
        if running + doc.tokens <= token_budget:
            kept.append(doc)
            running += doc.tokens
        else:
            pruned.append(doc)

    total_tokens = sum(d.tokens for d in kept)
    return BudgetResult(
        kept=kept, pruned=pruned, merged=merged, total_tokens=total_tokens
    )
