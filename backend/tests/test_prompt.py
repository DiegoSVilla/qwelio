import os
from unittest.mock import patch
from datetime import datetime, timezone

import pytest

from prompt import build_system_prompt, _format_event, _format_events_block, _truncate


@pytest.fixture(autouse=True)
def reset_prompt_env():
    """Ensure clean env for timezone tests."""
    old = os.environ.pop("USER_TIMEZONE", None)
    yield
    if old is not None:
        os.environ["USER_TIMEZONE"] = old
    else:
        os.environ.pop("USER_TIMEZONE", None)


# --- _format_event ---

class TestFormatEvent:
    def test_basic_event(self):
        e = {"summary": "Team Standup", "start": "2025-06-15T09:00:00", "end": "2025-06-15T09:30:00"}
        result = _format_event(e)
        assert "Team Standup" in result
        assert "2025-06-15T09:00:00" in result
        assert "2025-06-15T09:30:00" in result

    def test_event_with_location(self):
        e = {"summary": "Lunch", "start": "12:00", "end": "13:00", "location": "Cafeteria"}
        result = _format_event(e)
        assert "Location: Cafeteria" in result

    def test_event_with_description(self):
        e = {"summary": "Review", "start": "10:00", "end": "11:00", "description": "Code review session"}
        result = _format_event(e)
        assert "Description: Code review session" in result

    def test_event_description_truncated(self):
        long_desc = "x" * 300
        e = {"summary": "Review", "start": "10:00", "end": "11:00", "description": long_desc}
        result = _format_event(e)
        assert "..." in result
        assert len(result) < 400

    def test_event_no_title(self):
        e = {"start": "10:00", "end": "11:00"}
        result = _format_event(e)
        assert "No title" in result

    def test_event_no_times(self):
        e = {"summary": "All day thing"}
        result = _format_event(e)
        assert "All day thing" in result
        assert "(" not in result


# --- _format_events_block ---

class TestFormatEventsBlock:
    def test_empty_events(self):
        result = _format_events_block("Section Title", [])
        assert "Section Title:" in result
        assert "(none)" in result

    def test_single_event(self):
        events = [{"summary": "Meeting", "start": "09:00", "end": "10:00"}]
        result = _format_events_block("Today", events)
        assert "Meeting" in result
        assert "09:00" in result

    def test_multiple_events(self):
        events = [
            {"summary": "A", "start": "09:00", "end": "10:00"},
            {"summary": "B", "start": "11:00", "end": "12:00"},
        ]
        result = _format_events_block("Today", events)
        assert "A" in result
        assert "B" in result


# --- build_system_prompt ---

class TestBuildSystemPrompt:
    @pytest.fixture
    def now_utc(self):
        return datetime(2025, 6, 15, 14, 30, 0, tzinfo=timezone.utc)

    @pytest.fixture
    def today_ev(self):
        return [{"summary": "Standup", "start": "2025-06-15T09:00:00", "end": "2025-06-15T09:15:00"}]

    @pytest.fixture
    def week_ev(self):
        return [{"summary": "Sprint Planning", "start": "2025-06-16T10:00:00", "end": "2025-06-16T11:00:00"}]

    @pytest.fixture
    def tool_defs(self):
        return [
            {"type": "function", "function": {"name": "create_event", "description": "Create a calendar event", "parameters": {}}},
            {"type": "function", "function": {"name": "list_events", "description": "List calendar events", "parameters": {}}},
        ]

    def test_contains_utc_time(self, now_utc, today_ev, week_ev, tool_defs):
        prompt = build_system_prompt(now_utc, "UTC", today_ev, week_ev, tool_defs)
        assert "2025-06-15 14:30:00" in prompt
        assert "UTC" in prompt

    def test_contains_timezone(self, now_utc, today_ev, week_ev, tool_defs):
        prompt = build_system_prompt(now_utc, "America/New_York", today_ev, week_ev, tool_defs)
        assert "America/New_York" in prompt

    def test_contains_today_events(self, now_utc, today_ev, week_ev, tool_defs):
        prompt = build_system_prompt(now_utc, "UTC", today_ev, week_ev, tool_defs)
        assert "Standup" in prompt
        assert "Today's Agenda" in prompt

    def test_contains_week_events(self, now_utc, today_ev, week_ev, tool_defs):
        prompt = build_system_prompt(now_utc, "UTC", today_ev, week_ev, tool_defs)
        assert "Sprint Planning" in prompt
        assert "Upcoming Week" in prompt

    def test_contains_tools(self, now_utc, today_ev, week_ev, tool_defs):
        prompt = build_system_prompt(now_utc, "UTC", today_ev, week_ev, tool_defs)
        assert "create_event" in prompt
        assert "list_events" in prompt

    def test_no_tools(self, now_utc, today_ev, week_ev):
        prompt = build_system_prompt(now_utc, "UTC", today_ev, week_ev, [])
        assert "(no tools available)" in prompt

    def test_no_events(self, now_utc, tool_defs):
        prompt = build_system_prompt(now_utc, "UTC", [], [], tool_defs)
        assert "(none)" in prompt

    def test_contains_guidelines(self, now_utc, today_ev, week_ev, tool_defs):
        prompt = build_system_prompt(now_utc, "UTC", today_ev, week_ev, tool_defs)
        assert "Guidelines" in prompt
        assert "Qwelio" in prompt

    def test_contains_calendar_context_section(self, now_utc, today_ev, week_ev, tool_defs):
        prompt = build_system_prompt(now_utc, "UTC", today_ev, week_ev, tool_defs)
        assert "Calendar Context" in prompt

    def test_contains_current_time_section(self, now_utc, today_ev, week_ev, tool_defs):
        prompt = build_system_prompt(now_utc, "UTC", today_ev, week_ev, tool_defs)
        assert "Current Time" in prompt

    def test_calendar_available_true(self, now_utc, today_ev, week_ev, tool_defs):
        prompt = build_system_prompt(now_utc, "UTC", today_ev, week_ev, tool_defs, calendar_available=True)
        assert "Calendar access: available" in prompt

    def test_calendar_available_false(self, now_utc, today_ev, week_ev, tool_defs):
        prompt = build_system_prompt(now_utc, "UTC", today_ev, week_ev, tool_defs, calendar_available=False)
        assert "Calendar access: unavailable" in prompt

    def test_calendar_available_default_true(self, now_utc, today_ev, week_ev, tool_defs):
        prompt = build_system_prompt(now_utc, "UTC", today_ev, week_ev, tool_defs)
        assert "Calendar access: available" in prompt


# --- _truncate ---

class TestTruncate:
    def test_no_truncation_when_short(self):
        assert _truncate("hello", 10) == "hello"

    def test_truncates_when_long(self):
        result = _truncate("a" * 300, 100)
        assert result.endswith("...")
        assert len(result) == 103

    def test_exact_length_no_truncation(self):
        assert _truncate("abc", 3) == "abc"


# --- DEFAULT_TIMEZONE ---

class TestDefaultTimezone:
    def test_default_is_utc(self):
        # After the reset_prompt_env fixture, USER_TIMEZONE is unset
        from prompt import DEFAULT_TIMEZONE
        assert DEFAULT_TIMEZONE == "UTC"

    def test_custom_timezone(self):
        with patch.dict(os.environ, {"USER_TIMEZONE": "America/Chicago"}):
            # Re-import to pick up new env
            import importlib
            import prompt
            importlib.reload(prompt)
            assert prompt.DEFAULT_TIMEZONE == "America/Chicago"
