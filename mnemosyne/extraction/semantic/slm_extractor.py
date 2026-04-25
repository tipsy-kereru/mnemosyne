"""
Local SLM Semantic Extraction
Uses GLiNER2 for NER and REBEL for relation extraction
Runs on CPU or low-VRAM GPU - zero API cost
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict


@dataclass
class ExtractedEntity:
    """Entity extracted via local SLM"""
    type: str
    text: str
    confidence: float
    source: str
    start: int
    end: int
    scope_id: Optional[str] = None
    source_channel: Optional[str] = None


@dataclass
class ExtractedRelation:
    """Relation extracted via local SLM"""
    subject: str
    relation: str
    object: str
    confidence: float
    source: str
    scope_id: Optional[str] = None
    source_channel: Optional[str] = None


class GLiNER2Extractor:
    """
    Local NER using GLiNER2 model
    Supports custom entity types via natural language descriptions
    """
    
    def __init__(self, model_name: str = "urchade/gliner_base"):
        self.model = None
        self.model_name = model_name
        self._load_model()
    
    def _load_model(self):
        """Load GLiNER2 model (lazy loading)"""
        try:
            from gliner import GLiNER
            self.model = GLiNER(self.model_name)
        except ImportError:
            print("GLiNER not installed. Run: pip install gliner")
            print("Using fallback rule-based extraction")
        except Exception as e:
            print(f"Error loading GLiNER2 model: {e}")
            print("Using fallback rule-based extraction")
    
    def extract(
        self,
        text: str,
        entity_types: List[str],
        threshold: float = 0.5,
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> List[ExtractedEntity]:
        """
        Extract entities from text

        Args:
            text: Input text
            entity_types: List of entity types to extract
            threshold: Confidence threshold
            scope_id: Optional scope identifier
            source_channel: Optional source channel
        """
        if self.model:
            return self._extract_with_model(text, entity_types, threshold, scope_id, source_channel)
        else:
            return self._extract_fallback(text, entity_types, scope_id, source_channel)
    
    def _extract_with_model(
        self,
        text: str,
        entity_types: List[str],
        threshold: float,
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> List[ExtractedEntity]:
        """Use GLiNER2 model for extraction"""
        labels = entity_types if isinstance(entity_types[0], str) else [e['type'] for e in entity_types]

        entities = self.model.predict_entities(text, labels, threshold=threshold)

        result = []
        for ent in entities:
            result.append(ExtractedEntity(
                type=ent['label'],
                text=ent['text'],
                confidence=ent['score'],
                source='gliner2',
                start=ent.get('start', 0),
                end=ent.get('end', 0),
                scope_id=scope_id,
                source_channel=source_channel,
            ))

        return result
    
    def _extract_fallback(
        self,
        text: str,
        entity_types: List[str],
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> List[ExtractedEntity]:
        """Fallback rule-based extraction when model unavailable"""
        entities = []

        # Pattern-based extraction for common entities
        patterns = {
            'PERSON': r'\b[A-Z][a-z]+ [A-Z][a-z]+\b',
            'ORGANIZATION': r'\b[A-Z][a-z]+ (Inc|LLC|Corp|Ltd|Company)\b',
            'EMAIL': r'\b[\w.-]+@[\w.-]+\.\w+\b',
            'PHONE': r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',
            'DATE': r'\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b',
            'URL': r'https?://\S+',
        }

        for ent_type in entity_types:
            pattern = patterns.get(ent_type.upper())
            if pattern:
                for match in re.finditer(pattern, text):
                    entities.append(ExtractedEntity(
                        type=ent_type,
                        text=match.group(),
                        confidence=0.9,
                        source='rule-based',
                        start=match.start(),
                        end=match.end(),
                        scope_id=scope_id,
                        source_channel=source_channel,
                    ))

        return entities


class REBELExtractor:
    """
    Local relation extraction using REBEL model
    Extracts subject-relation-object triplets from unstructured text
    """
    
    def __init__(self, model_name: str = "Babelscape/rebel-large"):
        self.model = None
        self.tokenizer = None
        self.model_name = model_name
        self._load_model()
    
    def _load_model(self):
        """Load REBEL model (lazy loading)"""
        try:
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self.model = AutoModelForSeq2SeqLM.from_pretrained(self.model_name)
        except ImportError:
            print("Transformers not installed. Run: pip install transformers")
        except Exception as e:
            print(f"Error loading REBEL model: {e}")
    
    def extract(
        self,
        text: str,
        max_length: int = 128,
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> List[ExtractedRelation]:
        """
        Extract relations from text

        Args:
            text: Input text
            max_length: Max sequence length
            scope_id: Optional scope identifier
            source_channel: Optional source channel
        """
        if self.model and self.tokenizer:
            return self._extract_with_model(text, max_length, scope_id, source_channel)
        else:
            return self._extract_fallback(text, scope_id, source_channel)
    
    def _extract_with_model(
        self,
        text: str,
        max_length: int,
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> List[ExtractedRelation]:
        """Use REBEL model for extraction"""
        # Extract relation triples using REBEL methodology
        inputs = self.tokenizer(text, return_tensors="pt", max_length=max_length, truncation=True)

        gen_kwargs = {
            "max_length": max_length,
            "length_penalty": 0,
            "num_beams": 3,
            "num_return_sequences": 3
        }

        output = self.model.generate(**inputs, **gen_kwargs)
        decoded = self.tokenizer.batch_decode(output, skip_special_tokens=False)

        relations = []
        for seq in decoded:
            # Parse REBEL output format
            triples = self._parse_rebel_output(seq)
            for subj, rel, obj in triples:
                relations.append(ExtractedRelation(
                    subject=subj,
                    relation=rel,
                    object=obj,
                    confidence=0.8,
                    source='rebel',
                    scope_id=scope_id,
                    source_channel=source_channel,
                ))

        return relations
    
    def _parse_rebel_output(self, sequence: str) -> List[tuple]:
        """Parse REBEL's sequence output to extract triples"""
        triples = []
        
        # REBEL outputs <triplet> subject <relation> object <relation> object...
        pattern = r'<triplet> ([^<]+) <relation> ([^<]+) <object> ([^<]+)'
        for match in re.finditer(pattern, sequence):
            subj, rel, obj = match.groups()
            triples.append((subj.strip(), rel.strip(), obj.strip()))
        
        return triples
    
    def _extract_fallback(
        self,
        text: str,
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> List[ExtractedRelation]:
        """Fallback pattern-based relation extraction"""
        relations = []

        # Simple subject-verb-object patterns
        patterns = [
            (r'(\w+)\s+(?:is|was|are|were)\s+(?:a|an|the)\s+(\w+)', 'is_a'),
            (r'(\w+)\s+(?:works for|employed by)\s+(\w+)', 'works_for'),
            (r'(\w+)\s+(?:located in|based in)\s+(\w+)', 'located_in'),
            (r'(\w+)\s+(?:owns|owns a|has)\s+(\w+)', 'owns'),
        ]

        for pattern, rel_type in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                relations.append(ExtractedRelation(
                    subject=match.group(1),
                    relation=rel_type,
                    object=match.group(2),
                    confidence=0.7,
                    source='rule-based',
                    scope_id=scope_id,
                    source_channel=source_channel,
                ))

        return relations


class SemanticExtractor:
    """Combined semantic extraction using local SLMs"""
    
    def __init__(self, gliner_model: str = "urchade/gliner_base", rebel_model: str = "Babelscape/rebel-large"):
        self.ner = GLiNER2Extractor(gliner_model)
        self.re = REBELExtractor(rebel_model)
    
    def extract(
        self,
        text: str,
        entity_types: List[str],
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Extract entities and relations from text

        Args:
            text: Input text
            entity_types: Entity types to extract
            scope_id: Optional scope identifier
            source_channel: Optional source channel

        Returns:
            Dict with 'entities' and 'relations' keys
        """
        entities = self.ner.extract(text, entity_types, scope_id=scope_id, source_channel=source_channel)
        relations = self.re.extract(text, scope_id=scope_id, source_channel=source_channel)

        return {
            'entities': [asdict(e) for e in entities],
            'relations': [asdict(r) for r in relations],
            'token_cost': self._estimate_tokens(text),
            'extraction_method': 'local_slm'
        }
    
    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimation"""
        return len(text.split()) + len(text) // 4


def main():
    """Deprecated: use mnemosyne.extraction.cli:main for coding domain."""
    import argparse

    parser = argparse.ArgumentParser(description='Extract entities and relations using local SLMs')
    parser.add_argument('--text', help='Text to process')
    parser.add_argument('--file', help='File to process')
    parser.add_argument('--entities', nargs='+', default=['PERSON', 'ORGANIZATION', 'DATE'],
                       help='Entity types to extract')

    args = parser.parse_args()

    if args.text:
        text = args.text
    elif args.file:
        text = Path(args.file).read_text()
    else:
        text = "John Smith works at Google and lives in San Francisco. He joined the company in 2020."

    extractor = SemanticExtractor()
    result = extractor.extract(text, args.entities)

    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()