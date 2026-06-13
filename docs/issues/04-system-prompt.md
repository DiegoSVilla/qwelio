# Issue #4: Dynamic System Prompt with Calendar Context Injection

## Dependencies
- **Requires #1 (Authentication)** — endpoint uses `Depends(get_current_user)`
- **Requires #3 (Tool call loop)** — tool definitions are injected into the system prompt
- **Extended by #8 (Time-aware prompt)** — timezone handling is moved to `ZoneInfo` in #8; this spec uses a placeholder approach

## Functional Requirements
- Each LLM turn receives a system prompt enriched with:
  - Current datetime (UTC + user timezone)
  - Today's calendar agenda (formatted events)
  - Last 7 days of events (for conversational context like "yesterday's meeting")
  - Available tools with descriptions and parameter schemas
- System prompt is rebuilt fresh every turn — never stale
- Prompt stays within model's context window

## Current State
- No system prompt is sent to the LLM
- `chat()` receives raw user messages with no context
- LLM has no awareness of time, calendar, or available tools

## Technical Implementation

### System Prompt Builder (`backend/prompt.py`)
```python
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

def build_system_prompt(
    current_time: datetime,
    user_timezone: str,
    today_events: list[dict],
    week_events: list[dict],
    tool_definitions: list[dict],
) -> str:
    """Build the system prompt with fresh calendar context."""
    try:
        tz = ZoneInfo(user_timezone)
        now_local = current_time.astimezone(tz)
    except Exception:
        now_local = current_time  # fallback to UTC

    today_section = format_events_section("Today's agenda", today_events)
    week_section = format_events_section("This week's events", week_events)
    tools_section = format_tools_section(tool_definitions)

    return f"""You are Qwelio, an AI calendar assistant. You help users manage their schedule.

Current time: {now_local.isoformat()} (timezone: {user_timezone})
UTC time: {current_time.isoformat()}

{today_section}

{week_section}

Available tools:
{tools_section}

Guidelines:
- Always reference the current time when discussing schedules
- Use tools to create, edit, delete, and query calendar events
- If the user asks about "tomorrow" or "next week", use the current date to calculate
- Be concise and reference specific events by name and time
- If no events match the user's query, say so clearly
- Never invent events that don't exist in the calendar
"""

def format_events_section(title: str, events: list[dict]) -> str:
    if not events:
        return f"### {title}\n(No events)\n"
    lines = [f"### {title}"]
    for e in events:
        start = e.get("start") or "N/A"
        end = e.get("end") or "N/A"
        lines.append(f"- {e.get('summary', 'No title')} | {start} to {end}")
        if e.get("location"):
            lines.append(f"  Location: {e['location']}")
    return "\n".join(lines) + "\n"

def format_tools_section(tools: list[dict]) -> str:
    lines = []
    for t in tools:
        fn = t["function"]
        lines.append(f"- **{fn['name']}**: {fn['description']}")
    return "\n".join(lines)
```

### Modified Chat Endpoint (`backend/main.py`)
```python
@app.post("/api/chat")
async def api_chat(req: ChatRequest, user: User = Depends(get_current_user)):
    try:
        current_time = datetime.now(timezone.utc)
        user_timezone = user.settings.get("timezone", "America/New_York")

        # Fetch fresh calendar context
        service = get_service()  # may raise NotAuthenticated
        today_events = get_today_events(service)
        week_events = list_events(service, days=7)

        # Build system prompt
        system_prompt = build_system_prompt(
            current_time=current_time,
            user_timezone=user_timezone,
            today_events=today_events,
            week_events=week_events,
            tool_definitions=ToolRegistry.get_definitions(),
        )

        # Prepend system message
        messages = [{"role": "system", "content": system_prompt}] + req.messages

        content, tool_trace = await chat_with_tools(messages)
        # Full persistence of tool_trace is handled in #5
        return {"content": content}
    except NotAuthenticated as e:
        return {"auth_required": True, "auth_url": e.auth_url}
    except LLMError as e:
        return {"error": str(e)}
```

### Dynamic Variable Refresh
| Variable | Refreshed | When |
|----------|-----------|------|
| `current_time` | Every turn | `datetime.now(timezone.utc)` at request start |
| `user_timezone` | Session start | From user settings / `.env` `USER_TIMEZONE` |
| `today_events` | Every turn | Fresh `get_today_events(service)` call |
| `week_events` | Every turn | Fresh `list_events(service, days=7)` call |
| `tool_definitions` | Static | Loaded at app startup |

### Context Window Management
- If total prompt tokens exceed model's max (e.g., 8192 for Gemma), drop oldest conversation turns first
- Calendar context is always preserved (it's small: ~500 tokens max)
- Configurable via `MAX_CONTEXT_TURNS` env var (default: 20)
- **Note**: `_fetch_events` currently caps at `maxResults=50`. For busy calendars, a 7-day window could exceed this. Consider increasing `maxResults` or implementing pagination if users report truncated event lists.

## Acceptance Criteria
- [ ] System prompt includes current time in both UTC and user timezone (via ZoneInfo)
- [ ] System prompt includes today's events formatted as bullet list
- [ ] System prompt includes this week's events
- [ ] System prompt lists available tools with descriptions
- [ ] Calendar context is fresh on every turn (not cached)
- [ ] `format_events_section` handles None/null start/end gracefully
- [ ] LLM correctly references events by name and time
- [ ] LLM correctly calculates relative dates ("tomorrow", "next Tuesday")
- [ ] Context window overflow drops oldest conversation turns
- [ ] Tests: prompt builder with events, empty events, timezone conversion, tool formatting, overflow truncation, null event fields
