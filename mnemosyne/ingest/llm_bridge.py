"""Vendor-neutral LLM bridge for mnemosyne extraction."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess  # noqa: S404 -- used for optional `claude` CLI fallback only
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_LLM_MAX_TOKENS = 8192


def _max_tokens() -> int:
    """Return per-request token budget, overridable via MNEMOSYNE_LLM_MAX_TOKENS."""
    raw = os.environ.get("MNEMOSYNE_LLM_MAX_TOKENS", "")
    if raw:
        try:
            val = int(raw)
            if val > 0:
                return val
        except ValueError:
            logger.warning("MNEMOSYNE_LLM_MAX_TOKENS=%r is not a positive int, using default", raw)
    return DEFAULT_LLM_MAX_TOKENS


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
        if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
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
            try:
                raw = self._call_cli(prompt)
            except Exception as cli_exc:
                return {"nodes": [], "edges": [], "error": f"Fallback CLI failed: {cli_exc}"}
        except Exception as exc:
            # Catch all library exceptions (OpenAIError, APIError) and fall back to CLI dynamically
            logger.error("Provider %s call failed: %s; falling back to cli", provider, exc)
            try:
                raw = self._call_cli(prompt)
            except Exception as cli_exc:
                return {"nodes": [], "edges": [], "error": f"API call failed: {exc}, Fallback CLI failed: {cli_exc}"}

        if not raw:
            return {"nodes": [], "edges": [], "error": "empty response"}

        return self._parse_json(raw)

    async def extract_async(
        self,
        text: str,
        schema_hint: str,
        domain: str = "daily",
        semaphore: Optional[asyncio.Semaphore] = None,
    ) -> dict[str, Any]:
        """Async variant of :meth:`extract` — runs the blocking call in a thread.

        Pass a shared ``semaphore`` (e.g. ``asyncio.Semaphore(5)``) to cap
        concurrent LLM API calls and avoid rate limiting.
        """
        if semaphore is None:
            return await asyncio.get_event_loop().run_in_executor(
                None, lambda: self.extract(text, schema_hint, domain)
            )
        async with semaphore:
            return await asyncio.get_event_loop().run_in_executor(
                None, lambda: self.extract(text, schema_hint, domain)
            )

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        text = raw.strip()
        # Strip optional markdown fences
        fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()
        # Helper to repair truncated JSON due to token limits
        def try_repair(json_str: str) -> Optional[dict[str, Any]]:
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass

            temp = json_str.strip()
            if not temp:
                return None

            # Scan the string to find open brackets and unclosed strings
            stack = []
            in_string = False
            escaped = False
            
            i = 0
            n = len(temp)
            while i < n:
                char = temp[i]
                if escaped:
                    escaped = False
                elif char == '\\':
                    escaped = True
                elif char == '"':
                    in_string = not in_string
                elif not in_string:
                    if char in ('{', '['):
                        stack.append(char)
                    elif char == '}':
                        if stack and stack[-1] == '{':
                            stack.pop()
                    elif char == ']':
                        if stack and stack[-1] == '[':
                            stack.pop()
                i += 1

            repaired = temp
            if in_string:
                repaired += '"'

            repaired_stripped = repaired.rstrip()
            if repaired_stripped.endswith(','):
                repaired = repaired_stripped[:-1]
            elif repaired_stripped.endswith(':'):
                repaired = repaired_stripped + '""'

            while stack:
                open_char = stack.pop()
                if open_char == '{':
                    repaired += '}'
                elif open_char == '[':
                    repaired += ']'

            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                return None

        parsed = try_repair(text)
        if parsed is None:
            # Fallback: slice out the first matching {...} block
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                parsed = try_repair(match.group(0))

        if parsed is None:
            return {"nodes": [], "edges": [], "error": "JSON parse failed and cannot be repaired"}

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
        # GLM-4.5-air is a reasoning model: it spends tokens on internal thinking
        # before emitting the answer in content. response_format="json_object" causes
        # it to exhaust the token budget on reasoning, leaving content empty.
        # Rely on the prompt instructions + _parse_json fence-stripping instead.
        resp = client.chat.completions.create(
            model=model,
            max_tokens=_max_tokens(),
            messages=[{"role": "user", "content": prompt}],
        )
        msg = resp.choices[0].message
        return msg.content or ""

    @staticmethod
    def _call_anthropic(prompt: str) -> str:
        import anthropic  # type: ignore

        api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=_max_tokens(),
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
            max_tokens=_max_tokens(),
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
        resp = model.generate_content(prompt, generation_config={"max_output_tokens": _max_tokens()})
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
