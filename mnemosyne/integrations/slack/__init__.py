"""Direct, manually operated Slack ingestion — isolated from the graph.

See ``docs/SLACK_INTEGRATION_CONTRACT.ko.md``. Two properties define this
package:

*Fail-closed.* Only public channels are readable, the ACL is checked
before anything is fetched, a stale ACL denies, and every degraded
condition denies rather than proceeding (§4, §10).

*Isolated.* Slack content lives only in the ``slack_*`` tables and never
in ``entities``/``relations`` (INV-1), so no existing query, MCP, HTTP,
retrieval, or wiki surface can return it. ``source_channel`` is
``work-slack``, distinct from the ``slack`` channel used by Onyx-sourced
documents.

The Web API adapter (``api``), its loopback mock (``mock_api``), the
credential loader (``config``), and the ``mnemosyne-slack`` CLI are not
re-exported here: importing them pulls in urllib and a YAML parser that
the core ingestion path does not need. Import those modules directly.
Live Slack traffic is blocked by default — see ``api.WebApiConnector``.
"""

from mnemosyne.integrations.slack.acl import (
    ALLOWED_CHANNEL_TYPES,
    ChannelInfo,
    acl_denial,
    classify_channel,
    quarantine_snapshot,
)
from mnemosyne.integrations.slack.connector import (
    FetchedMessage,
    SlackConnector,
    SyntheticConnector,
)
from mnemosyne.integrations.slack.identity import (
    CONTRACT_VERSION,
    SOURCE_CHANNEL,
    SlackIdentityError,
    is_valid_ts,
    message_hash,
    message_key,
    message_key_for_source,
    parse_source_id,
    source_id,
    thread_key,
)
from mnemosyne.integrations.slack.redact import redact
from mnemosyne.integrations.slack.store import (
    SlackMessage,
    SlackQuarantineRecord,
    SlackSource,
    SlackStore,
    SlackStoreError,
    init_slack_schema,
)
from mnemosyne.integrations.slack.sync import (
    SlackSyncEngine,
    SyncResult,
    safe_watermark,
)

__all__ = [
    "ALLOWED_CHANNEL_TYPES",
    "CONTRACT_VERSION",
    "ChannelInfo",
    "FetchedMessage",
    "SOURCE_CHANNEL",
    "SlackConnector",
    "SlackIdentityError",
    "SlackMessage",
    "SlackQuarantineRecord",
    "SlackSource",
    "SlackStore",
    "SlackStoreError",
    "SlackSyncEngine",
    "SyncResult",
    "SyntheticConnector",
    "acl_denial",
    "classify_channel",
    "init_slack_schema",
    "is_valid_ts",
    "message_hash",
    "message_key",
    "message_key_for_source",
    "parse_source_id",
    "quarantine_snapshot",
    "redact",
    "safe_watermark",
    "source_id",
    "thread_key",
]
