"""
Deterministic Syntax Parsing - Zero LLM Extraction
Uses Tree-sitter for code AST parsing, SpaCy for natural language
"""

import re
import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict


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
        '.ts': 'typescript',
    }
    
    def __init__(self):
        self.entities: List[CodeEntity] = []
    
    def extract_file(
        self,
        file_path: Path,
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> List[CodeEntity]:
        """Extract entities from a single source file"""
        suffix = file_path.suffix.lower()
        language = self.SUPPORTED_LANGUAGES.get(suffix)

        if not language:
            return []

        # For now, use regex-based extraction as tree-sitter fallback
        # In production, use tree-sitter-python, tree-sitter-javascript, etc.
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        entities = []

        if language == 'python':
            entities = self._extract_python(content, file_path, scope_id, source_channel)
        elif language in ('javascript', 'typescript'):
            entities = self._extract_js_ts(content, file_path, language, scope_id, source_channel)
        elif language == 'go':
            entities = self._extract_go(content, file_path, scope_id, source_channel)
        elif language == 'rust':
            entities = self._extract_rust(content, file_path, scope_id, source_channel)

        self.entities.extend(entities)
        return entities
    
    def _extract_python(
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
    
    def _extract_js_ts(
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
    
    def _extract_go(
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
    
    def _extract_rust(
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
                        print(f"Error extracting {file_path}: {e}")

        return all_entities
    
    def to_wiki_format(self, entities: List[CodeEntity]) -> str:
        """Convert extracted entities to wiki markdown format"""
        lines = ["# Code Entities\n"]

        by_type = {}
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

        return '\n'.join(lines)


class SpaCyExtractor:
    """Extract entities from natural language using SpaCy"""
    
    def __init__(self, model: str = 'en_core_web_sm'):
        try:
            import spacy
            self.nlp = spacy.load(model)
        except OSError:
            print(f"SpaCy model '{model}' not found. Run: python -m spacy download {model}")
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
    """Example usage"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Extract code entities via deterministic parsing')
    parser.add_argument('path', help='File or directory to extract')
    parser.add_argument('--format', choices=['json', 'wiki'], default='json')
    
    args = parser.parse_args()
    
    path = Path(args.path)
    extractor = TreeSitterExtractor()
    
    if path.is_file():
        entities = extractor.extract_file(path)
    else:
        entities = extractor.extract_directory(path)
    
    if args.format == 'json':
        print(json.dumps([asdict(e) for e in entities], indent=2))
    else:
        print(extractor.to_wiki_format(entities))


if __name__ == '__main__':
    main()