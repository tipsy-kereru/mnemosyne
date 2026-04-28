"""
Deterministic Syntax Parsing - Zero LLM Extraction
Uses Tree-sitter for code AST parsing, SpaCy for natural language
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, TYPE_CHECKING
from dataclasses import dataclass

if TYPE_CHECKING:
    from mnemosyne.extraction.deterministic.types import ParseResult

logger = logging.getLogger(__name__)


@dataclass
class CodeEntity:
    """Represents a code entity extracted via AST parsing"""
    type: str  # function, class, module
    name: str
    language: str
    file_path: str
    line_start: int
    line_end: int
    properties: Dict[str, Any]
    scope_id: Optional[str] = None
    source_channel: Optional[str] = None


class TreeSitterExtractor:
    """Extract code entities using Tree-sitter AST parsing"""

    SUPPORTED_LANGUAGES = {
        '.py': 'python',
        '.js': 'javascript',
        '.ts': 'typescript',
        '.tsx': 'tsx',
        '.jsx': 'javascript',
        '.go': 'go',
        '.rs': 'rust',
        '.java': 'java',
        '.cpp': 'cpp',
        '.c': 'c',
        '.rb': 'ruby',
    }

    def __init__(self):
        self.entities: List[CodeEntity] = []
        self._unavailable_languages: Set[str] = set()
        self._grammars: Dict[str, Any] = self._load_grammars()
        self._cache: Dict[str, ParseResult] = {}

    def clear_cache(self) -> None:
        """Remove all cached ParseResult entries."""
        self._cache.clear()

    def _load_grammars(self) -> Dict[str, Any]:
        """Attempt to load tree-sitter grammars for all supported languages.

        Returns a dict mapping language name to tree_sitter.Language for
        languages whose grammar packages are installed. Languages that fail
        to load are recorded in ``_unavailable_languages``.
        """
        grammars: Dict[str, Any] = {}
        language_packages = {
            "python": ("tree_sitter_python", "language"),
            "javascript": ("tree_sitter_javascript", "language"),
            "typescript": ("tree_sitter_typescript", "language_typescript"),
            "tsx": ("tree_sitter_typescript", "language_tsx"),
            "go": ("tree_sitter_go", "language"),
            "rust": ("tree_sitter_rust", "language"),
        }
        for lang_name, (module_name, attr_name) in language_packages.items():
            try:
                module = __import__(module_name)
                from tree_sitter import Language

                grammars[lang_name] = Language(getattr(module, attr_name)())
            except (ImportError, Exception):
                self._unavailable_languages.add(lang_name)
                logger.warning("Grammar not available for '%s', using regex fallback", lang_name)
        return grammars

    def extract_file(
        self,
        file_path: Path,
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> List[CodeEntity]:
        """Extract entities from a single source file.

        Returns a list of CodeEntity for backward compatibility. Internally
        delegates to :meth:`extract_file_full`.
        """
        result = self.extract_file_full(file_path, scope_id, source_channel)
        self.entities.extend(result.entities)
        logger.info("Extracted %d entities from %s", len(result.entities), file_path)
        return result.entities

    def extract_file_full(
        self,
        file_path: Path,
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> "ParseResult":
        """Extract entities, imports, and calls from a single source file.

        Returns a :class:`ParseResult` containing all extracted data and
        metadata (file path, language, content hash, extraction method).

        When a tree-sitter grammar is available for the detected language,
        AST-based extraction is used. Otherwise, regex-based fallback
        extraction is applied.
        """
        from mnemosyne.extraction.deterministic.types import ParseResult

        suffix = file_path.suffix.lower()
        language = self.SUPPORTED_LANGUAGES.get(suffix)

        if not language:
            logger.warning("Unsupported language for file %s (suffix: %s)", file_path, suffix)
            return ParseResult()

        content_bytes = file_path.read_bytes()
        content_hash = hashlib.sha256(
            f"{file_path}|".encode() + content_bytes,
        ).hexdigest()

        # Return cached result if content has not changed
        if content_hash in self._cache:
            logger.debug("Cache hit for %s (hash=%s)", file_path, content_hash[:12])
            return self._cache[content_hash]

        logger.debug("Cache miss for %s, extracting with language=%s", file_path, language)

        # Try tree-sitter extraction when grammar is available
        if language in self._grammars:
            result = self._extract_with_tree_sitter(
                language, content_bytes, str(file_path),
                scope_id, source_channel,
            )
            result.file_path = str(file_path)
            result.language = language
            result.content_hash = content_hash
            result.extraction_method = "tree-sitter"
            self._cache[content_hash] = result
            return result

        # Regex fallback for languages without loaded grammars
        content = content_bytes.decode("utf-8", errors="ignore")
        entities = self._fallback_extract(
            language, content, file_path, scope_id, source_channel,
        )
        for entity in entities:
            entity.properties["extraction_method"] = "regex"

        result = ParseResult(
            entities=entities,
            file_path=str(file_path),
            language=language,
            content_hash=content_hash,
            extraction_method="regex",
        )
        self._cache[content_hash] = result
        return result

    def _extract_with_tree_sitter(
        self,
        language: str,
        content_bytes: bytes,
        file_path: str,
        scope_id: Optional[str],
        source_channel: Optional[str],
    ) -> "ParseResult":
        """Dispatch to the appropriate language extractor for AST parsing."""
        from mnemosyne.extraction.deterministic.types import ParseResult
        from tree_sitter import Parser

        grammar = self._grammars[language]
        parser = Parser(grammar)
        tree = parser.parse(content_bytes)

        extractor = self._get_language_extractor(language)
        if extractor is not None:
            entities = extractor.extract_entities(
                tree, content_bytes, file_path, scope_id, source_channel,
            )
            imports = extractor.extract_imports(
                tree, content_bytes, file_path, scope_id, source_channel,
            )
            calls = extractor.extract_calls(
                tree, content_bytes, file_path, scope_id, source_channel,
            )
            return ParseResult(
                entities=entities,
                imports=imports,
                calls=calls,
            )

        # If no dedicated extractor, return empty result
        return ParseResult()

    def _get_language_extractor(self, language: str) -> Any:
        """Return the language extractor for the given language, or None."""
        if language == "python":
            from mnemosyne.extraction.deterministic.languages.python_extractor import (
                PythonExtractor,
            )
            if not hasattr(self, "_python_extractor"):
                self._python_extractor = PythonExtractor()
            return self._python_extractor
        elif language in ("javascript", "typescript", "tsx"):
            from mnemosyne.extraction.deterministic.languages.javascript_extractor import (
                JavaScriptExtractor,
            )
            if not hasattr(self, "_js_extractor"):
                self._js_extractor = JavaScriptExtractor()
            if self._js_extractor.grammar is not None:
                return self._js_extractor
            return None
        elif language == "go":
            from mnemosyne.extraction.deterministic.languages.go_extractor import (
                GoExtractor,
            )
            if not hasattr(self, "_go_extractor"):
                self._go_extractor = GoExtractor()
            if self._go_extractor.grammar is not None:
                return self._go_extractor
            return None
        elif language == "rust":
            from mnemosyne.extraction.deterministic.languages.rust_extractor import (
                RustExtractor,
            )
            if not hasattr(self, "_rust_extractor"):
                self._rust_extractor = RustExtractor()
            if self._rust_extractor.grammar is not None:
                return self._rust_extractor
            return None
        return None

    def _fallback_extract(
        self,
        language: str,
        content: str,
        file_path: Path,
        scope_id: Optional[str],
        source_channel: Optional[str],
    ) -> List[CodeEntity]:
        """Regex-based fallback extraction for languages without AST grammars."""
        if language == "python":
            return self._fallback_extract_python(content, file_path, scope_id, source_channel)
        elif language in ("javascript", "typescript"):
            return self._fallback_extract_js_ts(content, file_path, language, scope_id, source_channel)
        elif language == "go":
            return self._fallback_extract_go(content, file_path, scope_id, source_channel)
        elif language == "rust":
            return self._fallback_extract_rust(content, file_path, scope_id, source_channel)
        return []

    def _fallback_extract_python(
        self,
        content: str,
        file_path: Path,
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> List[CodeEntity]:
        entities = []

        # Extract functions
        func_pattern = r'(?:^(?:async\s+)?def\s+(\w+)\s*\((.*?)\)(?:\s*->\s*(.+?))?:)'
        for match in re.finditer(func_pattern, content, re.MULTILINE):
            name, params, ret_type = match.groups()
            line = content[:match.start()].count('\n') + 1
            entities.append(CodeEntity(
                type='function',
                name=name,
                language='python',
                file_path=str(file_path),
                line_start=line,
                line_end=line + content[match.start():match.end()].count('\n'),
                properties={
                    'parameters': params,
                    'return_type': ret_type or 'None',
                    'is_async': 'async' in content[max(0, match.start()-10):match.start()]
                },
                scope_id=scope_id,
                source_channel=source_channel,
            ))

        # Extract classes
        class_pattern = r'^class\s+(\w+)(?:\((.*?)\))?:'
        for match in re.finditer(class_pattern, content, re.MULTILINE):
            name, bases = match.groups()
            line = content[:match.start()].count('\n') + 1
            entities.append(CodeEntity(
                type='class',
                name=name,
                language='python',
                file_path=str(file_path),
                line_start=line,
                line_end=line,
                properties={'bases': bases.split(',') if bases else []},
                scope_id=scope_id,
                source_channel=source_channel,
            ))

        return entities

    def _fallback_extract_js_ts(
        self,
        content: str,
        file_path: Path,
        language: str,
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> List[CodeEntity]:
        entities = []

        # Extract functions (function declarations and arrow functions assigned to const)
        func_pattern = r'(?:^(?:async\s+)?function\s+(\w+)\s*\((.*?)\)|^(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:\((.*?)\)|(\w+))\s*=>)'
        for match in re.finditer(func_pattern, content, re.MULTILINE):
            if match.group(1):  # function declaration
                name, params = match.group(1), match.group(2)
            else:  # arrow function
                name = match.group(3)
                params = match.group(4) or match.group(5)
            line = content[:match.start()].count('\n') + 1
            entities.append(CodeEntity(
                type='function',
                name=name,
                language=language,
                file_path=str(file_path),
                line_start=line,
                line_end=line,
                properties={'parameters': params or ''},
                scope_id=scope_id,
                source_channel=source_channel,
            ))

        # Extract classes
        class_pattern = r'^class\s+(\w+)(?:\s+extends\s+(\w+))?'
        for match in re.finditer(class_pattern, content, re.MULTILINE):
            name, extends = match.groups()
            line = content[:match.start()].count('\n') + 1
            entities.append(CodeEntity(
                type='class',
                name=name,
                language=language,
                file_path=str(file_path),
                line_start=line,
                line_end=line,
                properties={'extends': extends},
                scope_id=scope_id,
                source_channel=source_channel,
            ))

        return entities

    def _fallback_extract_go(
        self,
        content: str,
        file_path: Path,
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> List[CodeEntity]:
        entities = []

        # Extract functions
        func_pattern = r'^func\s+(?:\((\w+)\s+\*?[\w]+\)\s+)?(\w+)\s*\((.*?)\)'
        for match in re.finditer(func_pattern, content, re.MULTILINE):
            receiver, name, params = match.groups()
            line = content[:match.start()].count('\n') + 1
            entities.append(CodeEntity(
                type='function',
                name=name,
                language='go',
                file_path=str(file_path),
                line_start=line,
                line_end=line,
                properties={
                    'receiver': receiver,
                    'parameters': params
                },
                scope_id=scope_id,
                source_channel=source_channel,
            ))

        # Extract structs
        struct_pattern = r'^type\s+(\w+)\s+struct\s*\{'
        for match in re.finditer(struct_pattern, content, re.MULTILINE):
            name = match.group(1)
            line = content[:match.start()].count('\n') + 1
            entities.append(CodeEntity(
                type='class',  # Go structs are like classes
                name=name,
                language='go',
                file_path=str(file_path),
                line_start=line,
                line_end=line,
                properties={},
                scope_id=scope_id,
                source_channel=source_channel,
            ))

        return entities

    def _fallback_extract_rust(
        self,
        content: str,
        file_path: Path,
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> List[CodeEntity]:
        entities = []

        # Extract functions
        func_pattern = r'^(?:pub\s+)?(?:async\s+)?fn\s+(\w+)\s*(?:<[^>]+>\s*)?\((.*?)\)'
        for match in re.finditer(func_pattern, content, re.MULTILINE):
            name, params = match.groups()
            line = content[:match.start()].count('\n') + 1
            entities.append(CodeEntity(
                type='function',
                name=name,
                language='rust',
                file_path=str(file_path),
                line_start=line,
                line_end=line,
                properties={'parameters': params},
                scope_id=scope_id,
                source_channel=source_channel,
            ))

        # Extract structs and enums
        type_pattern = r'^struct\s+(\w+)'
        for match in re.finditer(type_pattern, content, re.MULTILINE):
            name = match.group(1)
            line = content[:match.start()].count('\n') + 1
            entities.append(CodeEntity(
                type='class',
                name=name,
                language='rust',
                file_path=str(file_path),
                line_start=line,
                line_end=line,
                properties={'kind': 'struct'},
                scope_id=scope_id,
                source_channel=source_channel,
            ))

        enum_pattern = r'^enum\s+(\w+)'
        for match in re.finditer(enum_pattern, content, re.MULTILINE):
            name = match.group(1)
            line = content[:match.start()].count('\n') + 1
            entities.append(CodeEntity(
                type='class',
                name=name,
                language='rust',
                file_path=str(file_path),
                line_start=line,
                line_end=line,
                properties={'kind': 'enum'},
                scope_id=scope_id,
                source_channel=source_channel,
            ))

        return entities

    def extract_directory(
        self,
        dir_path: Path,
        extensions: Optional[List[str]] = None,
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> List[CodeEntity]:
        """Recursively extract entities from all matching files"""
        logger.info("Starting directory extraction from %s", dir_path)
        all_entities = []

        for file_path in dir_path.rglob('*'):
            if file_path.is_file():
                if extensions is None or file_path.suffix in extensions:
                    try:
                        entities = self.extract_file(
                            file_path,
                            scope_id=scope_id,
                            source_channel=source_channel,
                        )
                        all_entities.extend(entities)
                    except Exception as e:
                        logger.error("Error extracting %s: %s", file_path, e)

        logger.info("Directory extraction complete: %d entities from %s", len(all_entities), dir_path)
        return all_entities

    def to_wiki_format(
        self,
        entities: List[CodeEntity],
        imports: Optional[List] = None,
        calls: Optional[List] = None,
    ) -> str:
        """Convert extracted entities to wiki markdown format.

        When *imports* or *calls* are provided (as lists of ImportEntity or
        CallRelation), additional Import Graph and Call Graph sections are
        appended.  Passing neither (or empty lists) preserves the original
        entities-only output for backward compatibility.
        """
        lines = ["# Code Entities\n"]

        by_type: Dict[str, List[CodeEntity]] = {}
        for e in entities:
            by_type.setdefault(e.type, []).append(e)

        for entity_type, type_entities in sorted(by_type.items()):
            lines.append(f"\n## {entity_type.title()}s\n")
            for entity in sorted(type_entities, key=lambda x: x.name):
                lines.append(f"### [[{entity.language}:{entity.name}]]\n")
                lines.append(f"- **File**: `{entity.file_path}:{entity.line_start}`")
                lines.append(f"- **Language**: {entity.language}")
                if entity.scope_id is not None:
                    lines.append(f"- **scope_id**: {entity.scope_id}")
                if entity.source_channel is not None:
                    lines.append(f"- **source_channel**: {entity.source_channel}")
                for key, value in entity.properties.items():
                    if value:
                        lines.append(f"- **{key}**: {value}")
                lines.append("")

        # Import Graph section
        if imports:
            lines.append("\n## Import Graph\n")
            for imp in imports:
                local_tag = " (local)" if imp.is_local else ""
                names = ", ".join(imp.imported_names) if imp.imported_names else "*"
                lines.append(
                    f"- [[import:{imp.module_path}]] -> {names}{local_tag}"
                    f" (`{imp.source_file}:{imp.line_number}`)"
                )
            lines.append("")

        # Call Graph section
        if calls:
            lines.append("\n## Call Graph\n")
            for call in calls:
                lines.append(
                    f"- [[{call.caller_name}]] -> [[{call.callee_name}]]"
                    f" ({call.call_type}, line {call.callee_line})"
                )
            lines.append("")

        return '\n'.join(lines)


class SpaCyExtractor:
    """Extract entities from natural language using SpaCy"""

    def __init__(self, model: str = 'en_core_web_sm'):
        try:
            import spacy  # type: ignore[import-not-found]
            self.nlp = spacy.load(model)
        except OSError:
            logger.warning("SpaCy model '%s' not found. Run: python -m spacy download %s", model, model)
            self.nlp = None

    def extract_entities(self, text: str, custom_types: Optional[Dict[str, str]] = None) -> List[Dict]:
        """Extract named entities from text"""
        if not self.nlp:
            return []

        doc = self.nlp(text)
        entities = []

        for ent in doc.ents:
            entities.append({
                'text': ent.text,
                'type': ent.label_,
                'start': ent.start_char,
                'end': ent.end_char
            })

        # Apply custom types if provided (for domain-specific extraction)
        if custom_types:
            for pattern, label in custom_types.items():
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    entities.append({
                        'text': match.group(),
                        'type': label,
                        'start': match.start(),
                        'end': match.end()
                    })

        return entities

    def extract_relations(self, text: str) -> List[Dict]:
        """Extract subject-verb-object relations"""
        if not self.nlp:
            return []

        doc = self.nlp(text)
        relations = []

        for token in doc:
            # Look for subject-verb-object patterns
            if token.dep_ == 'ROOT':
                subject = None
                obj = None
                for child in token.children:
                    if child.dep_ in ('nsubj', 'nsubjpass'):
                        subject = child.text
                    elif child.dep_ in ('dobj', 'pobj', 'attr'):
                        obj = child.text

                if subject and obj:
                    relations.append({
                        'subject': subject,
                        'verb': token.lemma_,
                        'object': obj
                    })

        return relations


def main():
    """Deprecated: use mnemosyne.extraction.cli:main instead."""
    from mnemosyne.extraction.cli import main as cli_main
    cli_main()


if __name__ == '__main__':
    main()
