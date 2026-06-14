import os
from datetime import datetime

from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


DEFAULT_TIMEZONE = os.getenv("USER_TIMEZONE", "UTC")
MAX_DESCRIPTION_LENGTH = 200


def _truncate(s: str, max_len: int) -> str:
    """Truncate a string to max_len characters, appending '...' if truncated."""
    return s[:max_len] + "..." if len(s) > max_len else s


def _format_event(e: dict) -> str:
    """Format a single calendar event for inclusion in the system prompt."""
    lines = [f"  - {e.get('summary', 'No title')}"]
    start = e.get("start", "")
    end = e.get("end", "")
    if start:
        lines[-1] += f" ({start}"
        if end:
            lines[-1] += f" -> {end}"
        lines[-1] += ")"
    if e.get("location"):
        lines.append(f"    Location: {e['location']}")
    desc = e.get("description")
    if desc:
        lines.append(f"    Description: {_truncate(desc, MAX_DESCRIPTION_LENGTH)}")
    return "\n".join(lines)


def _format_events_block(title: str, events: list[dict]) -> str:
    """Format a block of events with a section title."""
    if not events:
        return f"{title}:\n  (none)"
    formatted = "\n".join(_format_event(e) for e in events)
    return f"{title}:\n{formatted}"


def build_system_prompt(
    current_time_utc: datetime,
    user_timezone: str,
    today_events: list[dict],
    week_events: list[dict],
    tool_definitions: list[dict],
    calendar_available: bool = True,
) -> str:
    """Build the dynamic system prompt with calendar context and time awareness.

    Args:
        current_time_utc: Current time in UTC.
        user_timezone: IANA timezone name (e.g. "America/New_York").
        today_events: Events for today.
        week_events: Events for the next 7 days.
        tool_definitions: List of tool definition dicts from ToolRegistry.
        calendar_available: Whether the calendar API was reachable.

    Returns:
        The complete system prompt string.
    """
    calendar_status = "available" if calendar_available else "unavailable (not authenticated or API error)"

    tz_section = f"""You are Qwelio, an AI-powered calendar assistant. You help the user manage their schedule, answer questions about their calendar, and perform calendar operations.

# Current Time
- UTC: {current_time_utc.strftime("%Y-%m-%d %H:%M:%S")} UTC
- User timezone: {user_timezone}

# Calendar Context
Calendar access: {calendar_status}
{_format_events_block("Today's Agenda", today_events)}

{_format_events_block("Upcoming Week (next 7 days)", week_events)}

# Available Tools
You have access to the following tools to interact with the user's calendar:
"""

    if tool_definitions:
        for td in tool_definitions:
            func = td.get("function", {})
            name = func.get("name", "unknown")
            desc = func.get("description", "No description")
            tz_section += f"- {name}: {desc}\n"
    else:
        tz_section += "(no tools available)\n"

    tz_section += """
# Guidelines
- Always reference the current time and calendar context when answering.
- If the user asks about a specific day, check the calendar events for that day.
- When creating or editing events, confirm the details with the user before proceeding.
- If calendar data is unavailable, inform the user and guide them to authenticate.
- Keep responses concise and actionable.
"""
    return tz_section
