# Product: Mnemosyne Knowledge Graph

## Summary

Local-first, zero-API-cost knowledge memory system for AI agents. Provides persistent, compounding knowledge across three domains: daily life, coding, and legal. Based on Google Gemini Universal Temporal Knowledge Graph research and Andrej Karpathy's LLM-as-programmer paradigm.

## Problem

AI agents have no persistent memory across sessions. Every conversation starts from zero. Knowledge gained in one session (code patterns, user preferences, legal deadlines) is lost. RAG alone retrieves documents but doesn't build compound knowledge.

## Solution

A 4-layer architecture that transforms raw inputs into a navigable knowledge graph:

1. **Raw Source Layer** (immutable): Drop anything — papers, code, notes, screenshots
2. **Wiki Layer** (Markdown + wiki-links): Extracted knowledge in human-readable format
3. **Schema Layer** (CLAUDE.md): Declarative domain schemas define entity/relationship types
4. **Knowledge Graph** (SQLite + NetworkX): Temporal, queryable graph with history tracking

## Key Differentiators

- **Zero API cost**: Deterministic extraction (Tree-sitter, SpaCy) + local SLMs (GLiNER2, REBEL)
- **Knowledge compounding**: Immutable raw layer enables re-compilation when extraction models improve
- **Temporal tracking**: Every entity has full change history
- **3-domain schemas**: Daily life, coding, legal with declarative Markdown schemas

## Target Users

- AI agents needing persistent memory (Discord/Teams/Slack bots, coding assistants)
- Individual knowledge workers with cross-domain knowledge
- Legal professionals tracking case/timeline/obligation relationships

## Current Limitations

- No session isolation (all sessions share one graph)
- No project/topic hierarchy
- No source channel tracking (which platform contributed what)
- Deterministic parsing works best for well-structured code
- Local SLM models need 8GB+ RAM
