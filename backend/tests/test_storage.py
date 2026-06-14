import pytest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta

import storage


@pytest.fixture(autouse=True)
def reset_db_path(tmp_path):
    db_path = tmp_path / "test_conversations.db"
    with patch.object(storage, "DB_PATH", db_path):
        yield db_path


@pytest.fixture
async def initialized_db(reset_db_path):
    await storage.init_db()
    return reset_db_path


class TestInitDB:
    @pytest.mark.asyncio
    async def test_creates_tables(self, initialized_db):
        import aiosqlite
        async with aiosqlite.connect(str(initialized_db)) as conn:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = [r[0] for r in await cursor.fetchall()]
        assert "conversations" in tables
        assert "summaries" in tables

    @pytest.mark.asyncio
    async def test_idempotent(self, initialized_db):
        await storage.init_db()


class TestSaveAndGetHistory:
    @pytest.mark.asyncio
    async def test_save_and_load(self, initialized_db):
        await storage.save_turn("user1", "user", "Hello", None, None, 1)
        await storage.save_turn("user1", "assistant", "Hi there", None, None, 2)

        history = await storage.get_history("user1")
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Hello"
        assert history[1]["role"] == "assistant"
        assert history[1]["content"] == "Hi there"

    @pytest.mark.asyncio
    async def test_save_with_tool_calls(self, initialized_db):
        tool_calls = [{"id": "call-1", "function": {"name": "create_event", "arguments": "{}"}}]
        await storage.save_turn("user1", "assistant", None, tool_calls, None, 1)
        await storage.save_turn("user1", "tool", "OK", None, "call-1", 2)

        history = await storage.get_history("user1")
        assert len(history) == 2
        assert history[0]["tool_calls"] == tool_calls
        assert history[1]["tool_call_id"] == "call-1"

    @pytest.mark.asyncio
    async def test_limit(self, initialized_db):
        for i in range(30):
            await storage.save_turn("user1", "user", f"Msg {i}", None, None, i + 1)

        history = await storage.get_history("user1", limit=10)
        assert len(history) == 10
        assert history[0]["content"] == "Msg 20"

    @pytest.mark.asyncio
    async def test_user_scoping(self, initialized_db):
        await storage.save_turn("user1", "user", "User1 msg", None, None, 1)
        await storage.save_turn("user2", "user", "User2 msg", None, None, 1)

        h1 = await storage.get_history("user1")
        h2 = await storage.get_history("user2")
        assert len(h1) == 1
        assert h1[0]["content"] == "User1 msg"
        assert len(h2) == 1
        assert h2[0]["content"] == "User2 msg"

    @pytest.mark.asyncio
    async def test_empty_history(self, initialized_db):
        history = await storage.get_history("nobody")
        assert history == []

    @pytest.mark.asyncio
    async def test_turn_order_preserved(self, initialized_db):
        for i in range(5):
            await storage.save_turn("user1", "user", f"Msg {i}", None, None, i + 1)

        history = await storage.get_history("user1")
        for i, h in enumerate(history):
            assert h["turn_order"] == i + 1


class TestTurnCount:
    @pytest.mark.asyncio
    async def test_zero_when_empty(self, initialized_db):
        count = await storage.get_turn_count("user1")
        assert count == 0

    @pytest.mark.asyncio
    async def test_increments(self, initialized_db):
        await storage.save_turn("user1", "user", "Msg", None, None, 5)
        await storage.save_turn("user1", "assistant", "Reply", None, None, 10)
        count = await storage.get_turn_count("user1")
        assert count == 10


class TestClearHistory:
    @pytest.mark.asyncio
    async def test_clears_conversations_and_summaries(self, initialized_db):
        await storage.save_turn("user1", "user", "Msg", None, None, 1)
        await storage.save_summary("user1", "daily", "2025-01-01T00:00:00+00:00", "2025-01-02T00:00:00+00:00", "Summary")

        await storage.clear_history("user1")

        history = await storage.get_history("user1")
        assert history == []
        summaries = await storage.get_summaries("user1")
        assert summaries["monthly"] == []
        assert summaries["weekly"] == []
        assert summaries["daily"] == []

    @pytest.mark.asyncio
    async def test_clear_only_target_user(self, initialized_db):
        await storage.save_turn("user1", "user", "Msg1", None, None, 1)
        await storage.save_turn("user2", "user", "Msg2", None, None, 1)

        await storage.clear_history("user1")

        h1 = await storage.get_history("user1")
        h2 = await storage.get_history("user2")
        assert h1 == []
        assert len(h2) == 1


class TestSummaries:
    @pytest.mark.asyncio
    async def test_save_and_get_summary(self, initialized_db):
        await storage.save_summary(
            "user1", "monthly",
            "2025-01-01T00:00:00+00:00", "2025-01-31T23:59:59+00:00",
            "January summary"
        )

        summaries = await storage.get_summaries("user1")
        assert len(summaries["monthly"]) == 1
        assert summaries["monthly"][0]["content"] == "January summary"

    @pytest.mark.asyncio
    async def test_monthly_capped_at_12(self, initialized_db):
        for i in range(15):
            await storage.save_summary(
                "user1", "monthly",
                f"2024-{i+1:02d}-01T00:00:00+00:00", f"2024-{i+1:02d}-28T23:59:59+00:00",
                f"Summary {i}"
            )

        summaries = await storage.get_summaries("user1")
        assert len(summaries["monthly"]) == 12

    @pytest.mark.asyncio
    async def test_weekly_capped_at_4(self, initialized_db):
        for i in range(6):
            await storage.save_summary(
                "user1", "weekly",
                f"2025-01-{i*7+1:02d}T00:00:00+00:00", f"2025-01-{i*7+7:02d}T23:59:59+00:00",
                f"Week {i}"
            )

        summaries = await storage.get_summaries("user1")
        assert len(summaries["weekly"]) == 4

    @pytest.mark.asyncio
    async def test_daily_capped_at_7(self, initialized_db):
        for i in range(10):
            await storage.save_summary(
                "user1", "daily",
                f"2025-01-{i+1:02d}T00:00:00+00:00", f"2025-01-{i+2:02d}T00:00:00+00:00",
                f"Day {i}"
            )

        summaries = await storage.get_summaries("user1")
        assert len(summaries["daily"]) == 7

    @pytest.mark.asyncio
    async def test_summaries_user_scoped(self, initialized_db):
        await storage.save_summary("user1", "daily", "2025-01-01T00:00:00+00:00", "2025-01-02T00:00:00+00:00", "S1")
        await storage.save_summary("user2", "daily", "2025-01-01T00:00:00+00:00", "2025-01-02T00:00:00+00:00", "S2")

        s1 = await storage.get_summaries("user1")
        s2 = await storage.get_summaries("user2")
        assert s1["daily"][0]["content"] == "S1"
        assert s2["daily"][0]["content"] == "S2"


class TestGetPeriodMessages:
    @pytest.mark.asyncio
    async def test_returns_messages_in_range(self, initialized_db):
        now = datetime.now(timezone.utc)
        yesterday = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

        await storage.save_turn("user1", "user", "Old msg", None, None, 1)

        import aiosqlite
        async with aiosqlite.connect(str(initialized_db)) as conn:
            await conn.execute(
                "UPDATE conversations SET timestamp = ? WHERE content = 'Old msg'",
                (yesterday.isoformat(),)
            )
            await conn.commit()

        await storage.save_turn("user1", "user", "New msg", None, None, 2)

        messages = await storage.get_period_messages("user1", yesterday.isoformat(), now.isoformat())
        contents = [m["content"] for m in messages]
        assert "Old msg" in contents
        assert "New msg" in contents


class TestPendingSummaries:
    @pytest.mark.asyncio
    async def test_returns_pending_when_empty(self, initialized_db):
        pending = await storage.get_pending_summaries("user1")
        assert len(pending) > 0
        periods = {p[0] for p in pending}
        assert "daily" in periods
        assert "weekly" in periods
        assert "monthly" in periods

    @pytest.mark.asyncio
    async def test_excludes_existing(self, initialized_db):
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        ds = (today_start - timedelta(days=1)).isoformat()
        de = today_start.isoformat()

        await storage.save_summary("user1", "daily", ds, de, "Existing")

        pending = await storage.get_pending_summaries("user1")
        daily_pending = [p for p in pending if p[0] == "daily"]
        assert (ds, de) not in [(p[1], p[2]) for p in daily_pending]


class TestSaveTurns:
    @pytest.mark.asyncio
    async def test_saves_multiple_turns_atomically(self, initialized_db):
        turns = [
            ("user", "Hello", None, None),
            ("assistant", None, [{"id": "call-1"}], None),
            ("tool", "OK", None, "call-1"),
            ("assistant", "Done", None, None),
        ]
        orders = await storage.save_turns("user1", turns)
        assert len(orders) == 4
        assert orders == [1, 2, 3, 4]

        history = await storage.get_history("user1")
        assert len(history) == 4
        assert history[0]["role"] == "user"
        assert history[1]["tool_calls"] == [{"id": "call-1"}]
        assert history[2]["tool_call_id"] == "call-1"

    @pytest.mark.asyncio
    async def test_counter_increments_across_calls(self, initialized_db):
        await storage.save_turns("user1", [("user", "First", None, None)])
        await storage.save_turns("user1", [("assistant", "Reply", None, None)])

        history = await storage.get_history("user1")
        assert len(history) == 2
        assert history[0]["turn_order"] == 1
        assert history[1]["turn_order"] == 2

    @pytest.mark.asyncio
    async def test_counter_independent_per_user(self, initialized_db):
        await storage.save_turns("user1", [("user", "A", None, None)])
        await storage.save_turns("user2", [("user", "B", None, None)])

        h1 = await storage.get_history("user1")
        h2 = await storage.get_history("user2")
        assert h1[0]["turn_order"] == 1
        assert h2[0]["turn_order"] == 1


class TestCounterResetOnClear:
    @pytest.mark.asyncio
    async def test_clear_resets_counter(self, initialized_db):
        await storage.save_turns("user1", [("user", "Msg", None, None)])
        await storage.clear_history("user1")

        await storage.save_turns("user1", [("user", "New", None, None)])
        history = await storage.get_history("user1")
        assert len(history) == 1
        assert history[0]["turn_order"] == 1


class TestCleanupOldHistory:
    @pytest.mark.asyncio
    async def test_deletes_old_records(self, initialized_db):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=60)).isoformat()

        await storage.save_turn("user1", "user", "Old", None, None, 1)
        import aiosqlite
        async with aiosqlite.connect(str(initialized_db)) as conn:
            await conn.execute(
                "UPDATE conversations SET timestamp = ? WHERE content = 'Old'",
                (old,)
            )
            await conn.commit()

        await storage.save_summary("user1", "daily", old, old, "Old summary")
        async with aiosqlite.connect(str(initialized_db)) as conn:
            await conn.execute(
                "UPDATE summaries SET created_at = ? WHERE content = 'Old summary'",
                (old,)
            )
            await conn.commit()

        await storage.cleanup_old_history(30)

        history = await storage.get_history("user1")
        assert len(history) == 0
