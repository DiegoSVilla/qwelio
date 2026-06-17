import asyncio
import contextvars
import os
import secrets
import hmac
from contextlib import asynccontextmanager

import aiosqlite

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Literal
from datetime import datetime, date, timezone, timedelta

_current_timezone: contextvars.ContextVar[str] = contextvars.ContextVar("current_timezone", default="UTC")

from dotenv import load_dotenv

from llm import chat_with_tools, LLMError
from gcalendar import get_service, auth_flow, list_events, get_today_events, create_event, edit_event, delete_event, _fetch_events, NotAuthenticated, get_month_events, disconnect_calendar, TOKEN_PATH
from auth import User, SESSION_KEY, _rate_limiter, get_current_user, verify_password
from tools import ToolRegistry
from storage import init_db, seed_default_users, save_turns, get_history, clear_history, cleanup_old_history, get_summaries, get_user_timezone, update_user_timezone
from storage import DB_PATH
from prompt import build_system_prompt, DEFAULT_TIMEZONE
from settings import settings

load_dotenv()

HISTORY_RETENTION_DAYS = int(os.getenv("HISTORY_RETENTION_DAYS", "30"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await seed_default_users()
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
    session_secret = secrets.token_hex(32)

app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret,
    https_only=os.getenv("HTTPS_ONLY", "false").lower() == "true",
    max_age=3600,
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

    @model_validator(mode="after")
    def validate_time_range(self):
        if self.days is not None and (self.time_min is not None or self.time_max is not None):
            raise ValueError("Provide either 'days' or 'time_min'/'time_max', not both")
        if self.time_min and self.time_max:
            min_dt = datetime.fromisoformat(self.time_min.replace("Z", "+00:00")) if "T" in self.time_min else datetime.fromisoformat(self.time_min + "T00:00:00+00:00")
            max_dt = datetime.fromisoformat(self.time_max.replace("Z", "+00:00")) if "T" in self.time_max else datetime.fromisoformat(self.time_max + "T00:00:00+00:00")
            if min_dt >= max_dt:
                raise ValueError("time_min must be before time_max")
        return self


def _do_create(summary, start, end, location=None, description=None):
    req = EventCreateRequest(summary=summary, start=start, end=end, location=location, description=description)
    try:
        service = get_service()
    except NotAuthenticated:
        return {"error": "Calendar authentication expired. Please re-authorize."}
    return create_event(service, req.summary, req.start, req.end, req.location, req.description, user_tz=_current_timezone.get())


def _do_edit(event_id, summary=None, start=None, end=None, location=None, description=None):
    if not event_id:
        raise ValueError("event_id is required")
    req = EventUpdateRequest(summary=summary, start=start, end=end, location=location, description=description)
    try:
        service = get_service()
    except NotAuthenticated:
        return {"error": "Calendar authentication expired. Please re-authorize."}
    return edit_event(service, event_id, req.summary, req.start, req.end, req.location, req.description, user_tz=_current_timezone.get())


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
                "start": {"type": "string", "description": "Start time in the user's local timezone. Use 'YYYY-MM-DD' for all-day events, or 'YYYY-MM-DDTHH:MM:SS' for timed events. Do NOT include a timezone offset (no Z, no +00:00, no -03:00)."},
                "end": {"type": "string", "description": "End time in the user's local timezone. Use 'YYYY-MM-DD' for all-day events, or 'YYYY-MM-DDTHH:MM:SS' for timed events. Do NOT include a timezone offset."},
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
                "start": {"type": "string", "description": "New start time in user's local timezone. 'YYYY-MM-DD' for all-day, 'YYYY-MM-DDTHH:MM:SS' for timed. Do NOT include a timezone offset."},
                "end": {"type": "string", "description": "New end time in user's local timezone. 'YYYY-MM-DD' for all-day, 'YYYY-MM-DDTHH:MM:SS' for timed. Do NOT include a timezone offset."},
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

    ToolRegistry.register(
        "get_current_time",
        "Get the current date and time in the user's timezone. Call this tool whenever the user asks about the current time or date, or when you need to verify the exact time before answering.",
        {
            "type": "object",
            "properties": {},
            "required": [],
        },
        _do_get_time,
    )


def _do_get_time():
    from prompt import _parse_tz_offset
    tz = _current_timezone.get()
    offset_hours = _parse_tz_offset(tz)
    utc_now = datetime.now(timezone.utc)
    local_now = utc_now + timedelta(hours=offset_hours)
    month_names = ["January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December"]
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return {
        "timezone": tz,
        "utc": utc_now.strftime("%Y-%m-%d %H:%M:%S"),
        "local_time": local_now.strftime("%H:%M:%S"),
        "local_date": local_now.strftime("%Y-%m-%d"),
        "day_of_week": day_names[local_now.weekday()],
        "formatted": f"{day_names[local_now.weekday()]}, {month_names[local_now.month - 1]} {local_now.day}, {local_now.year} at {local_now.strftime('%I:%M %p')} {tz}",
    }


_register_tools()


@app.post("/api/auth/login")
async def api_login(request: Request, req: LoginRequest):
    print(f"[QW-B020] api_login: attempt for user={req.username}")
    if _rate_limiter.is_limited(request):
        print("[QW-B021] api_login: rate limited")
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")
    if not await verify_password(req.username, req.password):
        _rate_limiter.record(request)
        print("[QW-B022] api_login: invalid credentials")
        raise HTTPException(status_code=401, detail="Invalid credentials")
    user = User(id=req.username, username=req.username)
    request.session[SESSION_KEY] = user.model_dump()
    print(f"[QW-B023] api_login: success, user={user.id}")
    return {"user": user}


@app.post("/api/auth/logout")
async def api_logout(request: Request, user: User = Depends(get_current_user)):
    print(f"[QW-B024] api_logout: user={user.id}")
    request.session.clear()
    print("[QW-B025] api_logout: session cleared")
    return {"message": "Logged out"}


@app.get("/api/auth/me")
async def api_me(user: User = Depends(get_current_user)):
    print(f"[QW-B026] api_me: user={user.id}")
    tz = await get_user_timezone(user.id)
    return {"user": user, "timezone": tz}


@app.post("/api/chat")
async def api_chat(req: ChatRequest, user: User = Depends(get_current_user)):
    print(f"[QW-B001] api_chat: start, user={user.id}, messages={len(req.messages)}")
    try:
        print(f"[QW-B002] api_chat: fetching history (limit={settings.max_context_turns})")
        history = await get_history(user.id, limit=settings.max_context_turns)
        clean_history = [{k: v for k, v in h.items() if k != "turn_order"} for h in history]
        print(f"[QW-B003] api_chat: history loaded, turns={len(clean_history)}")

        # Fetch calendar context (async-safe, graceful degradation)
        today_ev = []
        week_ev = []
        calendar_available = False
        try:
            print("[QW-B004] api_chat: fetching calendar service")
            service = get_service()
            print("[QW-B005] api_chat: fetching today events")
            today_ev = await asyncio.to_thread(get_today_events, service)
            print(f"[QW-B006] api_chat: today events={len(today_ev)}")
            print("[QW-B007] api_chat: fetching week events")
            week_ev = await asyncio.to_thread(list_events, service, days=7)
            print(f"[QW-B008] api_chat: week events={len(week_ev)}")
            calendar_available = True
        except Exception as e:
            print(f"[QW-B009] api_chat: calendar unavailable: {type(e).__name__}: {e}")

        # Build system prompt with time + calendar context
        print("[QW-B010] api_chat: building system prompt")
        user_tz = await get_user_timezone(user.id)
        _current_timezone.set(user_tz)
        tool_defs = ToolRegistry.get_definitions()
        now = datetime.now(timezone.utc)
        system_prompt = build_system_prompt(
            current_time_utc=now,
            user_timezone=user_tz,
            today_events=today_ev,
            week_events=week_ev,
            tool_definitions=tool_defs,
            calendar_available=calendar_available,
        )
        print(f"[QW-B011] api_chat: system prompt built, length={len(system_prompt)}")

        # Timestamp user messages so the LLM knows when each message was sent
        def _timestamp_user_msg(content: str, ts: datetime) -> str:
            from prompt import _parse_tz_offset
            offset_hours = _parse_tz_offset(user_tz)
            local = ts + timedelta(hours=offset_hours)
            return f"[{local.strftime('%H:%M:%S %b %d, %Y')} {user_tz}] {content}"

        timestamped_history = []
        for h in clean_history:
            if h["role"] == "user":
                ts = datetime.fromisoformat(h.get("timestamp", now.isoformat())) if h.get("timestamp") else now
                timestamped_history.append({"role": "user", "content": _timestamp_user_msg(h["content"], ts)})
            else:
                timestamped_history.append(h)

        new_messages = []
        for m in req.messages:
            if m.role == "user":
                new_messages.append({"role": "user", "content": _timestamp_user_msg(m.content, now)})
            else:
                new_messages.append(m.model_dump())

        messages = [{"role": "system", "content": system_prompt}] + timestamped_history + new_messages
        print(f"[QW-B012] api_chat: sending {len(messages)} messages to LLM (system + {len(clean_history)} history + {len(req.messages)} new)")
        content, new_msgs = await chat_with_tools(messages, tool_defs)
        print(f"[QW-B013] api_chat: LLM response received, content length={len(content) if content else 0}, new_msgs={len(new_msgs)}")

        # Collect tool call names from the conversation loop
        tool_calls = []
        for msg in new_msgs:
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    tc_data = tc if isinstance(tc, dict) else tc.model_dump()
                    fn = tc_data.get("function", {})
                    tool_calls.append(fn.get("name", "unknown"))

        turns = [(m.role, m.content, None, None) for m in req.messages]
        for msg in new_msgs:
            turns.append((msg["role"], msg.get("content"), msg.get("tool_calls"), msg.get("tool_call_id")))
        print(f"[QW-B014] api_chat: saving {len(turns)} turns to history")
        await save_turns(user.id, turns)
        print("[QW-B015] api_chat: turns saved, returning response")

        return {"content": content, "tool_calls": tool_calls}
    except LLMError as e:
        print(f"[QW-B016] api_chat: LLMError: {e}")
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
    print(f"[QW-B036] calendar_auth: start, user={user.id}")
    try:
        get_service()
        print("[QW-B037] calendar_auth: already authenticated")
        return {"error": "Already authenticated"}
    except NotAuthenticated as e:
        print("[QW-B038] calendar_auth: not authenticated, generating OAuth state")
        state = secrets.token_urlsafe(32)
        request.session["oauth_state"] = state
        print(f"[QW-B039] calendar_auth: oauth_state stored={state[:8]}...")
        try:
            get_service(state=state)
        except NotAuthenticated as e2:
            request.session["oauth_code_verifier"] = e2.code_verifier
            print(f"[QW-B040] calendar_auth: code_verifier stored={e2.code_verifier is not None}")
            return {"auth_url": e2.auth_url, "oauth_state": state}


@app.get("/api/calendar/callback")
async def calendar_callback(request: Request, state: str = Query(...), user: User = Depends(get_current_user)):
    print(f"[QW-B041] calendar_callback: start, user={user.id}")
    stored_state = request.session.get("oauth_state")
    print(f"[QW-B042] calendar_callback: session keys={list(request.session.keys())}, stored_state={stored_state!r}, provided_state={state!r}")
    if not stored_state or not hmac.compare_digest(stored_state, state):
        print("[QW-B043] calendar_callback: STATE MISMATCH")
        return HTMLResponse("<h1>Error</h1><p>Invalid or missing state parameter.</p>", status_code=400)
    print("[QW-B044] calendar_callback: state valid, cleaning session")
    request.session.pop("oauth_state", None)
    code_verifier = request.session.pop("oauth_code_verifier", None)
    callback_url = os.getenv("GOOGLE_REDIRECT_URI") + "?" + str(request.url.query)
    print(f"[QW-B045] calendar_callback: callback_url={callback_url}, code_verifier={code_verifier is not None}")
    try:
        auth_flow(callback_url, code_verifier)
        print("[QW-B046] calendar_callback: auth_flow succeeded")
        return HTMLResponse(
            "<!DOCTYPE html><html><head><meta http-equiv='refresh' content='2;url=/'>"
            "<title>Success</title></head><body style='text-align:center;padding:60px;font-family:sans-serif'>"
            "<h1>Success!</h1><p>Calendar connected. Redirecting...</p></body></html>"
        )
    except Exception as exc:
        print(f"[QW-B047] calendar_callback: auth_flow FAILED: {type(exc).__name__}: {exc}")
        return HTMLResponse(
            "<!DOCTYPE html><html><head><meta http-equiv='refresh' content='3;url=/'>"
            "<title>Error</title></head><body style='text-align:center;padding:60px;font-family:sans-serif'>"
            "<h1>Error</h1><p>Authorization failed. Redirecting to login...</p></body></html>",
            status_code=500
        )


@app.get("/api/calendar/today")
async def calendar_today(user: User = Depends(get_current_user)):
    print(f"[QW-B030] calendar_today: start, user={user.id}")
    try:
        service = get_service()
        events = get_today_events(service)
        print(f"[QW-B031] calendar_today: success, events={len(events)}")
        return {"events": events}
    except NotAuthenticated as e:
        print("[QW-B032] calendar_today: NotAuthenticated")
        return {"auth_required": True, "auth_url": e.auth_url}


@app.get("/api/calendar/week")
async def calendar_week(user: User = Depends(get_current_user)):
    print(f"[QW-B033] calendar_week: start, user={user.id}")
    try:
        service = get_service()
        events = list_events(service, days=7)
        print(f"[QW-B034] calendar_week: success, events={len(events)}")
        return {"events": events}
    except NotAuthenticated as e:
        print("[QW-B035] calendar_week: NotAuthenticated")
        return {"auth_required": True, "auth_url": e.auth_url}


@app.post("/api/calendar/events")
async def create_calendar_event(resp: Response, req: EventCreateRequest, user: User = Depends(get_current_user)):
    try:
        service = get_service()
        try:
            user_tz = await get_user_timezone(user.id)
            event = create_event(
                service,
                req.summary,
                req.start,
                req.end,
                req.location,
                req.description,
                user_tz=user_tz,
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
            user_tz = await get_user_timezone(user.id)
            updated = edit_event(
                service,
                event_id,
                req.summary,
                req.start,
                req.end,
                req.location,
                req.description,
                user_tz=user_tz,
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


@app.get("/api/calendar/status")
async def calendar_status(user: User = Depends(get_current_user)):
    """Check if calendar is connected."""
    try:
        get_service()
        return {"connected": True}
    except NotAuthenticated as e:
        return {"connected": False, "auth_url": e.auth_url}


@app.get("/api/calendar/month")
async def calendar_month(year: int = Query(...), month: int = Query(...), user: User = Depends(get_current_user)):
    """Get events for a specific month."""
    print(f"[QW-B050] calendar_month: year={year}, month={month}, user={user.id}")
    try:
        service = get_service()
        events = get_month_events(service, year, month)
        print(f"[QW-B051] calendar_month: success, events={len(events)}")
        return {"events": events}
    except NotAuthenticated as e:
        print("[QW-B052] calendar_month: NotAuthenticated")
        return {"auth_required": True, "auth_url": e.auth_url}


@app.delete("/api/calendar/disconnect")
async def calendar_disconnect(request: Request, user: User = Depends(get_current_user)):
    """Disconnect Google Calendar by revoking token."""
    result = disconnect_calendar()
    request.session.pop("oauth_state", None)
    request.session.pop("oauth_code_verifier", None)
    return result


@app.get("/api/timezones")
async def get_timezones(user: User = Depends(get_current_user)):
    offsets = [f"UTC{h:+d}" if h != 0 else "UTC" for h in range(-12, 13)]
    return {"timezones": offsets}


@app.get("/api/settings")
async def get_settings(user: User = Depends(get_current_user)):
    tz = await get_user_timezone(user.id)
    return {
        "model_name": settings.model_name,
        "temperature": settings.temperature,
        "timeout": settings.timeout,
        "max_retries": settings.max_retries,
        "max_context_turns": settings.max_context_turns,
        "max_tool_iterations": settings.max_tool_iterations,
        "timezone": tz,
    }


class SettingsUpdateRequest(BaseModel):
    timezone: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    timeout: float | None = Field(default=None, ge=1.0, le=300.0)
    max_retries: int | None = Field(default=None, ge=0)
    max_context_turns: int | None = Field(default=None, ge=1, le=100)
    max_tool_iterations: int | None = Field(default=None, ge=1, le=20)


@app.patch("/api/settings")
async def update_settings(req: SettingsUpdateRequest, user: User = Depends(get_current_user)):
    if req.timezone is not None:
        import re
        if not re.match(r"^UTC(-|\+)?\d{1,2}$", req.timezone):
            raise HTTPException(status_code=400, detail=f"Invalid timezone: {req.timezone}")
        await update_user_timezone(user.id, req.timezone)
    return {"updated": True}
