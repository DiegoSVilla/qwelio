# Issue #5: Conversation History Persistence

## Dependencies
- **Requires #1 (Authentication)** — history is scoped to `user_id`
- **Requires #3 (Tool call loop)** — tool calls and results are stored as part of conversation turns

## Functional Requirements
- Conversation history persists across page reloads and browser sessions
- Each conversation turn stores: user message, assistant response, tool calls, timestamps
- History is scoped to the authenticated user
- Configurable retention: last N turns sent to LLM (default: 20)
- Admin can clear conversation history

## Current State
- `chatHistory` is an in-memory array in `app.js` — lost on reload
- No backend storage for conversations
- No user-scoped history (no auth yet — depends on #1)

## Technical Implementation

### New Dependencies
- `aiosqlite` — add to `backend/pyproject.toml` `[project.dependencies]`

### Storage Backend
Use **aiosqlite** (async-safe wrapper around SQLite) to avoid blocking the event loop:
```python
# backend/storage.py
import aiosqlite
import json
from pathlib import Path

DB_PATH = Path(__file__).parent / "conversations.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
                content TEXT,
                tool_calls TEXT,  -- JSON array of tool call objects, or null
                tool_call_id TEXT,  -- for tool results, or null
                timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                turn_order INTEGER NOT NULL
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_turn ON conversations(user_id, turn_order)")
        await conn.commit()
```

### CRUD Operations (all async)
```python
async def save_turn(user_id: str, role: str, content: str, tool_calls: list | None, tool_call_id: str | None, turn_order: int):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT INTO conversations (user_id, role, content, tool_calls, tool_call_id, turn_order) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, role, content, json.dumps(tool_calls), tool_call_id, turn_order),
        )
        await conn.commit()

async def save_turns(turns: list[tuple]) -> None:
    """Batch insert multiple turns in a single transaction. More efficient than
    calling save_turn repeatedly in a loop (avoids N separate connections)."""
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.executemany(
            "INSERT INTO conversations (user_id, role, content, tool_calls, tool_call_id, turn_order) VALUES (?, ?, ?, ?, ?, ?)",
            turns,
        )
        await conn.commit()

async def get_history(user_id: str, limit: int = 20) -> list[dict]:
    """Get last N conversation turns for LLM context. Each turn = user msg + assistant response.
    Queries user/assistant rows only (excludes tool calls/results from count),
    then multiplies limit by 2 to get N complete turns.

    Note: Tool calls/results are stored in DB (saved by #5 endpoint) but excluded from
    this query. They are available via `tool_calls`/`tool_call_id` columns if needed
    for full trace reconstruction.
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute(
            "SELECT role, content, tool_calls, tool_call_id, turn_order FROM conversations WHERE user_id = ? AND role IN ('user', 'assistant') ORDER BY turn_order DESC LIMIT ?",
            (user_id, limit * 2),
        )
        rows = await cursor.fetchall()
    return [
        {
            "role": r[0], "content": r[1],
            "tool_calls": json.loads(r[2]) if r[2] else None,
            "tool_call_id": r[3],
            "turn_order": r[4],
        }
        for r in reversed(rows)
    ]

async def clear_history(user_id: str):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
        await conn.commit()

async def cleanup_old_history(retention_days: int = 30):
    """Delete conversations older than retention_days. Called on startup and periodically."""
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("DELETE FROM conversations WHERE timestamp < datetime('now', ?)",
                           (f"-{retention_days} days",))
        await conn.commit()
```

### Modified Chat Endpoint (`backend/main.py`)
```python
@app.post("/api/chat")
async def api_chat(req: ChatRequest, user: User = Depends(get_current_user)):
    try:
        # Load history from DB
        history = await get_history(user.id, limit=MAX_CONTEXT_TURNS)
        messages = [{"role": "system", "content": build_system_prompt(...)}] + history + req.messages

        # Run tool loop — returns (content, tool_trace)
        content, tool_trace = await chat_with_tools(messages)

        # Persist new turns (including tool calls and results)
        turn_order = max([h.get("turn_order", 0) for h in history], default=0) + 1
        for msg in req.messages:
            await save_turn(user.id, msg.role, msg.content, None, None, turn_order)
            turn_order += 1
        # Persist tool calls and results from the trace
        for trace_msg in tool_trace:
            await save_turn(
                user.id,
                trace_msg["role"],
                trace_msg.get("content"),
                trace_msg.get("tool_calls"),
                trace_msg.get("tool_call_id"),
                turn_order,
            )
            turn_order += 1
        await save_turn(user.id, "assistant", content, None, None, turn_order)

        return {"content": content}
    except NotAuthenticated as e:
        return {"auth_required": True, "auth_url": e.auth_url}
    except LLMError as e:
        return {"error": str(e)}

@app.get("/api/conversations")
async def get_conversations(limit: int = 50, user: User = Depends(get_current_user)):
    """Get conversation history for rendering in the frontend chat panel."""
    history = await get_history(user.id, limit=limit)
    return {"messages": history}

@app.delete("/api/conversations")
async def clear_conversations(user: User = Depends(get_current_user)):
    await clear_history(user.id)
    return {"cleared": True}
```

### Startup Cleanup
Use FastAPI's `lifespan` event to run cleanup on startup:
```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: init DB and clean old conversations
    await init_db()
    retention = int(os.getenv("HISTORY_RETENTION_DAYS", "30"))
    await cleanup_old_history(retention)
    yield
    # Shutdown: nothing needed

app = FastAPI(title="Qwelio", lifespan=lifespan)
```

### Frontend
- On page load, fetch history: `GET /api/conversations?limit=50` → render in chat panel
- Remove in-memory `chatHistory` array — rely on server-side storage
- Add "Clear history" button

## Acceptance Criteria
- [ ] Conversation history persists across page reload
- [ ] History is scoped to user_id
- [ ] Last 20 turns sent to LLM (configurable)
- [ ] Tool calls and results are stored in history
- [ ] All DB operations are async (aiosqlite, no event loop blocking)
- [ ] `turn_order` is included in SELECT and returned to caller
- [ ] `DELETE /api/conversations` clears user's history
- [ ] Auto-cleanup runs on startup via lifespan event (deletes older than `HISTORY_RETENTION_DAYS`)
- [ ] Frontend renders full history on page load
- [ ] Tests: save, load, limit, clear, cleanup, concurrent writes, async safety
