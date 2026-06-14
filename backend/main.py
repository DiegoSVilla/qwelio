import os
import secrets
import hmac

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, Field, field_validator
from typing import Literal
from datetime import datetime, date

from dotenv import load_dotenv

from llm import chat, LLMError
from gcalendar import get_service, auth_flow, list_events, get_today_events, create_event, edit_event, delete_event, NotAuthenticated
from auth import User, SESSION_KEY, _rate_limiter, get_current_user, verify_password

load_dotenv()

app = FastAPI(title="Qwelio")

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
    description: str | None = Field(default=None)

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
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")) if "T" in start else date.fromisoformat(start)
            end_dt = datetime.fromisoformat(v.replace("Z", "+00:00")) if "T" in v else date.fromisoformat(v)
            if end_dt <= start_dt:
                raise ValueError("end must be after start")
        return v


class EventUpdateRequest(BaseModel):
    summary: str | None = Field(default=None, min_length=1, max_length=1024)
    start: str | None = None
    end: str | None = None
    location: str | None = Field(default=None, max_length=2048)
    description: str | None = Field(default=None)

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
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")) if "T" in start else date.fromisoformat(start)
            end_dt = datetime.fromisoformat(v.replace("Z", "+00:00")) if "T" in v else date.fromisoformat(v)
            if end_dt <= start_dt:
                raise ValueError("end must be after start")
        return v


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
        content = await chat(req.messages)
        return {"content": content}
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
