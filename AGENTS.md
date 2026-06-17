# Qwelio — Agent Instructions

## Product Vision
Qwelio is an AI-powered calendar assistant. The LLM agent is **time-aware** and **highly contextualized** with the user's Google Calendar agenda and past conversation history. It understands natural language requests like "schedule a meeting with Ana next Tuesday at 3pm" or "what do I have tomorrow?" and acts on them via calendar tool calls.

## Architecture
- **Backend** (FastAPI, port 8000): LLM chat, Google Calendar API, authentication, tool execution
- **Frontend** (Express, port 3000): Static dashboard + API proxy to backend. Only port 3000 exposed.
- Frontend uses relative `/api/*` paths; Express proxies to backend, converting cookies for cross-port compatibility
- Single-user for now (seeded at startup: `admin` / `lels1234`, stored in SQLite with bcrypt)

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
- Configurable via `.env`: `LLM_TEMPERATURE` (0.0–2.0, default 0.6), `LLM_TIMEOUT` (1–300s, default 30), `LLM_MAX_RETRIES` (>=0, default 2), `MAX_CONTEXT_TURNS` (1–100, default 20), `MAX_TOOL_ITERATIONS` (1–20, default 5)
- Settings centralized in `backend/settings.py` with range validation, exposed via `GET /api/settings`

## Google Calendar
- OAuth flow: navigate to `/api/calendar/auth`, callback at `/api/calendar/callback`
- OAuth credentials in `.env` (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`)
- `GOOGLE_REDIRECT_URI` must match the public-facing URL (e.g., `http://localhost:3000/api/calendar/callback`)
- Tokens stored in `backend/.calendar_token.json` (gitignored, chmod 0600)
- `NotAuthenticated` exception — caught at endpoint level to return `{"auth_required": True, "auth_url": ...}` instead of 401, so unauthenticated clients get a friendly redirect hint
- **Read/write** (`calendar.events` scope) — create, edit, delete supported
- **PKCE flow**: `google-auth-oauthlib` enforces PKCE by default. The `code_verifier` is generated inside `flow.authorization_url()` and must be captured, stored in the user session, and passed to `auth_flow()` on callback.
  - `calendar_auth` endpoint: calls `get_service(state=state)` → catches `NotAuthenticated` → stores `code_verifier` in `request.session["oauth_code_verifier"]`
  - `calendar_callback` endpoint: retrieves `code_verifier` from session, constructs callback URL from `GOOGLE_REDIRECT_URI` + query string, passes both to `auth_flow(callback_url, code_verifier)`

## Debug Logging Map

All debug logs are permanent, tagged `QW-*`, tracing the full request lifecycle.

### Proxy — `frontend/server.js`
| Code | Purpose |
|------|---------|
| `QW-P001` | Proxy request start: method, URL, backend target |
| `QW-P002` | Backend response received: status code |
| `QW-P003` | Set-Cookie forwarded: cookie names |
| `QW-P005` | Gateway timeout or bad gateway |
| `QW-P006` | Backend connection dropped after headers sent |

### Frontend JS — `frontend/public/app.js`
| Code | Purpose |
|------|---------|
| `QW-F001` | checkAuth: fetching /api/auth/me |
| `QW-F002` | checkAuth: response status |
| `QW-F003` | checkAuth: redirecting to /login |
| `QW-F004` | checkAuth: auth OK, showing app |
| `QW-F010` | handleAuthLoss: clearing intervals, redirecting |
| `QW-F020` | loadToday: start |
| `QW-F021` | loadToday: fetching /api/calendar/today |
| `QW-F022` | loadToday: response status |
| `QW-F023` | loadToday: 401, handleAuthLoss |
| `QW-F024` | loadToday: auth_required, showing Connect |
| `QW-F025` | Connect button clicked |
| `QW-F026` | Connect: auth response status |
| `QW-F027` | Connect: navigating to auth_url |
| `QW-F028` | Connect: error |
| `QW-F029` | loadToday: response not ok |
| `QW-F030` | loadToday: connected, event count |
| `QW-F031` | loadToday: exception |
| `QW-F040` | loadWeek: start |
| `QW-F041` | loadWeek: fetching /api/calendar/week |
| `QW-F042` | loadWeek: response status |
| `QW-F043` | loadWeek: 401, handleAuthLoss |
| `QW-F044` | loadWeek: auth_required |
| `QW-F045` | loadWeek: response not ok |
| `QW-F046` | loadWeek: event count |
| `QW-F047` | loadWeek: exception |
| `QW-F050` | Chat submit: message preview |
| `QW-F051` | Chat: sending N messages to /api/chat |
| `QW-F052` | Chat: response status |
| `QW-F053` | Chat: 401, handleAuthLoss |
| `QW-F054` | Chat: error response |
| `QW-F055` | Chat: success, response length |
| `QW-F056` | Chat: exception |
| `QW-F057` | Chat: finally, resetting loading |

### Backend — `backend/main.py`
| Code | Purpose |
|------|---------|
| `QW-B001` | api_chat: start, user, message count |
| `QW-B002` | api_chat: fetching history |
| `QW-B003` | api_chat: history loaded, turn count |
| `QW-B004` | api_chat: fetching calendar service |
| `QW-B005` | api_chat: fetching today events |
| `QW-B006` | api_chat: today event count |
| `QW-B007` | api_chat: fetching week events |
| `QW-B008` | api_chat: week event count |
| `QW-B009` | api_chat: calendar unavailable (error) |
| `QW-B010` | api_chat: building system prompt |
| `QW-B011` | api_chat: system prompt built, length |
| `QW-B012` | api_chat: sending messages to LLM |
| `QW-B013` | api_chat: LLM response received |
| `QW-B014` | api_chat: saving turns to history |
| `QW-B015` | api_chat: turns saved, returning |
| `QW-B016` | api_chat: LLMError |
| `QW-B020` | api_login: attempt |
| `QW-B021` | api_login: rate limited |
| `QW-B022` | api_login: invalid credentials |
| `QW-B023` | api_login: success |
| `QW-B024` | api_logout: start |
| `QW-B025` | api_logout: session cleared |
| `QW-B026` | api_me: user |
| `QW-B030` | calendar_today: start |
| `QW-B031` | calendar_today: success, event count |
| `QW-B032` | calendar_today: NotAuthenticated |
| `QW-B033` | calendar_week: start |
| `QW-B034` | calendar_week: success, event count |
| `QW-B035` | calendar_week: NotAuthenticated |
| `QW-B036` | calendar_auth: start |
| `QW-B037` | calendar_auth: already authenticated |
| `QW-B038` | calendar_auth: generating OAuth state |
| `QW-B039` | calendar_auth: oauth_state stored |
| `QW-B040` | calendar_auth: code_verifier stored |
| `QW-B041` | calendar_callback: start |
| `QW-B042` | calendar_callback: session keys, state comparison |
| `QW-B043` | calendar_callback: STATE MISMATCH |
| `QW-B044` | calendar_callback: state valid, cleaning session |
| `QW-B045` | calendar_callback: callback_url, code_verifier |
| `QW-B046` | calendar_callback: auth_flow succeeded |
| `QW-B047` | calendar_callback: auth_flow FAILED |

### LLM — `backend/llm.py`
| Code | Purpose |
|------|---------|
| `QW-L001` | chat: start, model, message count |
| `QW-L002` | chat: calling LLM API |
| `QW-L003` | chat: response received |
| `QW-L004` | chat: success, content length |
| `QW-L005` | chat: APIConnectionError |
| `QW-L006` | chat: RateLimitError |
| `QW-L007` | chat: APIStatusError |
| `QW-L010` | chat_with_tools: start, model, messages, tools |
| `QW-L011` | chat_with_tools: iteration start |
| `QW-L012` | chat_with_tools: calling LLM API |
| `QW-L013` | chat_with_tools: LLM response received |
| `QW-L014` | chat_with_tools: APIConnectionError |
| `QW-L015` | chat_with_tools: RateLimitError |
| `QW-L016` | chat_with_tools: APIStatusError |
| `QW-L017` | chat_with_tools: empty response |
| `QW-L018` | chat_with_tools: tool_calls detected |
| `QW-L019` | chat_with_tools: executing tool |
| `QW-L020` | chat_with_tools: tool INVALID JSON |
| `QW-L021` | chat_with_tools: tool success |
| `QW-L022` | chat_with_tools: tool NOT FOUND |
| `QW-L023` | chat_with_tools: tool LLMError |
| `QW-L024` | chat_with_tools: tool EXCEPTION |
| `QW-L025` | chat_with_tools: iteration complete |
| `QW-L026` | chat_with_tools: final text response |
| `QW-L027` | chat_with_tools: EXCEEDED max iterations |

### Google Calendar — `backend/gcalendar.py`
| Code | Purpose |
|------|---------|
| `QW-G001` | _save_token: saving |
| `QW-G002` | _save_token: saved |
| `QW-G003` | _load_credentials: checking token file |
| `QW-G004` | _load_credentials: token valid |
| `QW-G005` | _load_credentials: refreshing expired token |
| `QW-G006` | _load_credentials: token refreshed |
| `QW-G007` | _load_credentials: no refresh token |
| `QW-G008` | _load_credentials: no token file |
| `QW-G010` | get_service: valid credentials |
| `QW-G011` | get_service: missing OAuth env vars |
| `QW-G012` | get_service: building OAuth flow |
| `QW-G013` | get_service: code_verifier present |
| `QW-G020` | auth_flow: start |
| `QW-G021` | auth_flow: code_verifier present |
| `QW-G022` | auth_flow: fetching token |
| `QW-G023` | auth_flow: token fetched |
| `QW-G024` | auth_flow: building service |
| `QW-G030` | _fetch_events: time range |
| `QW-G031` | _fetch_events: raw event count |
| `QW-G032` | _fetch_events: formatted event count |
| `QW-G040` | list_events: days, range |
| `QW-G050` | get_today_events: range |
| `QW-G060` | create_event: summary, start, end |
| `QW-G061` | create_event: checking duplicates |
| `QW-G062` | create_event: DUPLICATE found |
| `QW-G063` | create_event: inserting |
| `QW-G064` | create_event: success |
| `QW-G070` | edit_event: event_id |
| `QW-G071` | edit_event: fetched event |
| `QW-G072` | edit_event: NOT FOUND |
| `QW-G073` | edit_event: updating |
| `QW-G074` | edit_event: success |
| `QW-G080` | delete_event: event_id |
| `QW-G081` | delete_event: success |
| `QW-G082` | delete_event: NOT FOUND |

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
- Users stored in SQLite with bcrypt-hashed passwords, seeded at startup (`admin` / `lels1234`)
- Session-based (signed cookies)
- All `/api/*` routes require authentication except `/api/calendar/auth` and `/api/calendar/callback`
- Login endpoint: `POST /api/auth/login` → returns session cookie
- IP-based rate limiting (5 attempts/60s) with `X-Forwarded-For` support

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
| 6 | Configurable inference settings (max context, model) | [#6](https://github.com/DiegoSVilla/qwelio/issues/6) ✅ |
| 7 | Calendar filtering (custom date ranges, keyword, location) | [#7](https://github.com/DiegoSVilla/qwelio/issues/7) ✅ |
| 8 | Time-aware system prompt (timezone, current time) | [#8](https://github.com/DiegoSVilla/qwelio/issues/8) ✅ |
| 26 | UX onboarding (welcome, suggestion chips, empty states) | [#26](https://github.com/DiegoSVilla/qwelio/issues/26) ✅ |
| 27 | Users migrated to SQLite with bcrypt hashing | [#27](https://github.com/DiegoSVilla/qwelio/issues/27) ✅ |
