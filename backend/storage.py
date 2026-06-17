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
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                timezone TEXT NOT NULL DEFAULT 'UTC',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        # Migration: add timezone column if it doesn't exist (for existing DBs)
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN timezone TEXT DEFAULT 'UTC'")
        except Exception:
            pass  # Column already exists
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS calendar_tokens (
                user_id TEXT PRIMARY KEY,
                token TEXT NOT NULL,
                refresh_token TEXT,
                token_uri TEXT,
                client_id TEXT,
                client_secret TEXT,
                scopes TEXT,
                expiry TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_turn ON conversations(user_id, turn_order)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_timestamp ON conversations(timestamp)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_period ON summaries(user_id, period, period_start)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_summaries_created_at ON summaries(created_at)")
        await conn.commit()


async def seed_default_users():
    """Idempotently seed the default admin user. Called once at startup after init_db."""
    import bcrypt

    default_users = [
        ("admin", "lels1234"),
    ]
    async with aiosqlite.connect(DB_PATH) as conn:
        for username, password in default_users:
            cursor = await conn.execute("SELECT id FROM users WHERE username = ?", (username,))
            if await cursor.fetchone():
                continue
            password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            await conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, password_hash),
            )
        await conn.commit()


async def get_user_by_username(username: str):
    """Return (id, username, password_hash) or None."""
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute("SELECT id, username, password_hash FROM users WHERE username = ?", (username,))
        row = await cursor.fetchone()
    return row


async def create_user(username: str, password: str) -> int:
    """Create a new user with hashed password. Returns the new user id, or 0 if username exists."""
    import bcrypt

    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute("SELECT id FROM users WHERE username = ?", (username,))
        if await cursor.fetchone():
            return 0
        cursor = await conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, password_hash),
        )
        await conn.commit()
        return cursor.lastrowid or 0


async def get_user_timezone(user_id: str) -> str:
    """Return the user's timezone setting. Defaults to 'UTC'."""
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute(
            "SELECT timezone FROM users WHERE username = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
    if row and row[0]:
        return row[0]
    return "UTC"


async def update_user_timezone(user_id: str, timezone: str):
    """Update the user's timezone setting."""
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "UPDATE users SET timezone = ? WHERE username = ?",
            (timezone, user_id),
        )
        await conn.commit()


async def save_turn(user_id: str, role: str, content: str | None, tool_calls: list | None, tool_call_id: str | None, turn_order: int):
    """Save a single turn with explicit turn_order. Used for testing and migrations."""
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


# --- Calendar token storage (per-user) ---

async def save_calendar_token(user_id: str, token_data: dict):
    """Save or update a user's Google Calendar OAuth token.

    token_data: dict with keys token, refresh_token, token_uri, client_id, client_secret, scopes
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            """INSERT INTO calendar_tokens (user_id, token, refresh_token, token_uri, client_id, client_secret, scopes, expiry, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(user_id) DO UPDATE SET
                token = excluded.token,
                refresh_token = excluded.refresh_token,
                token_uri = excluded.token_uri,
                client_id = excluded.client_id,
                client_secret = excluded.client_secret,
                scopes = excluded.scopes,
                expiry = excluded.expiry,
                updated_at = datetime('now')""",
            (
                user_id,
                token_data.get("token", ""),
                token_data.get("refresh_token"),
                token_data.get("token_uri"),
                token_data.get("client_id"),
                token_data.get("client_secret"),
                json.dumps(token_data.get("scopes", [])),
                token_data.get("expiry"),
            ),
        )
        await conn.commit()


async def get_calendar_token(user_id: str) -> dict | None:
    """Get a user's Google Calendar OAuth token data. Returns dict or None."""
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute(
            "SELECT token, refresh_token, token_uri, client_id, client_secret, scopes, expiry FROM calendar_tokens WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
    if not row:
        return None
    scopes = json.loads(row[5]) if row[5] else []
    return {
        "token": row[0],
        "refresh_token": row[1],
        "token_uri": row[2],
        "client_id": row[3],
        "client_secret": row[4],
        "scopes": scopes,
        "expiry": row[6],
    }


async def delete_calendar_token(user_id: str):
    """Delete a user's Google Calendar OAuth token."""
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("DELETE FROM calendar_tokens WHERE user_id = ?", (user_id,))
        await conn.commit()


async def has_calendar_token(user_id: str) -> bool:
    """Check if a user has a stored calendar token."""
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute(
            "SELECT 1 FROM calendar_tokens WHERE user_id = ?",
            (user_id,),
        )
        return await cursor.fetchone() is not None


async def migrate_global_token_file():
    """Migration: move existing global .calendar_token.json to admin user's row."""
    import pathlib
    token_path = pathlib.Path(__file__).parent / ".calendar_token.json"
    if not token_path.exists():
        return False
    try:
        data = json.loads(token_path.read_text())
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute("SELECT id FROM users WHERE username = ?", ("admin",))
            row = await cursor.fetchone()
            if row:
                user_id = str(row[0])
                scopes = data.get("scopes", [])
                await conn.execute(
                    """INSERT OR IGNORE INTO calendar_tokens (user_id, token, refresh_token, token_uri, client_id, client_secret, scopes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, NULL)""",
                    (
                        user_id,
                        data.get("token", ""),
                        data.get("refresh_token"),
                        data.get("token_uri"),
                        data.get("client_id"),
                        data.get("client_secret"),
                        json.dumps(scopes),
                    ),
                )
                await conn.commit()
        token_path.unlink(missing_ok=True)
        return True
    except Exception:
        return False


async def get_pending_summaries(user_id: str) -> list[tuple[str, str, str]]:
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
