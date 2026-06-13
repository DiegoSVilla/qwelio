# Issue #2: Calendar Write Operations (create/edit/delete)

## Dependencies
- **Requires #1 (Authentication)** — all endpoints use `Depends(get_current_user)`

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

## Prerequisites (existing bugs to fix first)
- **OAuth callback bug**: The current `auth_flow(state)` at `gcalendar.py:92` calls `flow.fetch_token(authorization_response=state)`, but the callback route at `main.py:46` passes `state: str = Query(...)` — which is the OAuth state parameter, not the full authorization URL containing the `code` query parameter. `fetch_token` expects a full URL with `?code=...`. This must be fixed before write operations can work. The callback should accept the `code` parameter directly and construct the proper authorization response URL.

## Technical Implementation
### OAuth Scope Change
- Change `SCOPES` in `gcalendar.py` from `["https://www.googleapis.com/auth/calendar.readonly"]` to `["https://www.googleapis.com/auth/calendar.events"]`
- This requires users to re-authenticate (token will be invalidated)
- Update `auth_flow` to request new scope

### New Endpoints (`backend/main.py`)
```python
@app.post("/api/calendar/events")
async def create_event(req: EventCreateRequest, user: User = Depends(get_current_user)):
    """Create a calendar event."""
    try:
        service = get_service()
    except NotAuthenticated as e:
        return {"auth_required": True, "auth_url": e.auth_url}
    event = service.events().insert(calendarId="primary", body=req.to_gapi_dict()).execute()
    return {"id": event["id"], "status": event.get("status", "confirmed")}

@app.patch("/api/calendar/events/{event_id}")
async def edit_event(event_id: str, req: EventUpdateRequest, user: User = Depends(get_current_user)):
    """Partially update an existing event. Only non-None fields are updated."""
    try:
        service = get_service()
    except NotAuthenticated as e:
        return {"auth_required": True, "auth_url": e.auth_url}
    try:
        existing = service.events().get(calendarId="primary", eventId=event_id).execute()
    except googleapiclient.errors.HttpError as e:
        if e.status_code == 404:
            raise HTTPException(404, f"Event {event_id} not found")
        raise
    except NotAuthenticated as e:
        return {"auth_required": True, "auth_url": e.auth_url}
    for field, value in req.model_dump(exclude_none=True).items():
        existing[field] = value
    updated = service.events().update(calendarId="primary", eventId=event_id, body=existing).execute()
    return {"id": updated["id"]}

@app.delete("/api/calendar/events/{event_id}")
async def delete_event(event_id: str, user: User = Depends(get_current_user)):
    """Delete an event."""
    try:
        service = get_service()
    except NotAuthenticated as e:
        return {"auth_required": True, "auth_url": e.auth_url}
    try:
        service.events().delete(calendarId="primary", eventId=event_id).execute()
    except googleapiclient.errors.HttpError as e:
        if e.status_code == 404:
            raise HTTPException(404, f"Event {event_id} not found")
        raise
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

    def to_gapi_dict(self) -> dict:
        return {
            "summary": self.summary,
            "start": {"dateTime": self.start} if "T" in self.start else {"date": self.start},
            "end": {"dateTime": self.end} if "T" in self.end else {"date": self.end},
            **{k: v for k, v in self.model_dump().items() if k not in ("summary", "start", "end") and v is not None},
        }

class EventUpdateRequest(BaseModel):
    """Partial update — only non-None fields are applied to the existing event."""
    summary: str | None = None
    start: str | None = None
    end: str | None = None
    location: str | None = None
    description: str | None = None
```

### Error Handling
- `create_event`: Duplicate detection queries existing events in the same time window with matching summary before insertion. If found → return 409 with `{"error": "Duplicate event", "existing_id": ...}`. This requires a preliminary `_fetch_events` call for the target time range.
- `edit_event`: handle missing event → return 404 (via `googleapiclient.errors.HttpError` catch)
- `delete_event`: handle missing event → return 404
- All endpoints catch `NotAuthenticated` → return 200 with `{"auth_required": True, "auth_url": ...}`
- All endpoints wrapped in try/except `NotAuthenticated` to return auth URL

### CORS Update
- The new HTTP methods `PATCH`, `DELETE`, and `PUT` must be added to the CORS middleware:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET", "POST", "PATCH", "DELETE", "PUT"],
    allow_headers=["Content-Type"],
)
```

### Frontend
- No immediate frontend changes — write operations are LLM-driven via tool calls
- Today/week views should refresh after LLM-initiated create/edit/delete

## Acceptance Criteria
- [ ] OAuth callback bug fixed (accepts `code` parameter, constructs proper authorization response URL)
- [ ] OAuth scope changed to `calendar.events`
- [ ] `POST /api/calendar/events` creates event on Google Calendar
- [ ] `PATCH /api/calendar/events/{id}` partially updates existing event (only non-None fields)
- [ ] `DELETE /api/calendar/events/{id}` removes event
- [ ] Duplicate event detection (same time+summary) returns 409 with existing event ID
- [ ] Missing event returns 404
- [ ] NotAuthenticated returns auth URL
- [ ] Existing events appear in `/api/calendar/today` and `/api/calendar/week` after creation
- [ ] Tests: create, edit, delete, duplicate, missing, not-auth for each endpoint
