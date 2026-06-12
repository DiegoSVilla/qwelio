# Qwelio — Agent Instructions

## Architecture
- Python backend (FastAPI) on port 8000: LLM chat + Google Calendar API
- Node frontend (Express) on port 3000: static dashboard + chat UI
- Frontend calls backend at `http://localhost:8000/api/*`

## Directories
- `backend/` — FastAPI app: `main.py`, `llm.py`, `calendar.py`
- `frontend/` — Express server + `public/` (HTML, CSS)

## Commands
- `npm run dev` — starts both backend (uvicorn) and frontend (nodemon)
- `npm run dev:python` — FastAPI only
- `npm run dev:node` — Express only
- `npm run install:all` — install frontend deps
- Backend deps: `cd backend && uv sync`
- Frontend deps: `cd frontend && npm install`

## LLM Integration
- OpenAI-compatible client, endpoint + key in `.env`
- `QWEN_API_URL`, `QWEN_API_KEY`, `MODEL_NAME`
- See `backend/llm.py` for client setup

## Google Calendar
- OAuth flow: navigate to `/api/calendar/auth`, callback at `/api/calendar/callback`
- OAuth credentials in `.env` (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`)
- Tokens stored locally, never committed

## Conventions
- Never commit `.env` or `.venv/` or `node_modules/`
- Python: ruff for lint
- Always test API routes before touching frontend UI
- Branch workflow: code → review → commit
