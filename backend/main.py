from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from typing import Literal
from llm import chat, LLMError
from gcalendar import get_service, auth_flow, list_events, get_today_events, NotAuthenticated

app = FastAPI(title="Qwelio")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[Message] = Field(..., max_length=50)


@app.post("/api/chat")
async def api_chat(req: ChatRequest):
    try:
        content = await chat(req.messages)
        return {"content": content}
    except LLMError as e:
        return {"error": str(e)}


@app.get("/api/calendar/auth")
async def calendar_auth():
    try:
        service = get_service()
        return {"error": "Already authenticated"}
    except NotAuthenticated as e:
        return {"auth_url": e.auth_url}


@app.get("/api/calendar/callback")
async def calendar_callback(state: str = Query(...)):
    try:
        auth_flow(state)
        return HTMLResponse(
            "<h1>Success!</h1><p>Calendar authorized. You can close this window.</p>"
        )
    except Exception:
        return HTMLResponse("<h1>Error</h1><p>Authorization failed. Try again.</p>", status_code=500)


@app.get("/api/calendar/today")
async def calendar_today():
    try:
        service = get_service()
        events = get_today_events(service)
        return {"events": events}
    except NotAuthenticated as e:
        return {"auth_required": True, "auth_url": e.auth_url}


@app.get("/api/calendar/week")
async def calendar_week():
    try:
        service = get_service()
        events = list_events(service, days=7)
        return {"events": events}
    except NotAuthenticated as e:
        return {"auth_required": True, "auth_url": e.auth_url}
