# Issue #7: Calendar Filtering (custom date ranges, keyword, location)

## Dependencies
- **Requires #1 (Authentication)** — endpoint uses `Depends(get_current_user)`
- **Requires #3 (Tool call loop)** — `filter_events` extends the tool registry defined in #3

## Functional Requirements
- List events for custom date ranges: "show me events from Jan 1-15"
- Filter events by keyword: "what meetings do I have with Ana?"
- Filter events by location: "show me events at Room A"
- Combine filters: "meetings with Ana in January at Room A"
- Natural language date parsing: "next week", "this month", "last Monday"

## Current State
- `get_today_events(service)` — fixed to today
- `list_events(service, days=7)` — fixed to next 7 days
- No filtering by keyword, location, or custom date range
- No natural language date parsing

## Technical Implementation

### New Endpoint (`backend/main.py`)
```python
from datetime import datetime, timedelta, timezone

class EventFilterRequest(BaseModel):
    time_min: str | None = None      # ISO 8601 start
    time_max: str | None = None      # ISO 8601 end
    days: int | None = None          # relative: next N days from now
    keyword: str | None = None       # search in summary + description
    location: str | None = None      # search in location

@app.post("/api/calendar/filter")
async def filter_events(req: EventFilterRequest, user: User = Depends(get_current_user)):
    service = get_service()

    # Determine time range
    now = datetime.now(timezone.utc)
    if req.time_min and req.time_max:
        time_min, time_max = req.time_min, req.time_max
    elif req.days:
        time_min = now.isoformat()
        time_max = (now + timedelta(days=req.days)).isoformat()
    else:
        time_min = (now - timedelta(days=30)).isoformat()
        time_max = (now + timedelta(days=30)).isoformat()

    events = _fetch_events(service, time_min, time_max)

    # Apply filters
    if req.keyword:
        kw = req.keyword.lower()
        events = [e for e in events if kw in e.get("summary", "").lower() or kw in (e.get("description") or "").lower()]
    if req.location:
        loc = req.location.lower()
        events = [e for e in events if loc in (e.get("location") or "").lower()]

    return {"events": events}
```

### Natural Language Date Parsing
- Use `dateutil.parser` for parsing relative dates: "next Tuesday", "3pm tomorrow"
- Register as a tool: `parse_date_range(description: str) → {time_min, time_max}`
```python
from datetime import datetime, timedelta, timezone
from dateutil import parser as dateutil_parser
from llm import LLMError

def parse_date_range(description: str) -> dict:
    """Parse natural language date description to ISO 8601 range.
    
    Handles single dates ("next Tuesday" → that day 00:00-23:59) and
    ranges ("next week" → Monday 00:00 to Sunday 23:59).
    """
    try:
        dt = dateutil_parser.parse(description, default=datetime.now(timezone.utc))
        day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = dt.replace(hour=23, minute=59, second=59)
        return {"time_min": day_start.isoformat(), "time_max": day_end.isoformat()}
    except ValueError as e:
        raise LLMError(f"Could not parse date: {description}")
```

### New Dependencies
- `python-dateutil` — add to `backend/pyproject.toml` `[project.dependencies]`

### Tool Registration (extends #3's tool registry)
```python
# Standalone wrapper — not the FastAPI endpoint (Depends won't resolve from tool registry)
from datetime import datetime, timedelta, timezone

def tool_filter_events(time_min: str | None = None, time_max: str | None = None, days: int | None = None, keyword: str | None = None, location: str | None = None) -> dict:
    service = get_service()
    now = datetime.now(timezone.utc)
    if time_min and time_max:
        pass  # use provided range
    elif days:
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
    return {"events": events}

ToolRegistry.register(
    name="filter_events",
    description="Filter calendar events by date range, keyword, or location",
    parameters={
        "type": "object",
        "properties": {
            "time_min": {"type": "string", "description": "Start date (ISO 8601)"},
            "time_max": {"type": "string", "description": "End date (ISO 8601)"},
            "days": {"type": "integer", "description": "Next N days from now"},
            "keyword": {"type": "string", "description": "Search in summary and description"},
            "location": {"type": "string", "description": "Search in location"},
        },
    },
    handler=tool_filter_events,
)

ToolRegistry.register(
    name="parse_date_range",
    description="Parse natural language date description (e.g., 'next Tuesday', 'this month') into a date range",
    parameters={
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "Natural language date description"},
        },
    },
    handler=parse_date_range,
)
```

## Acceptance Criteria
- [ ] `POST /api/calendar/filter` accepts date range, keyword, and location filters
- [ ] Custom date range (`time_min` + `time_max`) works
- [ ] Relative date range (`days=N`) works
- [ ] Keyword filter searches in summary and description (case-insensitive)
- [ ] Location filter searches in location (case-insensitive)
- [ ] Filters can be combined
- [ ] Default range: ±30 days when no range specified
- [ ] `parse_date_range` tool returns `{time_min, time_max}` for use with `filter_events`
- [ ] `filter_events` tool registered in ToolRegistry (extends #3)
- [ ] Tests: each filter individually, combined filters, empty results, invalid dates, keyword matching, date range parsing
