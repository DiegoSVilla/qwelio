from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from llm import chat

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
