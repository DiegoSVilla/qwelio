from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from llm import chat
from gcalendar import get_service, auth_flow, list_events, get_today_events

app = FastAPI(title="Qwelio")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    messages: list[dict]


@app.post("/api/chat")
async def api_chat(req: ChatRequest):
    content = chat(req.messages)
    return {"content": content}


@app.get("/api/calendar/auth")
async def calendar_auth():
    result = get_service()
    if isinstance(result, str):
        return {"auth_url": result}
    return {"error": "Already authenticated"}


@app.get("/api/calendar/callback")
async def calendar_callback(state: str = Query(...)):
    try:
        service = auth_flow(state)
        return HTMLResponse(
            "<h1>Success!</h1><p>Calendar authorized. You can close this window.</p>"
        )
    except Exception as e:
        return HTMLResponse(f"<h1>Error</h1><p>{e}</p>", status_code=500)


@app.get("/api/calendar/today")
async def calendar_today():
    result = get_service()
    if isinstance(result, str):
        return {"auth_required": True, "auth_url": result}
    events = get_today_events(result)
    return {"events": events}


@app.get("/api/calendar/week")
async def calendar_week():
    result = get_service()
    if isinstance(result, str):
        return {"auth_required": True, "auth_url": result}
    events = list_events(result, days=7)
    return {"events": events}
