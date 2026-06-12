# Qwelio — Agent Instructions

## Architecture
- Python backend (FastAPI) on port 8000: LLM chat + Google Calendar API
- Node frontend (Express) on port 3000: static dashboard + chat UI
- Frontend calls backend at `http://localhost:8000/api/*`

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

## Google Calendar
- OAuth flow: navigate to `/api/calendar/auth`, callback at `/api/calendar/callback`
- OAuth credentials in `.env` (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`)
- Tokens stored in `backend/.calendar_token.json` (gitignored, chmod 0600)
- `NotAuthenticated` exception — don't use dual return types

## Conventions
- Never commit `.env`, `.venv/`, `node_modules/`, `.calendar_token.json`
- Python: ruff for lint, pytest for tests
- Async endpoints use `await` — never block event loop
- XSS-safe: use `textContent` / `createElement`, never `innerHTML` with data
- Branch workflow: code → review → commit
- Always test API routes before touching frontend UI
