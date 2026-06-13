# Issue #5: Conversation History Persistence

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

### Storage Backend
Use SQLite for simplicity (single-user, low volume):
```python
# backend/storage.py
import sqlite3
import json
from pathlib import Path

DB_PATH = Path(__file__).parent / "conversations.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user_turn ON conversations(user_id, turn_order)")
    conn.commit()
    return conn
```

### CRUD Operations
```python
def save_turn(user_id: str, role: str, content: str, tool_calls: list | None, tool_call_id: str | None, turn_order: int):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO conversations (user_id, role, content, tool_calls, tool_call_id, turn_order) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, role, content, json.dumps(tool_calls), tool_call_id, turn_order),
    )
    conn.commit()
    conn.close()

def get_history(user_id: str, limit: int = 20) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT role, content, tool_calls, tool_call_id, timestamp FROM conversations WHERE user_id = ? ORDER BY turn_order DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1], "tool_calls": json.loads(r[2]) if r[2] else None, "tool_call_id": r[3]} for r in reversed(rows)]

def clear_history(user_id: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
```

### Modified Chat Endpoint (`backend/main.py`)
```python
@app.post("/api/chat")
async def api_chat(req: ChatRequest, user: User = Depends(get_current_user)):
    # Load history from DB
    history = get_history(user.id, limit=MAX_CONTEXT_TURNS)
    messages = [{"role": "system", "content": build_system_prompt(...)}] + history + req.messages

    # Run tool loop
    content = await chat_with_tools(messages)

    # Persist new turns
    turn_order = max([h.get("turn_order", 0) for h in history], default=0) + 1
    for msg in req.messages:
        save_turn(user.id, msg.role, msg.content, None, None, turn_order)
        turn_order += 1
    save_turn(user.id, "assistant", content, None, None, turn_order)

    return {"content": content}

@app.delete("/api/conversations")
async def clear_conversations(user: User = Depends(get_current_user)):
    clear_history(user.id)
    return {"cleared": True}
```

### Frontend
- On page load, fetch history: `GET /api/conversations?limit=50` → render in chat panel
- Remove in-memory `chatHistory` array — rely on server-side storage
- Add "Clear history" button

### Cleanup
- Auto-delete conversations older than 30 days (daily cron or on-startup job)
- Configurable via `HISTORY_RETENTION_DAYS` env var

## Acceptance Criteria
- [ ] Conversation history persists across page reload
- [ ] History is scoped to user_id
- [ ] Last 20 turns sent to LLM (configurable)
- [ ] Tool calls and results are stored in history
- [ ] `DELETE /api/conversations` clears user's history
- [ ] Auto-cleanup of conversations older than 30 days
- [ ] Frontend renders full history on page load
- [ ] Tests: save, load, limit, clear, cleanup, concurrent writes
