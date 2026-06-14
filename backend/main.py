import asyncio
import os
import secrets
import hmac
from contextlib import asynccontextmanager

import aiosqlite

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, Field, field_validator
from typing import Literal
from datetime import datetime, date, timezone, timedelta

from dotenv import load_dotenv

from llm import chat_with_tools, LLMError
from gcalendar import get_service, auth_flow, list_events, get_today_events, create_event, edit_event, delete_event, _fetch_events, NotAuthenticated
from auth import User, SESSION_KEY, _rate_limiter, get_current_user, verify_password
from tools import ToolRegistry
from storage import init_db, save_turns, get_history, clear_history, cleanup_old_history, get_summaries
from storage import DB_PATH
from prompt import build_system_prompt, DEFAULT_TIMEZONE

load_dotenv()

MAX_CONTEXT_TURNS = int(os.getenv("MAX_CONTEXT_TURNS", "20"))
HISTORY_RETENTION_DAYS = int(os.getenv("HISTORY_RETENTION_DAYS", "30"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await cleanup_old_history(HISTORY_RETENTION_DAYS)
    yield
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            await conn.commit()
    except Exception:
        pass


app = FastAPI(title="Qwelio", lifespan=lifespan)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)

session_secret = os.getenv("SESSION_SECRET")
if not session_secret:
    import pathlib
    secret_file = pathlib.Path(__file__).parent / ".session_secret"
    if secret_file.exists():
        session_secret = secret_file.read_text().strip()
    else:
        session_secret = secrets.token_hex(32)
        secret_file.write_text(session_secret)
        secret_file.chmod(0o600)

app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret,
    https_only=os.getenv("HTTPS_ONLY", "false").lower() == "true",
    max_age=86400,
)


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[Message] = Field(..., max_length=50)


class LoginRequest(BaseModel):
    username: str
    password: str


class EventCreateRequest(BaseModel):
    summary: str = Field(..., min_length=1, max_length=1024)
    start: str
    end: str
    location: str | None = Field(default=None, max_length=2048)
    description: str | None = Field(default=None, max_length=5000)

    @field_validator("start", "end")
    @classmethod
    def validate_iso8601(cls, v: str) -> str:
        if "T" in v:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        else:
            date.fromisoformat(v)
        return v

    @field_validator("end")
    @classmethod
    def validate_end_after_start(cls, v: str, info) -> str:
        start = info.data.get("start")
        if start:
            start_str = start.replace("Z", "+00:00") if "T" in start else start + "T00:00:00+00:00"
            end_str = v.replace("Z", "+00:00") if "T" in v else v + "T00:00:00+00:00"
            start_dt = datetime.fromisoformat(start_str)
            end_dt = datetime.fromisoformat(end_str)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            if end_dt <= start_dt:
                raise ValueError("end must be after start")
        return v


class EventUpdateRequest(BaseModel):
    summary: str | None = Field(default=None, min_length=1, max_length=1024)
    start: str | None = None
    end: str | None = None
    location: str | None = Field(default=None, max_length=2048)
    description: str | None = Field(default=None, max_length=5000)

    @field_validator("start", "end")
    @classmethod
    def validate_iso8601(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if "T" in v:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        else:
            date.fromisoformat(v)
        return v

    @field_validator("end")
    @classmethod
    def validate_end_after_start(cls, v: str | None, info) -> str | None:
        if v is None:
            return v
        start = info.data.get("start")
        if start:
            start_str = start.replace("Z", "+00:00") if "T" in start else start + "T00:00:00+00:00"
            end_str = v.replace("Z", "+00:00") if "T" in v else v + "T00:00:00+00:00"
            start_dt = datetime.fromisoformat(start_str)
            end_dt = datetime.fromisoformat(end_str)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            if end_dt <= start_dt:
                raise ValueError("end must be after start")
        return v


class EventFilterRequest(BaseModel):
    time_min: str | None = None
    time_max: str | None = None
    days: int | None = Field(default=None, ge=1, le=365)
    keyword: str | None = Field(default=None, max_length=500)
    location: str | None = Field(default=None, max_length=500)

    @field_validator("time_min", "time_max")
    @classmethod
    def validate_iso8601(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if "T" in v:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        else:
            date.fromisoformat(v)
        return v


def _do_create(summary, start, end, location=None, description=None):
    req = EventCreateRequest(summary=summary, start=start, end=end, location=location, description=description)
    try:
        service = get_service()
    except NotAuthenticated:
        return {"error": "Calendar authentication expired. Please re-authorize."}
    return create_event(service, req.summary, req.start, req.end, req.location, req.description)


def _do_edit(event_id, summary=None, start=None, end=None, location=None, description=None):
    if not event_id:
        raise ValueError("event_id is required")
    req = EventUpdateRequest(summary=summary, start=start, end=end, location=location, description=description)
    try:
        service = get_service()
    except NotAuthenticated:
        return {"error": "Calendar authentication expired. Please re-authorize."}
    return edit_event(service, event_id, req.summary, req.start, req.end, req.location, req.description)


def _do_delete(event_id):
    if not event_id:
        raise ValueError("event_id is required")
    try:
        service = get_service()
    except NotAuthenticated:
        return {"error": "Calendar authentication expired. Please re-authorize."}
    delete_event(service, event_id)
    return {"deleted": event_id}


def _do_list(time_min=None, time_max=None, days=7):
    if days is not None and (days < 1 or days > 365):
        raise ValueError("days must be between 1 and 365")
    if time_min:
        date.fromisoformat(time_min) if "T" not in time_min else datetime.fromisoformat(time_min.replace("Z", "+00:00"))
    if time_max:
        date.fromisoformat(time_max) if "T" not in time_max else datetime.fromisoformat(time_max.replace("Z", "+00:00"))
    try:
        service = get_service()
    except NotAuthenticated:
        return {"error": "Calendar authentication expired. Please re-authorize."}
    if time_min and time_max:
        return _fetch_events(service, time_min, time_max)
    return list_events(service, days=days)


def _do_today():
    try:
        service = get_service()
    except NotAuthenticated:
        return {"error": "Calendar authentication expired. Please re-authorize."}
    return get_today_events(service)


def _do_filter(time_min=None, time_max=None, days=None, keyword=None, location=None):
    if days is not None and (days < 1 or days > 365):
        raise ValueError("days must be between 1 and 365")
    if time_min:
        date.fromisoformat(time_min) if "T" not in time_min else datetime.fromisoformat(time_min.replace("Z", "+00:00"))
    if time_max:
        date.fromisoformat(time_max) if "T" not in time_max else datetime.fromisoformat(time_max.replace("Z", "+00:00"))
    if time_min and time_max:
        min_dt = datetime.fromisoformat(time_min.replace("Z", "+00:00")) if "T" in time_min else datetime.fromisoformat(time_min + "T00:00:00+00:00")
        max_dt = datetime.fromisoformat(time_max.replace("Z", "+00:00")) if "T" in time_max else datetime.fromisoformat(time_max + "T00:00:00+00:00")
        if min_dt >= max_dt:
            raise ValueError("time_min must be before time_max")
    try:
        service = get_service()
    except NotAuthenticated:
        return {"error": "Calendar authentication expired. Please re-authorize."}

    events = _apply_filters(service, time_min, time_max, days, keyword, location)
    return {"events": events}

def _apply_filters(service, time_min=None, time_max=None, days=None, keyword=None, location=None):
    now = datetime.now(timezone.utc)
    if time_min is None or time_max is None:
        if days is not None:
            time_min = now.isoformat()
            time_max = (now + timedelta(days=days)).isoformat()
        else:
            time_min = (now - timedelta(days=30)).isoformat()
            time_max = (now + timedelta(days=30)).isoformat()

    events = _fetch_events(service, time_min, time_max)

    if keyword:
        kw = keyword.lower()
        events = [e for e in events if kw in e.get("summary", "").lower() or kw in (e.get("description") or "").lower()]
    if location:
        loc = location.lower()
        events = [e for e in events if loc in (e.get("location") or "").lower()]

    return events


def _register_tools():
    ToolRegistry.register(
        "create_event",
        "Create a new calendar event",
        {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Event title"},
                "start": {"type": "string", "description": "Start time in ISO 8601 format"},
                "end": {"type": "string", "description": "End time in ISO 8601 format"},
                "location": {"type": "string", "description": "Event location (optional)"},
                "description": {"type": "string", "description": "Event description (optional)"},
            },
            "required": ["summary", "start", "end"],
        },
        _do_create,
    )

    ToolRegistry.register(
        "edit_event",
        "Update an existing calendar event",
        {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "Event ID to update"},
                "summary": {"type": "string", "description": "New event title (optional)"},
                "start": {"type": "string", "description": "New start time in ISO 8601 (optional)"},
                "end": {"type": "string", "description": "New end time in ISO 8601 (optional)"},
                "location": {"type": "string", "description": "New location (optional)"},
                "description": {"type": "string", "description": "New description (optional)"},
            },
            "required": ["event_id"],
        },
        _do_edit,
    )

    ToolRegistry.register(
        "delete_event",
        "Delete a calendar event",
        {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "Event ID to delete"},
            },
            "required": ["event_id"],
        },
        _do_delete,
    )

    ToolRegistry.register(
        "list_events",
        "List calendar events for a date range",
        {
            "type": "object",
            "properties": {
                "time_min": {"type": "string", "description": "Start of range in ISO 8601 (optional)"},
                "time_max": {"type": "string", "description": "End of range in ISO 8601 (optional)"},
                "days": {"type": "integer", "description": "Number of days from now (default 7, used if time_min not provided)"},
            },
            "required": [],
        },
        _do_list,
    )

    ToolRegistry.register(
        "get_today_events",
        "Get today's calendar events",
        {
            "type": "object",
            "properties": {},
            "required": [],
        },
        _do_today,
    )

    ToolRegistry.register(
        "filter_events",
        "Filter calendar events by date range, keyword, or location. Use ISO 8601 format for dates (e.g., 2025-07-01T09:00:00+00:00 or 2025-07-01). You can compute dates from the current time provided in the system prompt.",
        {
            "type": "object",
            "properties": {
                "time_min": {"type": "string", "description": "Start of range in ISO 8601 (e.g., 2025-07-01T00:00:00+00:00). Optional — omit to use default range."},
                "time_max": {"type": "string", "description": "End of range in ISO 8601 (e.g., 2025-07-31T23:59:59+00:00). Optional — omit to use default range."},
                "days": {"type": "integer", "description": "Number of days from now (1-365). Use instead of time_min/time_max for relative ranges. Default: 60 days (±30)."},
                "keyword": {"type": "string", "description": "Search term matched case-insensitively in event summary and description."},
                "location": {"type": "string", "description": "Search term matched case-insensitively in event location."},
            },
            "required": [],
        },
        _do_filter,
    )


_register_tools()


@app.post("/api/auth/login")
async def api_login(request: Request, req: LoginRequest):
    if _rate_limiter.is_limited(request):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")
    if not verify_password(req.username, req.password):
        _rate_limiter.record(request)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    user = User(id=req.username, username=req.username)
    request.session[SESSION_KEY] = user.model_dump()
    return {"user": user}


@app.post("/api/auth/logout")
async def api_logout(request: Request, user: User = Depends(get_current_user)):
    request.session.clear()
    return {"message": "Logged out"}


@app.get("/api/auth/me")
async def api_me(user: User = Depends(get_current_user)):
    return {"user": user}


@app.post("/api/chat")
async def api_chat(req: ChatRequest, user: User = Depends(get_current_user)):
    try:
        history = await get_history(user.id, limit=MAX_CONTEXT_TURNS)
        clean_history = [{k: v for k, v in h.items() if k != "turn_order"} for h in history]

        # Fetch calendar context (async-safe, graceful degradation)
        today_ev = []
        week_ev = []
        calendar_available = False
        try:
            service = get_service()
            today_ev = await asyncio.to_thread(get_today_events, service)
            week_ev = await asyncio.to_thread(list_events, service, days=7)
            calendar_available = True
        except Exception:
            pass

        # Build system prompt with time + calendar context
        tool_defs = ToolRegistry.get_definitions()
        system_prompt = build_system_prompt(
            current_time_utc=datetime.now(timezone.utc),
            user_timezone=DEFAULT_TIMEZONE,
            today_events=today_ev,
            week_events=week_ev,
            tool_definitions=tool_defs,
            calendar_available=calendar_available,
        )

        messages = [{"role": "system", "content": system_prompt}] + clean_history + [m.model_dump() for m in req.messages]
        content, new_msgs = await chat_with_tools(messages, tool_defs)

        turns = [(m.role, m.content, None, None) for m in req.messages]
        for msg in new_msgs:
            turns.append((msg["role"], msg.get("content"), msg.get("tool_calls"), msg.get("tool_call_id")))
        await save_turns(user.id, turns)

        return {"content": content}
    except LLMError as e:
        return {"error": str(e)}


@app.get("/api/conversations")
async def get_conversations(limit: int = Query(default=50, ge=1, le=200), user: User = Depends(get_current_user)):
    history = await get_history(user.id, limit=limit)
    summaries = await get_summaries(user.id)
    return {
        "history": history,
        "summaries": summaries,
    }


@app.delete("/api/conversations")
async def clear_conversations(user: User = Depends(get_current_user)):
    await clear_history(user.id)
    return {"cleared": True}


@app.post("/api/conversations/summarize")
async def trigger_summarize(user: User = Depends(get_current_user)):
    from summarizer import generate_summaries
    try:
        results = await generate_summaries(user.id)
        return {"summarized": results}
    except LLMError as e:
        return {"error": str(e)}


@app.get("/api/calendar/auth")
async def calendar_auth(request: Request, user: User = Depends(get_current_user)):
    try:
        get_service()
        return {"error": "Already authenticated"}
    except NotAuthenticated as e:
        state = secrets.token_urlsafe(32)
        request.session["oauth_state"] = state
        return {"auth_url": e.auth_url, "oauth_state": state}


@app.get("/api/calendar/callback")
async def calendar_callback(request: Request, state: str = Query(...), user: User = Depends(get_current_user)):
    stored_state = request.session.get("oauth_state")
    if not stored_state or not hmac.compare_digest(stored_state, state):
        return HTMLResponse("<h1>Error</h1><p>Invalid or missing state parameter.</p>", status_code=400)
    request.session.pop("oauth_state", None)
    try:
        auth_flow(str(request.url))
        return HTMLResponse(
            "<h1>Success!</h1><p>Calendar authorized. You can close this window.</p>"
        )
    except Exception:
        return HTMLResponse("<h1>Error</h1><p>Authorization failed. Try again.</p>", status_code=500)


@app.get("/api/calendar/today")
async def calendar_today(user: User = Depends(get_current_user)):
    try:
        service = get_service()
        events = get_today_events(service)
        return {"events": events}
    except NotAuthenticated as e:
        return {"auth_required": True, "auth_url": e.auth_url}


@app.get("/api/calendar/week")
async def calendar_week(user: User = Depends(get_current_user)):
    try:
        service = get_service()
        events = list_events(service, days=7)
        return {"events": events}
    except NotAuthenticated as e:
        return {"auth_required": True, "auth_url": e.auth_url}


@app.post("/api/calendar/events")
async def create_calendar_event(resp: Response, req: EventCreateRequest, user: User = Depends(get_current_user)):
    try:
        service = get_service()
        try:
            event = create_event(
                service,
                req.summary,
                req.start,
                req.end,
                req.location,
                req.description,
            )
            resp.status_code = 201
            return {"id": event["id"], "status": event.get("status", "confirmed")}
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))
    except NotAuthenticated as e:
        return {"auth_required": True, "auth_url": e.auth_url}


@app.patch("/api/calendar/events/{event_id}")
async def edit_calendar_event(event_id: str, req: EventUpdateRequest, user: User = Depends(get_current_user)):
    try:
        service = get_service()
        try:
            updated = edit_event(
                service,
                event_id,
                req.summary,
                req.start,
                req.end,
                req.location,
                req.description,
            )
            return {"id": updated["id"]}
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
    except NotAuthenticated as e:
        return {"auth_required": True, "auth_url": e.auth_url}


@app.delete("/api/calendar/events/{event_id}")
async def delete_calendar_event(event_id: str, user: User = Depends(get_current_user)):
    try:
        service = get_service()
        try:
            delete_event(service, event_id)
            return {"deleted": event_id}
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
    except NotAuthenticated as e:
        return {"auth_required": True, "auth_url": e.auth_url}


@app.post("/api/calendar/filter")
async def filter_events(req: EventFilterRequest, user: User = Depends(get_current_user)):
    try:
        service = get_service()
    except NotAuthenticated as e:
        return {"auth_required": True, "auth_url": e.auth_url}

    events = _apply_filters(service, req.time_min, req.time_max, req.days, req.keyword, req.location)
    return {"events": events}
