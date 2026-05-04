"""Vendor-neutral LLM bridge for mnemosyne extraction."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess  # noqa: S404 -- used for optional `claude` CLI fallback only
from typing import Any, Optional

logger = logging.getLogger(__name__)


SCHEMA_HINTS: dict[str, str] = {
    "coding": "function, class, module, api, bug, feature, test, dependency",
    "daily": "task, person, place, event, habit, preference, note",
    "legal": "statute, clause, case, party, obligation, deadline, contract",
}


EXTRACTION_PROMPT = """You are a knowledge graph extraction agent. Extract entities and relations from the following text.

Domain: {domain}
Schema hint: {schema_hint}

Text:
{text}

CRITICAL: Your response must be ONLY the raw JSON object below. Do NOT include any text, explanation, reasoning, markdown fences (```), or whitespace before the opening brace. Start your response with {{ and end with }}.

Required format:
{{"nodes": [{{"id": "slug_entityname", "label": "Human Readable Name", "type": "entity_type", "source_file": ""}}],
  "edges": [{{"source": "node_id", "target": "node_id", "relation": "relation_type",
             "confidence": "EXTRACTED|INFERRED|AMBIGUOUS", "confidence_score": 0.9}}]}}

Rules:
- Node IDs: lowercase alphanumeric+underscore only, format: filename_entityname
- confidence: EXTRACTED (explicit in text=1.0), INFERRED (implied=0.6-0.9), AMBIGUOUS (uncertain=0.1-0.3)
- Entity types for {domain} domain: {entity_types}
- Extract named entities matching the schema types
- Extract relations as subject-verb-object triples
- Keep nodes and edges arrays; return empty arrays if nothing found
"""


# @MX:ANCHOR: [AUTO] LLMBridge is the vendor-neutral entry point for extraction.
# @MX:REASON: Used by LLMExtractor and CLI fallback paths; fan_in >= 3.
class LLMBridge:
    """Vendor-neutral bridge for LLM-based entity/relation extraction."""

    def __init__(self, provider: Optional[str] = None) -> None:
        self.provider = provider or self._detect_provider()
        logger.debug("LLMBridge using provider=%s", self.provider)

    @staticmethod
    def _detect_provider() -> str:
        """Auto-detect provider from environment variables."""
        if os.environ.get("MNEMOSYNE_LLM"):
            return os.environ["MNEMOSYNE_LLM"]
        if os.environ.get("Z_AI_API_KEY"):
            return "zai"
        if os.environ.get("ANTHROPIC_API_KEY"):
            return "anthropic"
        if os.environ.get("OPENAI_API_KEY"):
            return "openai"
        if os.environ.get("GOOGLE_API_KEY"):
            return "google"
        return "cli"

    def extract(
        self, text: str, schema_hint: str, domain: str = "daily"
    ) -> dict[str, Any]:
        """Extract entities and relations. Returns ``{"nodes": [...], "edges": [...]}``."""
        prompt = EXTRACTION_PROMPT.format(
            domain=domain,
            schema_hint=schema_hint,
            text=text,
            entity_types=SCHEMA_HINTS.get(domain, schema_hint),
        )

        provider = self.provider
        try:
            if provider == "zai":
                raw = self._call_zai(prompt)
            elif provider == "anthropic":
                raw = self._call_anthropic(prompt)
            elif provider == "openai":
                raw = self._call_openai(prompt)
            elif provider == "google":
                raw = self._call_google(prompt)
            else:
                raw = self._call_cli(prompt)
        except ImportError as exc:
            logger.warning(
                "Provider %s import failed (%s); falling back to cli", provider, exc
            )
            raw = self._call_cli(prompt)
        except (RuntimeError, OSError) as exc:
            logger.error("Provider %s call failed: %s", provider, exc)
            return {"nodes": [], "edges": [], "error": str(exc)}

        if not raw:
            return {"nodes": [], "edges": [], "error": "empty response"}

        return self._parse_json(raw)

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        text = raw.strip()
        # Strip optional markdown fences
        fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("LLM JSON parse failed: %s", exc)
            # Best-effort: try to slice out the first {...} block
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                except json.JSONDecodeError as exc2:
                    return {"nodes": [], "edges": [], "error": str(exc2)}
            else:
                return {"nodes": [], "edges": [], "error": str(exc)}

        if not isinstance(parsed, dict):
            return {"nodes": [], "edges": [], "error": "non-object response"}
        parsed.setdefault("nodes", [])
        parsed.setdefault("edges", [])
        return parsed

    # -- provider implementations --

    @staticmethod
    def _call_zai(prompt: str) -> str:
        import openai  # type: ignore

        client = openai.OpenAI(
            base_url="https://api.z.ai/api/coding/paas/v4",
            api_key=os.environ.get("Z_AI_API_KEY", ""),
        )
        model = os.environ.get("Z_AI_MODEL", "glm-4.5-air")
        resp = client.chat.completions.create(
            model=model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        msg = resp.choices[0].message
        content = msg.content or ""
        # GLM reasoning models put the answer in reasoning_content when content is empty
        if not content:
            content = getattr(msg, "reasoning_content", "") or ""
        return content

    @staticmethod
    def _call_anthropic(prompt: str) -> str:
        import anthropic  # type: ignore

        client = anthropic.Anthropic()
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        # SDK returns a list of content blocks; gather text blocks.
        chunks: list[str] = []
        for block in getattr(msg, "content", []) or []:
            text_attr = getattr(block, "text", None)
            if text_attr:
                chunks.append(text_attr)
        return "".join(chunks)

    @staticmethod
    def _call_openai(prompt: str) -> str:
        import openai  # type: ignore

        client = openai.OpenAI()
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        choice = resp.choices[0]
        return choice.message.content or ""

    @staticmethod
    def _call_google(prompt: str) -> str:
        import google.generativeai as genai  # type: ignore

        api_key = os.environ.get("GOOGLE_API_KEY")
        if api_key:
            genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        resp = model.generate_content(prompt)
        return getattr(resp, "text", "") or ""

    @staticmethod
    def _call_cli(prompt: str) -> str:
        if not shutil.which("claude"):
            raise RuntimeError("claude CLI not found")
        try:
            result = subprocess.run(  # noqa: S603 -- explicit list of args, no shell.
                ["claude", "-p", prompt],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            raise RuntimeError(f"claude CLI execution failed: {exc}") from exc
        if result.returncode != 0:
            raise RuntimeError(
                f"claude CLI exit {result.returncode}: {result.stderr.strip()}"
            )
        return result.stdout
