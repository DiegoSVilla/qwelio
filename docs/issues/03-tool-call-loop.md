# Issue #3: Agentic Tool Call Loop with Function Calling

## Dependencies
- **Requires #1 (Authentication)** — endpoint uses `Depends(get_current_user)`
- **Requires #2 (Calendar write operations)** — `create_event`, `edit_event`, `delete_event` tools depend on these endpoints existing

## Functional Requirements
- LLM can request tool calls (e.g., `create_event`, `list_events`) in response to user messages
- System executes the requested tool with LLM-provided parameters
- Tool result is injected back into the conversation as a `tool_result` message
- Loop continues until LLM returns a plain text response (no more tool calls)
- Final text response is returned to the user

## Current State
- `POST /api/chat` sends messages to LLM and returns response — single turn, no tool calls
- `chat()` in `llm.py` calls `client.chat.completions.create()` once and returns
- No function calling / tool calling enabled
- No tool registry or execution framework

## Technical Implementation

### Tool Registry (`backend/tools.py`)
```python
import json
from pydantic import BaseModel
from typing import Any, Callable
import asyncio
import inspect
from llm import LLMError

class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: dict  # JSON Schema

class ToolRegistry:
    _tools: dict[str, ToolDefinition] = {}
    _handlers: dict[str, Callable] = {}

    @classmethod
    def register(cls, name: str, description: str, parameters: dict, handler: Callable):
        cls._tools[name] = ToolDefinition(name=name, description=description, parameters=parameters)
        cls._handlers[name] = handler

    @classmethod
    def get_definitions(cls) -> list[dict]:
        return [{"type": "function", "function": t.model_dump()} for t in cls._tools.values()]

    @classmethod
    async def execute(cls, name: str, arguments: dict) -> str:
        try:
            handler = cls._handlers[name]
        except KeyError:
            raise LLMError(f"Unknown tool: {name}")
        try:
            # Always wrap in asyncio.to_thread for sync handlers, or await directly for async
            if inspect.iscoroutinefunction(handler):
                coro = handler(**arguments)
            else:
                coro = asyncio.to_thread(handler, **arguments)
            result = await asyncio.wait_for(coro, timeout=10.0)
            return json.dumps(result) if isinstance(result, dict) else str(result)
        except asyncio.TimeoutError:
            raise LLMError(f"Tool {name} timed out after 10s")
```

### Tool Definitions (registered at startup)

**Important**: Handlers are standalone wrapper functions, NOT the FastAPI endpoint functions directly. FastAPI's `Depends()` won't resolve when called from the tool registry. Each wrapper acquires the service/user context internally:

```python
def tool_create_event(summary: str, start: str, end: str, location: str | None = None, description: str | None = None) -> dict:
    service = get_service()
    body = {
        "summary": summary,
        "start": {"dateTime": start} if "T" in start else {"date": start},
        "end": {"dateTime": end} if "T" in end else {"date": end},
    }
    if location:
        body["location"] = location
    if description:
        body["description"] = description
    event = service.events().insert(calendarId="primary", body=body).execute()
    return {"id": event["id"], "status": event.get("status", "confirmed")}

def tool_list_events(time_min: str | None = None, time_max: str | None = None, days: int = 7) -> list[dict]:
    service = get_service()
    if time_min and time_max:
        return _fetch_events(service, time_min, time_max)
    return list_events(service, days=days)
```

| Tool | Parameters | Handler |
|------|-----------|---------|
| `create_event` | `summary`, `start` (ISO 8601), `end` (ISO 8601), `location?`, `description?` | `tool_create_event()` |
| `edit_event` | `event_id`, `summary?`, `start?`, `end?`, `location?`, `description?` | `tool_edit_event()` |
| `delete_event` | `event_id` | `tool_delete_event()` |
| `list_events` | `time_min?` (ISO 8601), `time_max?` (ISO 8601), `days?` (default 7) | `tool_list_events()` |
| `get_today_events` | (none) | `tool_get_today_events()` |
| `filter_events` | `time_min?`, `time_max?`, `days?`, `keyword?`, `location?` | Added by #7 (extends this registry) |

### Modified Chat Loop (`backend/llm.py`)
```python
import json
import asyncio
import inspect

MAX_TOOL_ITERATIONS = 5

async def chat_with_tools(messages: list[dict]) -> tuple[str, list[dict]]:
    """Execute the tool call loop. Returns (final_content, tool_trace).
    tool_trace contains all tool call and tool result messages for persistence (#5).
    Never mutates the input messages list.
    """
    client = _get_client()
    model = _get_model()
    tool_definitions = ToolRegistry.get_definitions()
    tool_trace = []  # Collected tool messages for persistence

        # Import settings from #6 — defaults to 0.6 if not configured
        from settings import settings

    # Work on a copy to avoid mutating the caller's messages (which may be persisted history from #5)
    working_messages = list(messages)

    for iteration in range(MAX_TOOL_ITERATIONS):
        resp = await client.chat.completions.create(
            model=model,
            messages=working_messages,
            temperature=settings.temperature,
            tools=tool_definitions,
        )

        message = resp.choices[0].message

        if message.tool_calls:
            # Group all tool calls from this response into a single assistant message
            tool_call_dumps = [tc.model_dump() for tc in message.tool_calls]
            assistant_msg = {
                "role": "assistant",
                "content": message.content,
                "tool_calls": tool_call_dumps,
            }
            working_messages.append(assistant_msg)
            tool_trace.append(assistant_msg)

            # Execute each tool and append results
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                try:
                    arguments = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError as e:
                    result = f"Error: Invalid JSON in tool arguments for {tool_name}: {e}"
                else:
                    try:
                        result = await ToolRegistry.execute(tool_name, arguments)
                    except LLMError as e:
                        result = f"Error: {e}"

                tool_result_msg = {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                }
                working_messages.append(tool_result_msg)
                tool_trace.append(tool_result_msg)
        else:
            return (message.content or "", tool_trace)

    raise LLMError(f"Tool loop exceeded {MAX_TOOL_ITERATIONS} iterations")
```

### Modified Endpoint (`backend/main.py`)
```python
@app.post("/api/chat")
async def api_chat(req: ChatRequest, user: User = Depends(get_current_user)):
    try:
        content, tool_trace = await chat_with_tools(req.messages)
        return {"content": content}
    except LLMError as e:
        return {"error": str(e)}
```

**Note**: The full endpoint with history persistence, system prompt, and tool trace saving is shown in #5's spec. This snippet shows the core call pattern.

### Safety Guards
- `MAX_TOOL_ITERATIONS` = 5 — prevents infinite loops
- Tool execution timeout: 10s per call via `asyncio.wait_for`
- Parameter validation via Pydantic before tool execution
- Only registered tools can be called — unknown tool name → error message injected
- Rate limit: 10 tool calls per minute per user — tracked via in-memory dict keyed by user.id, with sliding-window counter that resets after 60s
- Working copy of messages prevents state leakage into persisted conversation history

## Acceptance Criteria
- [ ] LLM can request `create_event` and system executes it
- [ ] Tool result is injected as `tool` role message
- [ ] Loop continues until LLM returns text (no tool calls)
- [ ] `MAX_TOOL_ITERATIONS` = 5 prevents infinite loops
- [ ] Unknown tool name returns error to LLM
- [ ] Invalid JSON in tool arguments returns error to LLM
- [ ] Tool execution timeout: 10s via asyncio.wait_for
- [ ] Input messages list is never mutated (working copy used)
- [ ] Tests: single tool call, multiple tool calls, max iterations, unknown tool, invalid params, timeout, no mutation of input
