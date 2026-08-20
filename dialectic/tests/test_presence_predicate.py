"""One definition of "present right now", shared by every reader.

WHY this file exists: the 90s staleness TTL used to be the presence
endpoint's private opinion. Three other readers took `user_presence.status`
raw, so a row stranded at 'online' by an ungraceful restart silently
suppressed that member's push, the annotator and the trading curator for
that room — forever, with no error anywhere. These tests pin the SQL form
and the Python form to each other, and pin the push gate to the Python form.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from presence import PRESENCE_STALE_AFTER, ONLINE_SQL, is_present, online_sql


NOW = datetime(2026, 8, 20, 3, 0, tzinfo=timezone.utc)
FRESH = NOW - timedelta(seconds=30)
STRANDED = NOW - timedelta(hours=3)


class TestIsPresent:
    def test_fresh_online_is_present(self):
        assert is_present("online", FRESH, now=NOW) is True

    def test_stranded_online_is_not_present(self):
        """The founding bug: an 'online' row nothing ever reset."""
        assert is_present("online", STRANDED, now=NOW) is False

    def test_offline_is_never_present_however_fresh(self):
        assert is_present("offline", NOW, now=NOW) is False

    def test_away_is_not_present(self):
        assert is_present("away", FRESH, now=NOW) is False

    def test_null_heartbeat_is_not_present(self):
        assert is_present("online", None, now=NOW) is False

    def test_boundary_is_exclusive(self):
        exactly = NOW - PRESENCE_STALE_AFTER
        assert is_present("online", exactly, now=NOW) is False
        assert is_present("online", exactly + timedelta(seconds=1), now=NOW) is True


class TestOnlineSql:
    def test_unaliased_names_the_columns_bare(self):
        assert ONLINE_SQL == online_sql()
        assert "status = 'online'" in ONLINE_SQL
        assert "last_heartbeat >" in ONLINE_SQL

    def test_alias_qualifies_every_column(self):
        sql = online_sql("up")
        assert "up.status" in sql
        assert "up.last_heartbeat" in sql
        # No bare column may survive — an unqualified name in a joined query
        # is either ambiguous or silently reads the wrong table.
        assert " status" not in sql.replace("up.status", "")
        assert " last_heartbeat" not in sql.replace("up.last_heartbeat", "")

    def test_sql_and_python_agree_on_the_same_ttl(self):
        seconds = int(PRESENCE_STALE_AFTER.total_seconds())
        assert f"'{seconds} seconds'" in ONLINE_SQL


class TestEveryConsumerSharesThePredicate:
    """The four readers must not be able to drift apart again."""

    def test_push_gate_uses_is_present_not_raw_status(self):
        """A stranded 'online' row must NOT suppress a push."""
        import asyncio
        from transport.handlers import MessageHandler

        class FakeConnections:
            def is_user_connected(self, user_id, room_id):
                return False

        class FakeDB:
            def __init__(self, row):
                self.row = row
                self.sql = None

            async def fetchrow(self, sql, *args):
                self.sql = sql
                return self.row

        user_id, room_id = uuid4(), uuid4()

        # The row the founding bug leaves behind.
        db = FakeDB({"status": "online", "last_heartbeat": STRANDED})
        handler = MessageHandler.__new__(MessageHandler)
        handler.db = db
        handler.connections = FakeConnections()
        assert asyncio.run(handler._should_send_push(user_id, room_id)) is True, (
            "a stranded 'online' row must not suppress push"
        )
        # It cannot reach that verdict without reading the heartbeat.
        assert "last_heartbeat" in db.sql

        # A genuinely present user is still suppressed.
        db = FakeDB({"status": "online", "last_heartbeat": datetime.now(timezone.utc)})
        handler.db = db
        assert asyncio.run(handler._should_send_push(user_id, room_id)) is False

        # No row at all still pushes.
        db = FakeDB(None)
        handler.db = db
        assert asyncio.run(handler._should_send_push(user_id, room_id)) is True

    @pytest.mark.parametrize("module,attr", [
        ("llm.annotator", "ONLINE_SQL"),
        ("llm.trading_curator", "ONLINE_SQL"),
    ])
    def test_consumers_import_the_shared_constant(self, module, attr):
        import importlib
        mod = importlib.import_module(module)
        assert getattr(mod, attr) == ONLINE_SQL

    def test_endpoint_and_predicate_agree(self):
        from api.main import _effective_presence_status
        for status, hb in [
            ("online", FRESH), ("online", STRANDED), ("online", None),
            ("offline", FRESH), ("offline", None),
        ]:
            effective = _effective_presence_status(
                status, hb, locally_connected=False, now=NOW,
            )
            assert (effective == "online") == is_present(status, hb, now=NOW), (
                f"endpoint and predicate disagree on ({status}, {hb})"
            )
