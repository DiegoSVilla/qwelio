# Qwelio — AI Calendar Assistant

An AI-powered calendar assistant that understands natural language and acts on your Google Calendar. Ask "what do I have tomorrow?" or "schedule a meeting with Ana next Tuesday at 3pm" and let the LLM handle it.

## Architecture

- **Backend**: Python FastAPI (port 8000) — LLM chat, Google Calendar API, authentication
- **Frontend**: Node Express (port 3000) — static dashboard with week view, today's events, chat panel
- **LLM**: OpenAI-compatible client (Qwen API) with lazy initialization
- **Calendar**: Google Calendar OAuth2 with read/write scope (`calendar.events`)

## Requirements

- **Python** 3.12+
- **Node.js** 18+
- **uv** (Python package manager): `pip install uv`
- **Google Cloud Project** with Calendar API enabled (for OAuth)
- **OpenAI-compatible API** endpoint (e.g., Qwen API)

## Quick Start

```bash
git clone git@github.com:DiegoSVilla/qwelio.git
cd qwelio

# Install dependencies
npm run install:all

# Configure .env (create manually)
# Required: QWEN_API_URL, QWEN_API_KEY, MODEL_NAME
# Required for calendar features: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI

# Run both servers
npm run dev
```

Open http://localhost:3000 in your browser.

## Commands

| Command | Description |
|---------|-------------|
| `npm run dev` | Start both backend and frontend |
| `npm run dev:python` | FastAPI only (port 8000) |
| `npm run dev:node` | Express only (port 3000) |
| `npm run install:all` | Install frontend + backend deps |
| `npm run test` | Run all tests (backend, frontend, integration) |
| `npm run test:backend` | pytest only |
| `npm run test:frontend` | Frontend server tests |
| `npm run test:integration` | Frontend → backend communication |
| `npm run lint:python` | ruff check |

## Configuration

Create a `.env` file in the project root:

```env
# LLM (required)
QWEN_API_URL=https://your-api-endpoint/v1
QWEN_API_KEY=your-api-key
MODEL_NAME=google/gemma-4-12B-it-qat-w4a16-ct

# Google Calendar (required for calendar features)
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/api/calendar/callback

# Authentication (required — random default invalidates sessions on restart)
SESSION_SECRET=your-session-secret

# Inference settings (optional, defaults shown)
LLM_TEMPERATURE=0.6
LLM_TIMEOUT=30.0
LLM_MAX_RETRIES=2
MAX_CONTEXT_TURNS=20
MAX_TOOL_ITERATIONS=5
USER_TIMEZONE=America/New_York
```

## Agent Flow

The agent operates as a **retrieval-augmented chat loop**:

1. User sends a message
2. System injects current time, timezone, and relevant calendar events
3. LLM responds with natural language or requests a tool call
4. If tool called, result is injected back into conversation
5. Loop continues until LLM returns a text response
6. Conversation turn is persisted for future context

## Roadmap

| # | Feature | Issue |
|---|---------|-------|
| 1 | User authentication (login/logout/session) | [#1](https://github.com/DiegoSVilla/qwelio/issues/1) ✅ |
| 2 | Calendar write operations (create/edit/delete) | [#2](https://github.com/DiegoSVilla/qwelio/issues/2) ✅ |
| 3 | Agentic tool call loop with function calling | [#3](https://github.com/DiegoSVilla/qwelio/issues/3) |
| 4 | Dynamic system prompt with calendar context injection | [#4](https://github.com/DiegoSVilla/qwelio/issues/4) |
| 5 | Conversation history persistence | [#5](https://github.com/DiegoSVilla/qwelio/issues/5) |
| 6 | Configurable inference settings (max context, model) | [#6](https://github.com/DiegoSVilla/qwelio/issues/6) |
| 7 | Calendar filtering (custom date ranges, keyword, location) | [#7](https://github.com/DiegoSVilla/qwelio/issues/7) |
| 8 | Time-aware system prompt (timezone, current time) | [#8](https://github.com/DiegoSVilla/qwelio/issues/8) |

## License

Private project.
