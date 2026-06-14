import json
import time
from pathlib import Path

from dotenv import load_dotenv
from llm import chat, LLMError

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_last_summarize: dict[str, float] = {}
_SUMMARIZE_COOLDOWN = 300


def _build_summary_prompt(messages: list[dict], period: str, period_start: str, period_end: str) -> list[dict]:
    formatted = []
    for msg in messages:
        role = msg["role"]
        if role in ("user", "assistant"):
            tool_calls = msg.get("tool_calls")
            content = msg.get("content") or ""
            if tool_calls:
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        fn = tc.get("function", {})
                        name = fn.get("name", "unknown")
                        args = fn.get("arguments", "{}")
                        try:
                            args_obj = json.loads(args) if isinstance(args, str) else args
                        except (json.JSONDecodeError, TypeError):
                            args_obj = {}
                        formatted.append(f"[tool_call: {name}({json.dumps(args_obj)})]")
            if content.strip():
                formatted.append(f"{role}: {content.strip()}")
        elif role == "tool":
            content = msg.get("content") or ""
            if content.strip():
                formatted.append(f"[tool_result: {content.strip()}]")
    conversation = "\n".join(formatted)

    if period == "monthly":
        detail = "Brief overview: key topics, decisions, and calendar actions. Max 1 paragraph."
    elif period == "weekly":
        detail = "Detailed summary: conversations, calendar changes, recurring themes. Max 2 paragraphs."
    else:
        detail = "Detailed daily log: what was discussed, events created/modified/deleted, outcomes. Max 3 paragraphs."

    system_prompt = f"""You are a memory summarizer for a calendar assistant.

Summarize the following conversation from period {period_start} to {period_end} ({period}).

{detail}

Focus on:
- Calendar actions (events created, edited, deleted)
- User preferences and patterns
- Important decisions or recurring topics
- Time-sensitive information

Format as plain text. Do NOT include timestamps or metadata."""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": conversation or "(No conversations in this period)"},
    ]


async def generate_summary(user_id: str, period: str, period_start: str, period_end: str) -> str:
    from storage import get_period_messages
    messages = await get_period_messages(user_id, period_start, period_end)
    prompt_messages = _build_summary_prompt(messages, period, period_start, period_end)
    return await chat(prompt_messages)


async def generate_summaries(user_id: str) -> list[dict]:
    now = time.time()
    if _last_summarize.get(user_id, 0) + _SUMMARIZE_COOLDOWN > now:
        raise LLMError(f"Summarization cooldown active. Try again in {_SUMMARIZE_COOLDOWN - (now - _last_summarize.get(user_id, 0)):.0f}s")
    _last_summarize[user_id] = now
    from storage import get_pending_summaries, save_summary
    pending = await get_pending_summaries(user_id)
    results = []
    for period, ps, pe in pending:
        try:
            content = await generate_summary(user_id, period, ps, pe)
            await save_summary(user_id, period, ps, pe, content)
            results.append({"period": period, "start": ps, "end": pe, "status": "ok"})
        except LLMError as e:
            results.append({"period": period, "start": ps, "end": pe, "status": "error", "error": str(e)})
    return results
