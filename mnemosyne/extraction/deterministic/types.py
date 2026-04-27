"""
Data structures for deterministic tree-sitter extraction (SPEC-TS-001).

Provides ParseResult, ImportEntity, and CallRelation dataclasses used by
AST-based extraction to carry entity, import, and call-graph data.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from mnemosyne.extraction.deterministic.code_parser import CodeEntity


@dataclass
class ImportEntity:
    """Represents a single import statement extracted from source."""

    source_file: str
    module_path: str
    imported_names: List[str]
    is_local: bool
    line_number: int
    scope_id: Optional[str] = None
    source_channel: Optional[str] = None


@dataclass
class CallRelation:
    """Represents a call-graph edge between two functions/methods."""

    caller_name: str
    caller_file: str
    callee_name: str
    callee_line: int
    call_type: str
    scope_id: Optional[str] = None
    source_channel: Optional[str] = None


@dataclass
class ParseResult:
    """Aggregated result of parsing a single source file.

    Holds all extracted entities, import declarations, and call-graph edges
    along with metadata (file path, language, content hash, extraction method).
    """

    entities: List[CodeEntity] = field(default_factory=list)
    imports: List[ImportEntity] = field(default_factory=list)
    calls: List[CallRelation] = field(default_factory=list)
    file_path: str = ""
    language: str = ""
    content_hash: str = ""
    extraction_method: str = ""
