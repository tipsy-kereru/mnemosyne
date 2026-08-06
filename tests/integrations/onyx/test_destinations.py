from __future__ import annotations

from mnemosyne.integrations.onyx.destinations import (
    Destination,
    DestinationNotBound,
    DestinationRegistry,
)


def _destination(destination_id: str, **overrides) -> Destination:
    values = {
        "destination_id": destination_id,
        "base_url": "https://onyx.example.test",
        "api_key_env": "ONYX_TEST_KEY",
        "cc_pair_id_env": "ONYX_TEST_CC",
    }
    values.update(overrides)
    return Destination(**values)




def test_t17_scope_bindings_select_independent_destinations():
    first = _destination("first", cc_pair_id_env="CC_FIRST", classification_ceiling="private")
    second = _destination("second", cc_pair_id_env="CC_SECOND", classification_ceiling="internal")
    registry = DestinationRegistry(
        {"first": first, "second": second},
        {"scope-a": "first", "scope-b": "second"},
    )
    assert registry.for_scope("scope-a").cc_pair_id_env == "CC_FIRST"
    assert registry.for_scope("scope-a").classification_ceiling == "private"
    assert registry.for_scope("scope-b").cc_pair_id_env == "CC_SECOND"
    assert registry.for_scope("scope-b").classification_ceiling == "internal"




