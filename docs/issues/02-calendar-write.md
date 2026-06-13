# Issue #2: Calendar Write Operations (create/edit/delete)

## Functional Requirements
- User can create calendar events via natural language: "schedule a meeting with Ana next Tuesday at 3pm"
- User can edit existing events: "move my 3pm meeting to 4pm"
- User can delete events: "cancel my lunch with Bob"
- Events are created on the user's primary Google Calendar
- Event fields: summary, start, end, location, description

## Current State
- Google Calendar scope is `calendar.readonly` — no write access
- No create/edit/delete endpoints exist
- `_fetch_events` is read-only

## Technical Implementation
### OAuth Scope Change
- Change `SCOPES` in `gcalendar.py` from `["https://www.googleapis.com/auth/calendar.readonly"]` to `["https://www.googleapis.com/auth/calendar.events"]`
- This requires users to re-authenticate (token will be invalidated)
- Update `auth_flow` to request new scope

### New Endpoints (`backend/main.py`)
```python
@app.post("/api/calendar/events")
async def create_event(req: EventCreateRequest):
    """Create a calendar event."""
    service = get_service()
    event = service.events().insert(calendarId="primary", body=req.to_gapi_dict()).execute()
    return {"id": event["id"], "status": event.get("status", "confirmed")}

@app.put("/api/calendar/events/{event_id}")
async def edit_event(event_id: str, req: EventUpdateRequest):
    """Update an existing event."""
    service = get_service()
    event = service.events().update(calendarId="primary", eventId=event_id, body=req.to_gapi_dict()).execute()
    return {"id": event["id"]}

@app.delete("/api/calendar/events/{event_id}")
async def delete_event(event_id: str):
    """Delete an event."""
    service = get_service()
    service.events().delete(calendarId="primary", eventId=event_id).execute()
    return {"deleted": event_id}
```

### Pydantic Models (`backend/main.py`)
```python
class EventCreateRequest(BaseModel):
    summary: str
    start: str  # ISO 8601 datetime
    end: str    # ISO 8601 datetime
    location: str | None = None
    description: str | None = None

class EventUpdateRequest(BaseModel):
    summary: str | None = None
    start: str | None = None
    end: str | None = None
    location: str | None = None
    description: str | None = None
```

### Error Handling
- `create_event`: handle duplicate events (same time+summary) → return 409
- `edit_event`: handle missing event → return 404
- `delete_event`: handle missing event → return 404
- All endpoints catch `NotAuthenticated` → return 200 with `{"auth_required": True, "auth_url": ...}`

### Frontend
- No immediate frontend changes — write operations are LLM-driven via tool calls
- Today/week views should refresh after LLM-initiated create/edit/delete

## Acceptance Criteria
- [ ] OAuth scope changed to `calendar.events`
- [ ] `POST /api/calendar/events` creates event on Google Calendar
- [ ] `PUT /api/calendar/events/{id}` updates existing event
- [ ] `DELETE /api/calendar/events/{id}` removes event
- [ ] Duplicate event detection returns 409
- [ ] Missing event returns 404
- [ ] NotAuthenticated returns auth URL
- [ ] Existing events appear in `/api/calendar/today` and `/api/calendar/week` after creation
- [ ] Tests: create, edit, delete, duplicate, missing, not-auth for each endpoint
