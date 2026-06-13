# Issue #8: Time-Aware System Prompt (timezone, current time)

## Functional Requirements
- System prompt always includes the current time in both UTC and user's local timezone
- User can configure their timezone (default: inferred from system or set in `.env`)
- LLM can correctly interpret relative time references: "tomorrow at 3pm", "next Tuesday", "in 30 minutes"
- Calendar events are displayed and compared in the user's timezone
- Day boundaries (today, tomorrow) are calculated in user's timezone, not UTC

## Current State
- `get_today_events` uses `datetime.now(timezone.utc)` — may not match user's "today"
- `list_events` uses UTC — same issue
- No timezone configuration exists
- System prompt doesn't include time information (depends on #4)

## Technical Implementation

### Timezone Configuration
```python
# backend/settings.py (add to InferenceSettings)
self.user_timezone = os.getenv("USER_TIMEZONE", "America/New_York")
```

### Timezone-Aware Event Fetching (`gcalendar.py`)
```python
from zoneinfo import ZoneInfo

def get_user_now(user_timezone: str = "America/New_York"):
    """Get current datetime in user's timezone."""
    tz = ZoneInfo(user_timezone)
    return datetime.now(tz)

def get_today_events(service, user_timezone: str = "America/New_York"):
    now = get_user_now(user_timezone)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    # Convert to UTC for Google API
    return _fetch_events(service, start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat())

def list_events(service, days: int = 7, user_timezone: str = "America/New_York"):
    now = get_user_now(user_timezone)
    end = now + timedelta(days=days)
    return _fetch_events(service, now.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat())
```

### Time in System Prompt (extends #4)
```python
def build_system_prompt(..., user_timezone: str):
    utc_now = datetime.now(timezone.utc)
    local_now = utc_now.astimezone(ZoneInfo(user_timezone))

    time_section = f"""Current time:
- UTC: {utc_now.strftime("%Y-%m-%d %H:%M:%S %Z")}
- Local ({user_timezone}): {local_now.strftime("%Y-%m-%d %H:%M:%S %Z")}
- Day of week: {local_now.strftime("%A")}
- Is business hours (9am-5pm local)? {"Yes" if 9 <= local_now.hour < 17 else "No"}
"""
    # ... rest of prompt
```

### Event Time Formatting
- Events returned from API include both UTC and local time:
```python
def _format_events(events, user_timezone: str = "America/New_York"):
    tz = ZoneInfo(user_timezone)
    formatted = []
    for e in events:
        start_raw = e.get("start", {})
        start_dt = parse_datetime(start_raw.get("dateTime") or start_raw.get("date"))
        local_start = start_dt.astimezone(tz) if start_dt else None

        formatted.append({
            "summary": e.get("summary", "No title"),
            "start": start_raw.get("dateTime") or start_raw.get("date"),
            "start_local": local_start.strftime("%Y-%m-%d %H:%M") if local_start else None,
            "end": ...,
            "location": e.get("location"),
            "description": e.get("description"),
        })
    return formatted
```

### Timezone Endpoint
```python
@app.get("/api/time")
async def get_current_time(user: User = Depends(get_current_user)):
    utc_now = datetime.now(timezone.utc)
    local_now = utc_now.astimezone(ZoneInfo(user.settings.get("timezone", "America/New_York")))
    return {
        "utc": utc_now.isoformat(),
        "local": local_now.isoformat(),
        "timezone": user.settings.get("timezone", "America/New_York"),
        "day_of_week": local_now.strftime("%A"),
        "business_hours": 9 <= local_now.hour < 17,
    }

@app.put("/api/timezone")
async def set_timezone(req: TimezoneRequest, user: User = Depends(get_current_user)):
    user.settings["timezone"] = req.timezone
    return {"timezone": req.timezone}
```

## Acceptance Criteria
- [ ] `USER_TIMEZONE` env var controls default timezone
- [ ] `get_today_events` uses user's timezone for day boundaries
- [ ] `list_events` uses user's timezone for start date
- [ ] System prompt shows both UTC and local time
- [ ] System prompt shows day of week and business hours status
- [ ] Events include `start_local` in user's timezone
- [ ] `GET /api/time` returns current time in both timezones
- [ ] `PUT /api/timezone` lets user change timezone
- [ ] Tests: timezone conversion, DST handling, day boundaries, business hours, edge cases (midnight, DST transition)
