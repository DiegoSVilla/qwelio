# Issue #3: Agentic Tool Call Loop with Function Calling

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
from pydantic import BaseModel
from typing import Any, Callable

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
    def execute(cls, name: str, arguments: dict) -> str:
        handler = cls._handlers[name]
        result = handler(**arguments)
        return json.dumps(result) if isinstance(result, dict) else str(result)
```

### Tool Definitions (registered at startup)
| Tool | Parameters | Handler |
|------|-----------|---------|
| `create_event` | `summary`, `start` (ISO 8601), `end` (ISO 8601), `location?`, `description?` | `gcalendar.create_event()` |
| `edit_event` | `event_id`, `summary?`, `start?`, `end?`, `location?`, `description?` | `gcalendar.update_event()` |
| `delete_event` | `event_id` | `gcalendar.delete_event()` |
| `list_events` | `time_min?` (ISO 8601), `time_max?` (ISO 8601), `days?` (default 7) | `gcalendar._fetch_events()` |
| `get_today_events` | (none) | `gcalendar.get_today_events()` |

### Modified Chat Loop (`backend/llm.py`)
```python
MAX_TOOL_ITERATIONS = 5

async def chat_with_tools(messages: list[dict], conversation_id: str | None = None) -> str:
    client = _get_client()
    model = _get_model()
    tool_definitions = ToolRegistry.get_definitions()

    for iteration in range(MAX_TOOL_ITERATIONS):
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.6,
            tools=tool_definitions,  # OpenAI function calling format
        )

        message = resp.choices[0].message

        if message.tool_calls:
            # Execute each tool call
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments)
                result = ToolRegistry.execute(tool_name, arguments)

                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [tool_call.model_dump()],
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })
        else:
            # No tool calls — final response
            return message.content or ""

    raise LLMError(f"Tool loop exceeded {MAX_TOOL_ITERATIONS} iterations")
```

### Modified Endpoint (`backend/main.py`)
```python
@app.post("/api/chat")
async def api_chat(req: ChatRequest):
    try:
        content = await chat_with_tools(req.messages)
        return {"content": content}
    except LLMError as e:
        return {"error": str(e)}
```

### Safety Guards
- `MAX_TOOL_ITERATIONS` = 5 — prevents infinite loops
- Tool execution timeout: 10s per call (async timeout)
- Parameter validation via Pydantic before tool execution
- Only registered tools can be called — unknown tool name → error message injected
- Rate limit: 10 tool calls per minute per user

## Acceptance Criteria
- [ ] LLM can request `create_event` and system executes it
- [ ] Tool result is injected as `tool_result` message
- [ ] Loop continues until LLM returns text (no tool calls)
- [ ] `MAX_TOOL_ITERATIONS` = 5 prevents infinite loops
- [ ] Unknown tool name returns error to LLM
- [ ] Invalid tool parameters return validation error
- [ ] Tool execution timeout: 10s
- [ ] Tests: single tool call, multiple tool calls, max iterations, unknown tool, invalid params, timeout
