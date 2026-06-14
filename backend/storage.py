import aiosqlite
import json
import calendar
from pathlib import Path
from datetime import datetime, timezone, timedelta

DB_PATH = Path(__file__).parent / "conversations.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
                content TEXT,
                tool_calls TEXT,
                tool_call_id TEXT,
                timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                turn_order INTEGER NOT NULL
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                period TEXT NOT NULL CHECK(period IN ('daily', 'weekly', 'monthly')),
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS _turn_counter (
                user_id TEXT PRIMARY KEY,
                counter INTEGER NOT NULL DEFAULT 0
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_turn ON conversations(user_id, turn_order)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_timestamp ON conversations(timestamp)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_period ON summaries(user_id, period, period_start)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_summaries_created_at ON summaries(created_at)")
        await conn.commit()


async def save_turn(user_id: str, role: str, content: str | None, tool_calls: list | None, tool_call_id: str | None, turn_order: int):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT INTO conversations (user_id, role, content, tool_calls, tool_call_id, turn_order) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, role, content, json.dumps(tool_calls) if tool_calls else None, tool_call_id, turn_order),
        )
        await conn.commit()


async def save_turns(user_id: str, turns: list[tuple[str, str | None, list | None, str | None]]) -> list[int]:
    """Atomically save multiple turns with auto-incremented turn_order. Returns assigned turn_orders."""
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO _turn_counter (user_id, counter) VALUES (?, 0)",
            (user_id,),
        )
        orders = []
        for role, content, tool_calls, tool_call_id in turns:
            await conn.execute(
                "UPDATE _turn_counter SET counter = counter + 1 WHERE user_id = ?",
                (user_id,),
            )
            cursor = await conn.execute(
                "SELECT counter FROM _turn_counter WHERE user_id = ?",
                (user_id,),
            )
            row = await cursor.fetchone()
            to = row[0]
            orders.append(to)
            await conn.execute(
                "INSERT INTO conversations (user_id, role, content, tool_calls, tool_call_id, turn_order) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, role, content, json.dumps(tool_calls) if tool_calls else None, tool_call_id, to),
            )
        await conn.commit()
    return orders


async def get_history(user_id: str, limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute(
            "SELECT role, content, tool_calls, tool_call_id, turn_order FROM conversations WHERE user_id = ? ORDER BY turn_order DESC LIMIT ?",
            (user_id, limit),
        )
        rows = await cursor.fetchall()
    return [
        {
            "role": r[0],
            "content": r[1],
            "tool_calls": json.loads(r[2]) if r[2] else None,
            "tool_call_id": r[3],
            "turn_order": r[4],
        }
        for r in reversed(rows)
    ]


async def get_turn_count(user_id: str) -> int:
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute("SELECT MAX(turn_order) FROM conversations WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
    return row[0] if row and row[0] else 0


async def clear_history(user_id: str):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
        await conn.execute("DELETE FROM summaries WHERE user_id = ?", (user_id,))
        await conn.execute("DELETE FROM _turn_counter WHERE user_id = ?", (user_id,))
        await conn.commit()


async def cleanup_old_history(retention_days: int = 30):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("DELETE FROM conversations WHERE timestamp < datetime('now', ?)", (f"-{retention_days} days",))
        await conn.execute("DELETE FROM summaries WHERE created_at < datetime('now', ?)", (f"-{retention_days} days",))
        await conn.commit()


async def save_summary(user_id: str, period: str, period_start: str, period_end: str, content: str):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT INTO summaries (user_id, period, period_start, period_end, content) VALUES (?, ?, ?, ?, ?)",
            (user_id, period, period_start, period_end, content),
        )
        await conn.commit()


async def get_summaries(user_id: str) -> dict:
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute(
            "SELECT period, period_start, period_end, content FROM summaries WHERE user_id = ? ORDER BY period_start DESC",
            (user_id,),
        )
        rows = await cursor.fetchall()
    monthly = [r for r in rows if r[0] == "monthly"]
    weekly = [r for r in rows if r[0] == "weekly"]
    daily = [r for r in rows if r[0] == "daily"]
    def _to_dict(r):
        return {"period": r[0], "period_start": r[1], "period_end": r[2], "content": r[3]}

    return {
        "monthly": [_to_dict(r) for r in monthly[:12]],
        "weekly": [_to_dict(r) for r in weekly[:4]],
        "daily": [_to_dict(r) for r in daily[:7]],
    }


async def get_pending_summaries(user_id: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute(
            """
            SELECT period, period_start, period_end
            FROM summaries WHERE user_id = ?
            ORDER BY period, period_start DESC
            """,
            (user_id,),
        )
        rows = await cursor.fetchall()
    existing = {(r[0], r[1], r[2]) for r in rows}

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    pending = []

    for d in range(1, 8):
        ds = (today_start - timedelta(days=d)).isoformat()
        de = (today_start - timedelta(days=d - 1)).isoformat()
        if ("daily", ds, de) not in existing:
            pending.append(("daily", ds, de))

    for w in range(1, 5):
        ws = (week_start - timedelta(weeks=w)).isoformat()
        we = (week_start - timedelta(weeks=w) + timedelta(days=7)).isoformat()
        if ("weekly", ws, we) not in existing:
            pending.append(("weekly", ws, we))

    for m in range(1, 13):
        target_month = now.month - m
        target_year = now.year
        while target_month < 1:
            target_month += 12
            target_year -= 1
        ms_dt = today_start.replace(year=target_year, month=target_month, day=1)
        last_day = calendar.monthrange(target_year, target_month)[1]
        me_dt = ms_dt.replace(day=last_day, hour=23, minute=59, second=59, microsecond=999999)
        ms = ms_dt.isoformat()
        me = me_dt.isoformat()
        if ("monthly", ms, me) not in existing:
            pending.append(("monthly", ms, me))

    return pending


async def get_period_messages(user_id: str, period_start: str, period_end: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute(
            """
            SELECT role, content, tool_calls, tool_call_id, timestamp
            FROM conversations
            WHERE user_id = ? AND timestamp >= ? AND timestamp <= ?
            ORDER BY turn_order ASC
            """,
            (user_id, period_start, period_end),
        )
        rows = await cursor.fetchall()
    return [
        {
            "role": r[0],
            "content": r[1],
            "tool_calls": json.loads(r[2]) if r[2] else None,
            "tool_call_id": r[3],
            "timestamp": r[4],
        }
        for r in rows
    ]
