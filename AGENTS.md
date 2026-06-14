# Qwelio — Agent Instructions

## Product Vision
Qwelio is an AI-powered calendar assistant. The LLM agent is **time-aware** and **highly contextualized** with the user's Google Calendar agenda and past conversation history. It understands natural language requests like "schedule a meeting with Ana next Tuesday at 3pm" or "what do I have tomorrow?" and acts on them via calendar tool calls.

## Architecture
- **Backend** (FastAPI, port 8000): LLM chat, Google Calendar API, authentication, tool execution
- **Frontend** (Express, port 3000): Static dashboard with week view, today's events, chat panel
- Frontend calls backend at `http://localhost:8000/api/*`
- Single-user for now (hardcoded login: `admin` / `lels1234`)

## Directories
- `backend/` — FastAPI app: `main.py`, `llm.py`, `gcalendar.py`
- `frontend/` — Express server + `public/` (HTML, CSS, JS)
- `test/` — integration tests

## Commands
- `npm run dev` — starts both backend (uvicorn) and frontend (nodemon)
- `npm run dev:python` — FastAPI only
- `npm run dev:node` — Express only
- `npm run install:all` — installs frontend + backend deps
- `npm run test` — runs all tests (backend + frontend + integration)
- `npm run test:backend` — pytest only
- `npm run test:frontend` — frontend server tests
- `npm run test:integration` — frontend → backend communication
- `npm run lint:python` — ruff check
- Backend deps: `cd backend && uv sync --all-extras`

## LLM Integration
- OpenAI-compatible client, endpoint + key in `.env`
- `QWEN_API_URL`, `QWEN_API_KEY`, `MODEL_NAME`
- See `backend/llm.py` for client setup
- Lazy-init client — no import-time dependency on env vars
- Current model: `google/gemma-4-12B-it-qat-w4a16-ct`
- Temperature: 0.6, timeout: 30s, max retries: 2

## Google Calendar
- OAuth flow: navigate to `/api/calendar/auth`, callback at `/api/calendar/callback`
- OAuth credentials in `.env` (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`)
- Tokens stored in `backend/.calendar_token.json` (gitignored, chmod 0600)
- `NotAuthenticated` exception — caught at endpoint level to return `{"auth_required": True, "auth_url": ...}` instead of 401, so unauthenticated clients get a friendly redirect hint
- **Read/write** (`calendar.events` scope) — create, edit, delete supported

## Agent Flow (Tool Call Loop)

The agent operates as a **retrieval-augmented chat loop** with calendar context:

```
User message
    ↓
Ingest current time + timezone
    ↓
Fetch relevant calendar events (today, week, or filtered by user query)
    ↓
Build system prompt with:
  - Current datetime (UTC + user timezone)
  - Today's agenda (formatted events)
  - Last 7 days of events (for context)
  - Recent conversation history (last N turns)
  - Available tools list (create, edit, delete, list, filter)
    ↓
Send to LLM with function/tool calling enabled
    ↓
If LLM requests tool_call:
  → Execute tool (e.g., create_event, list_events)
  → Inject tool result as "tool_result" message
  → Re-send full conversation + tool result to LLM
  → Repeat until LLM returns text response (no more tool calls)
    ↓
Return final response to user
    ↓
Persist conversation turn (user msg + assistant response + tool calls)
```

### Dynamic Variables (refreshed per turn)
| Variable | Source | Refresh |
|----------|--------|---------|
| `current_time` | `datetime.now(timezone.utc)` | Every turn |
| `user_timezone` | Config / `.env` | Session start |
| `today_events` | `get_today_events(service)` | Every turn |
| `week_events` | `list_events(service, days=7)` | Every turn |
| `conversation_history` | In-memory / DB | Appended each turn |
| `available_tools` | Hardcoded tool registry | Static |

### Tool Registry (planned)
| Tool | Description | Backend Route |
|------|-------------|---------------|
| `create_event` | Create a calendar event | `POST /api/calendar/events` |
| `edit_event` | Update an existing event | `PATCH /api/calendar/events/{id}` |
| `delete_event` | Remove an event | `DELETE /api/calendar/events/{id}` |
| `list_events` | List events by date range | `GET /api/calendar/events?start=&end=` |
| `filter_events` | Filter by keyword, location, etc. | `POST /api/calendar/filter` |
| `get_today_events` | Today's events | `GET /api/calendar/today` (exists) |
| `get_week_events` | Next 7 days | `GET /api/calendar/week` (exists) |

### Conversation Context
- System prompt is rebuilt each turn with fresh calendar data
- Last 20 conversation turns sent to LLM (configurable via `MAX_CONTEXT_TURNS`)
- Tool call results are injected as `tool_result` messages in the conversation
- If context exceeds model's max tokens, oldest turns are dropped

## Authentication
- Hardcoded login: username `admin`, password `lels1234`
- Session-based (cookie or JWT token)
- All `/api/*` routes require authentication except `/api/calendar/auth` and `/api/calendar/callback`
- Login endpoint: `POST /api/auth/login` → returns session cookie

## Conventions
- Never commit `.env`, `.venv/`, `node_modules/`, `.calendar_token.json`
- Python: ruff for lint, pytest for tests
- Async endpoints use `await` — never block event loop
- XSS-safe: use `textContent` / `createElement`, never `innerHTML` with data
- Branch workflow: code → review → commit
- Always test API routes before touching frontend UI
- E2E test credentials in `.env` (`E2E_TEST_GOOGLE_ACCOUNT`, `E2E_TEST_GOOGLE_PASSWORD`) — dedicated test account, not a real user account

## Roadmap

| # | Feature | Issue |
|---|---------|-------|
| 1 | User authentication (login/logout/session) | [#1](https://github.com/DiegoSVilla/qwelio/issues/1) ✅ |
| 2 | Calendar write operations (create/edit/delete) | [#2](https://github.com/DiegoSVilla/qwelio/issues/2) ✅ |
| 3 | Agentic tool call loop with function calling | [#3](https://github.com/DiegoSVilla/qwelio/issues/3) ✅ |
| 4 | Dynamic system prompt with calendar context injection | [#4](https://github.com/DiegoSVilla/qwelio/issues/4) ✅ |
| 5 | Conversation history persistence | [#5](https://github.com/DiegoSVilla/qwelio/issues/5) ✅ |
| 6 | Configurable inference settings (max context, model) | [#6](https://github.com/DiegoSVilla/qwelio/issues/6) |
| 7 | Calendar filtering (custom date ranges, keyword, location) | [#7](https://github.com/DiegoSVilla/qwelio/issues/7) |
| 8 | Time-aware system prompt (timezone, current time) | [#8](https://github.com/DiegoSVilla/qwelio/issues/8) ✅ |
