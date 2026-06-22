"""REQ-NL-001: NL intent router unit tests (5 intents + fallback)."""

from __future__ import annotations

import pytest

from mnemosyne.query.router import NLQueryRouter


@pytest.fixture()
def router() -> NLQueryRouter:
    # GLiNER2 disabled so the heuristic path is deterministic in CI.
    return NLQueryRouter(use_gliner=False)


@pytest.mark.parametrize(
    "question, expected_intent, expect_rel",
    [
        ("what calls authenticate?", "relation_query", True),
        ("what function does the parser use", "relation_query", True),
        ("show me the path between AuthService and Database", "path_query", False),
        ("parse_config", "entity_lookup", False),
        ("parse_config_snake", "entity_lookup", False),
    ],
    ids=["relation-calls", "relation-uses", "path", "entity-single", "entity-snake"],
)
def test_intent_routing(
    router: NLQueryRouter, question: str, expected_intent: str, expect_rel: bool
) -> None:
    plan = router.route(question)
    assert plan.intent == expected_intent
    if expect_rel:
        assert plan.target_relations, "relation_query must carry relations"


def test_search_fallback_on_no_signal(router: NLQueryRouter) -> None:
    plan = router.route("hello world")
    assert plan.intent == "search"
    assert plan.confidence < 0.4


def test_low_confidence_rewrites_to_search(router: NLQueryRouter) -> None:
    # A capitalized token with no relation keyword -> entity_lookup at 0.55,
    # still above fallback. Force below by asking a bare "the".
    plan = router.route("the")
    assert plan.intent == "search"


def test_longdoc_signal_routes_when_long_enough(router: NLQueryRouter) -> None:
    tokens = ["word"] * 35
    tokens += ["find", "the", "section", "of", "the", "document", "layout"]
    plan = router.route(" ".join(tokens))
    assert plan.intent == "longdoc_retrieve"


def test_scope_propagated(router: NLQueryRouter) -> None:
    plan = router.route("parse_config", scope={"project": "proj-x"})
    assert plan.scope["project"] == "proj-x"


def test_relation_dsl_precomputed(router: NLQueryRouter) -> None:
    plan = router.route("what calls authenticate?")
    assert plan.raw_dsl == "relation:calls"
