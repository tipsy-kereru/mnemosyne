"""Shared synthetic fixtures for the Slack integration tests.

Everything here is offline: a temporary SQLite file and an in-memory
fixture dict. No network, no credentials, no Slack, no Onyx.
"""

from __future__ import annotations

import copy
from datetime import timedelta
from typing import Any

import pytest

from mnemosyne.integrations.slack.acl import utc_now, utc_now_iso
from mnemosyne.integrations.slack.connector import SyntheticConnector
from mnemosyne.integrations.slack.identity import source_id
from mnemosyne.integrations.slack.store import SlackStore
from mnemosyne.integrations.slack.sync import SlackSyncEngine

TEAM_ID = "T0FIXTURE"
CHANNEL_ID = "C0FIXTURE1"
SCOPE_ID = "scope-work-slack"
SOURCE_ID = source_id(TEAM_ID, CHANNEL_ID)

_TS_BASE = 1712345678


def mk_ts(offset: int, micro: int = 100) -> str:
    """A well-formed Slack ts. Stays 10 digits for any sane offset."""
    return f"{_TS_BASE + offset}.{micro:06d}"


def public_channel(members: list[str] | None = None, **overrides: Any) -> dict:
    info = {
        "name": "general",
        "is_private": False,
        "is_ext_shared": False,
        "is_org_shared": False,
        "is_im": False,
        "is_mpim": False,
        "members": list(members if members is not None else ["U1", "U2"]),
        "captured_at": utc_now_iso(),
    }
    info.update(overrides)
    return info


def thread_messages() -> list[dict]:
    """Three roots with three replies each — 12 messages total."""
    messages: list[dict] = []
    for root in (0, 4, 8):
        root_ts = mk_ts(root)
        messages.append(
            {"ts": root_ts, "user": "U1", "text": f"root {root}"}
        )
        for reply in range(1, 4):
            messages.append({
                "ts": mk_ts(root + reply),
                "thread_ts": root_ts,
                "user": "U2",
                "text": f"reply {root}.{reply}",
            })
    return messages


def build_fixture(info: dict | None = None, messages: list[dict] | None = None) -> dict:
    return {
        "team_id": TEAM_ID,
        "channels": {
            CHANNEL_ID: {
                "info": info if info is not None else public_channel(),
                "messages": copy.deepcopy(
                    messages if messages is not None else thread_messages()
                ),
            }
        },
    }


def stale_iso(hours: float) -> str:
    return (utc_now() - timedelta(hours=hours)).isoformat()


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "knowledge.db"


@pytest.fixture
def store(db_path):
    s = SlackStore(db_path)
    yield s
    s.close()


@pytest.fixture
def registered_store(store):
    store.register_source(TEAM_ID, CHANNEL_ID, SCOPE_ID)
    return store


@pytest.fixture
def fixture_data():
    return build_fixture()


@pytest.fixture
def fixture_file(tmp_path, fixture_data):
    """The same fixture, on disk, for CLI runs that take --fixture."""
    import json

    path = tmp_path / "slack_fixture.json"
    path.write_text(json.dumps(fixture_data), encoding="utf-8")
    return path


def make_engine(store: SlackStore, fixture: dict, **kwargs) -> SlackSyncEngine:
    return SlackSyncEngine(store, SyntheticConnector(fixture, **kwargs))
