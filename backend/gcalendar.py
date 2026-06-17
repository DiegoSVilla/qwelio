from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime, timedelta, timezone
import os
import json
import pathlib

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
TOKEN_PATH = pathlib.Path(__file__).parent / ".calendar_token.json"


class NotAuthenticated(Exception):
    def __init__(self, auth_url: str, code_verifier: str = None):
        self.auth_url = auth_url
        self.code_verifier = code_verifier
        super().__init__(f"Not authenticated. Visit: {auth_url}")


def _save_token(credentials):
    print("[QW-G001] _save_token: saving calendar token")
    TOKEN_PATH.write_text(json.dumps({
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": credentials.scopes,
    }))
    TOKEN_PATH.chmod(0o600)
    print("[QW-G002] _save_token: saved successfully")


def _load_credentials():
    print("[QW-G003] _load_credentials: checking token file")
    if TOKEN_PATH.exists():
        data = json.loads(TOKEN_PATH.read_text())
        creds = Credentials(**data)
        print(f"[QW-G004] _load_credentials: token valid={creds.valid}")
        if not creds.valid:
            if creds.refresh_token:
                print("[QW-G005] _load_credentials: refreshing expired token")
                creds.refresh(Request())
                _save_token(creds)
                print("[QW-G006] _load_credentials: token refreshed successfully")
            else:
                print("[QW-G007] _load_credentials: no refresh token available")
        return creds
    print("[QW-G008] _load_credentials: no token file found")
    return None


def _check_env():
    if not os.getenv("GOOGLE_CLIENT_ID") or not os.getenv("GOOGLE_CLIENT_SECRET"):
        raise RuntimeError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set")


def _build_flow():
    _check_env()
    return Flow.from_client_config(
        {
            "web": {
                "client_id": os.getenv("GOOGLE_CLIENT_ID"),
                "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
    )


def _format_events(events):
    formatted = []
    for e in events:
        start = e.get("start", {})
        formatted.append({
            "id": e.get("id"),
            "summary": e.get("summary", "No title"),
            "start": start.get("dateTime") or start.get("date"),
            "end": (e.get("end", {}) or {}).get("dateTime") or (e.get("end", {}) or {}).get("date"),
            "location": e.get("location"),
            "description": e.get("description"),
        })
    return formatted


def get_service(state=None):
    creds = _load_credentials()
    if creds:
        print("[QW-G010] get_service: returning calendar service with valid credentials")
        return build("calendar", "v3", credentials=creds)

    if not os.getenv("GOOGLE_CLIENT_ID") or not os.getenv("GOOGLE_CLIENT_SECRET"):
        print("[QW-G011] get_service: missing Google OAuth env vars")
        raise NotAuthenticated("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env")

    print("[QW-G012] get_service: building OAuth flow")
    flow = _build_flow()
    flow.redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="select_account consent",
        state=state,
    )
    code_verifier = getattr(flow, "code_verifier", None)
    print(f"[QW-G013] get_service: code_verifier={code_verifier is not None}")
    raise NotAuthenticated(auth_url, code_verifier)


def auth_flow(callback_url, code_verifier=None):
    print("[QW-G020] auth_flow: start")
    flow = _build_flow()
    flow.redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
    if code_verifier:
        flow.code_verifier = code_verifier
    print(f"[QW-G021] auth_flow: code_verifier={code_verifier is not None}")
    print("[QW-G022] auth_flow: fetching token from Google")
    flow.fetch_token(authorization_response=callback_url)
    print("[QW-G023] auth_flow: token fetched, saving credentials")
    _save_token(flow.credentials)
    print("[QW-G024] auth_flow: building calendar service")
    return build("calendar", "v3", credentials=flow.credentials)


def _fetch_events(service, time_min, time_max):
    print(f"[QW-G030] _fetch_events: time_min={time_min}, time_max={time_max}")
    events_result = service.events().list(
        calendarId="primary",
        timeMin=time_min,
        timeMax=time_max,
        maxResults=50,
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    items = events_result.get("items", [])
    print(f"[QW-G031] _fetch_events: raw events={len(items)}")
    formatted = _format_events(items)
    print(f"[QW-G032] _fetch_events: formatted events={len(formatted)}")
    return formatted


def list_events(service, days=7):
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)
    print(f"[QW-G040] list_events: days={days}, range={now.isoformat()} to {end.isoformat()}")
    return _fetch_events(service, now.isoformat(), end.isoformat())


def get_today_events(service):
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    print(f"[QW-G050] get_today_events: range={start.isoformat()} to {end.isoformat()}")
    return _fetch_events(service, start.isoformat(), end.isoformat())


def _strip_offset(dt_str: str) -> str:
    """Strip timezone offset from ISO datetime string.

    Google Calendar API uses the timeZone field, not the offset in the dateTime.
    If both are present, Google prefers the offset, causing wrong-day events.
    Examples: '2026-07-11T00:00:00-03:00' -> '2026-07-11T00:00:00'
              '2026-07-11T00:00:00Z' -> '2026-07-11T00:00:00'
    """
    import re
    # Strip trailing Z
    s = dt_str.rstrip("Z")
    # Strip +HH:MM or -HH:MM or +HHMM or -HHMM
    s = re.sub(r"[+-]\d{2}:\d{2}$", "", s)
    s = re.sub(r"[+-]\d{4}$", "", s)
    return s


def _to_gapi_event(summary, start, end, location=None, description=None, user_tz=None):
    """Convert tool args to Google Calendar API event body.

    When user_tz is provided, we strip any offset from the dateTime and set
    the timeZone field so Google interprets the time in the user's timezone.
    """
    event = {"summary": summary}
    if "T" in start:
        dt = _strip_offset(start) if user_tz else start
        event["start"] = {"dateTime": dt}
        if user_tz:
            event["start"]["timeZone"] = _tz_to_iana(user_tz)
    else:
        event["start"] = {"date": start}
    if "T" in end:
        dt = _strip_offset(end) if user_tz else end
        event["end"] = {"dateTime": dt}
        if user_tz:
            event["end"]["timeZone"] = _tz_to_iana(user_tz)
    else:
        event["end"] = {"date": end}
    if location is not None:
        event["location"] = location
    if description is not None:
        event["description"] = description
    return event


def _tz_to_iana(tz: str) -> str:
    """Convert UTC offset string (e.g. 'UTC-3') to IANA 'Etc/GMT+3'.

    POSIX/GMT convention inverts the sign: UTC-3 -> Etc/GMT+3.
    """
    if tz == "UTC":
        return "Etc/UTC"
    import re
    m = re.match(r"^UTC([+-])(\d{1,2})$", tz)
    if m:
        sign = "+" if m.group(1) == "-" else "-"
        offset = m.group(2).zfill(2)
        return f"Etc/GMT{sign}{offset}"
    return "Etc/UTC"


def create_event(service, summary, start, end, location=None, description=None, user_tz=None):
    print(f"[QW-G060] create_event: summary={summary}, start={start}, end={end}")
    start_str = start if isinstance(start, str) else start.isoformat()
    end_str = end if isinstance(end, str) else end.isoformat()
    # Expand timeMin backwards by event duration to catch overlapping events
    if "T" in start_str:
        start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
        # If naive (no offset from LLM), attach user timezone so Google accepts the query
        if start_dt.tzinfo is None and user_tz:
            tz_offset = _parse_tz_offset(user_tz)
            user_tzinfo = timezone(timedelta(hours=tz_offset))
            start_dt = start_dt.replace(tzinfo=user_tzinfo)
            end_dt = end_dt.replace(tzinfo=user_tzinfo)
        elif start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        duration = (end_dt - start_dt).total_seconds()
        expanded_start = (start_dt - timedelta(seconds=duration)).isoformat()
        query_end = end_dt.isoformat()
    else:
        start_dt = datetime.fromisoformat(start_str)
        end_dt = datetime.fromisoformat(end_str)
        duration = (end_dt - start_dt).days
        expanded_start = (start_dt - timedelta(days=max(duration, 1))).strftime("%Y-%m-%d")
        # Google requires timezone-aware ISO strings for timeMin/timeMax
        expanded_start = f"{expanded_start}T00:00:00+00:00"
        query_end = f"{end_str}T00:00:00+00:00"
    print(f"[QW-G061] create_event: checking duplicates in range {expanded_start} to {query_end}")
    existing = _fetch_events(service, expanded_start, query_end)
    for e in existing:
        if e["summary"].lower() == summary.lower():
            print(f"[QW-G062] create_event: DUPLICATE found: {e['summary']}")
            raise ValueError(f"Duplicate event: {e['summary']}")
    event_body = _to_gapi_event(summary, start, end, location, description, user_tz)
    print("[QW-G063] create_event: inserting event")
    created = service.events().insert(calendarId="primary", body=event_body).execute()
    print(f"[QW-G064] create_event: success, event_id={created['id']}")
    return created


def edit_event(service, event_id, summary=None, start=None, end=None, location=None, description=None, user_tz=None):
    print(f"[QW-G070] edit_event: event_id={event_id}")
    try:
        existing = service.events().get(calendarId="primary", eventId=event_id).execute()
        print(f"[QW-G071] edit_event: fetched event '{existing.get('summary')}'")
    except HttpError as e:
        if e.resp.status == 404:
            print(f"[QW-G072] edit_event: NOT FOUND event_id={event_id}")
            raise KeyError(f"Event {event_id} not found")
        raise
    if summary is not None:
        existing["summary"] = summary
    if start is not None:
        start_obj = existing.get("start", {})
        if "T" in start:
            dt = _strip_offset(start) if user_tz else start
            existing["start"] = {"dateTime": dt}
            if user_tz:
                existing["start"]["timeZone"] = _tz_to_iana(user_tz)
        else:
            existing["start"] = {"date": start}
        if "timeZone" in start_obj and "timeZone" not in existing.get("start", {}):
            existing["start"]["timeZone"] = start_obj["timeZone"]
    if end is not None:
        end_obj = existing.get("end", {})
        if "T" in end:
            dt = _strip_offset(end) if user_tz else end
            existing["end"] = {"dateTime": dt}
            if user_tz:
                existing["end"]["timeZone"] = _tz_to_iana(user_tz)
        else:
            existing["end"] = {"date": end}
        if "timeZone" in end_obj and "timeZone" not in existing.get("end", {}):
            existing["end"]["timeZone"] = end_obj["timeZone"]
    if location is not None:
        existing["location"] = location
    if description is not None:
        existing["description"] = description
    print("[QW-G073] edit_event: updating event")
    updated = service.events().update(calendarId="primary", eventId=event_id, body=existing).execute()
    print(f"[QW-G074] edit_event: success, event_id={updated['id']}")
    return updated


def delete_event(service, event_id):
    print(f"[QW-G080] delete_event: event_id={event_id}")
    try:
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        print(f"[QW-G081] delete_event: success, event_id={event_id}")
    except HttpError as e:
        if e.resp.status == 404:
            print(f"[QW-G082] delete_event: NOT FOUND event_id={event_id}")
            raise KeyError(f"Event {event_id} not found")
        raise


def get_month_events(service, year: int, month: int):
    """Get all events for a given month."""
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    print(f"[QW-G090] get_month_events: range={start.isoformat()} to {end.isoformat()}")
    return _fetch_events(service, start.isoformat(), end.isoformat())


def disconnect_calendar():
    """Revoke Google OAuth tokens and delete token file."""
    print("[QW-G100] disconnect_calendar: start")
    if not TOKEN_PATH.exists():
        print("[QW-G101] disconnect_calendar: no token file found")
        return {"error": "Calendar not connected"}
    try:
        data = json.loads(TOKEN_PATH.read_text())
        creds = Credentials(**data)
        from google.auth.transport.requests import Request
        req = Request()
        revoke_url = "https://oauth2.googleapis.com/revoke"
        # Revoke access token
        resp = req.post(revoke_url, body=f"token={creds.token}")
        print(f"[QW-G102] disconnect_calendar: access token revoked, status={resp.status}")
        # Also revoke refresh token if present
        if creds.refresh_token:
            resp = req.post(revoke_url, body=f"token={creds.refresh_token}")
            print(f"[QW-G103] disconnect_calendar: refresh token revoked, status={resp.status}")
    except Exception as e:
        print(f"[QW-G104] disconnect_calendar: revoke failed: {e}")
    TOKEN_PATH.unlink(missing_ok=True)
    print("[QW-G105] disconnect_calendar: token file deleted")
    return {"disconnected": True}
