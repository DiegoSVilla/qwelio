# Issue #7: Calendar Filtering (custom date ranges, keyword, location)

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
- Register as a tool: `parse_date(description: str) → {time_min, time_max}`
```python
from dateutil import parser as dateutil_parser

def parse_date(description: str) -> dict:
    """Parse natural language date description to ISO 8601 range."""
    try:
        dt = dateutil_parser.parse(description, default=datetime.now(timezone.utc))
        return {"datetime": dt.isoformat()}
    except ValueError as e:
        raise LLMError(f"Could not parse date: {description}")
```

### Tool Registration
```python
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
    handler=lambda **kwargs: filter_events_by_criteria(**kwargs),
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
- [ ] `parse_date` tool handles natural language dates
- [ ] Tests: each filter individually, combined filters, empty results, invalid dates, keyword matching
