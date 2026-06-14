import pytest
from unittest.mock import patch, AsyncMock

import summarizer


@pytest.fixture(autouse=True)
def reset_summarizer_cooldown():
    summarizer._last_summarize.clear()
    yield


class TestBuildSummaryPrompt:
    def test_basic_conversation(self):
        messages = [
            {"role": "user", "content": "Schedule a meeting"},
            {"role": "assistant", "content": "OK, I'll create it"},
        ]
        prompt = summarizer._build_summary_prompt(messages, "daily", "2025-01-01T00:00:00+00:00", "2025-01-02T00:00:00+00:00")
        assert len(prompt) == 2
        assert prompt[0]["role"] == "system"
        assert "memory summarizer" in prompt[0]["content"].lower()
        assert prompt[1]["role"] == "user"
        assert "user: Schedule a meeting" in prompt[1]["content"]
        assert "assistant: OK, I'll create it" in prompt[1]["content"]

    def test_includes_tool_calls(self):
        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"function": {"name": "create_event", "arguments": '{"summary":"Meeting"}'}}
                ],
            },
            {"role": "tool", "content": "Created"},
        ]
        prompt = summarizer._build_summary_prompt(messages, "daily", "2025-01-01T00:00:00+00:00", "2025-01-02T00:00:00+00:00")
        user_content = prompt[1]["content"]
        assert "create_event" in user_content
        assert "Meeting" in user_content

    def test_empty_conversation(self):
        messages = []
        prompt = summarizer._build_summary_prompt(messages, "daily", "2025-01-01T00:00:00+00:00", "2025-01-02T00:00:00+00:00")
        assert "(No conversations in this period)" in prompt[1]["content"]

    def test_monthly_prompt(self):
        prompt = summarizer._build_summary_prompt([], "monthly", "2025-01-01T00:00:00+00:00", "2025-01-31T23:59:59+00:00")
        assert "1 paragraph" in prompt[0]["content"]

    def test_weekly_prompt(self):
        prompt = summarizer._build_summary_prompt([], "weekly", "2025-01-01T00:00:00+00:00", "2025-01-07T23:59:59+00:00")
        assert "2 paragraphs" in prompt[0]["content"]

    def test_daily_prompt(self):
        prompt = summarizer._build_summary_prompt([], "daily", "2025-01-01T00:00:00+00:00", "2025-01-02T00:00:00+00:00")
        assert "3 paragraphs" in prompt[0]["content"]

    def test_filters_out_system_messages(self):
        messages = [
            {"role": "system", "content": "You are Qwelio"},
            {"role": "user", "content": "Hi"},
        ]
        prompt = summarizer._build_summary_prompt(messages, "daily", "2025-01-01T00:00:00+00:00", "2025-01-02T00:00:00+00:00")
        assert "You are Qwelio" not in prompt[1]["content"]
        assert "user: Hi" in prompt[1]["content"]

    def test_skips_empty_content(self):
        messages = [
            {"role": "user", "content": ""},
            {"role": "assistant", "content": "  "},
            {"role": "user", "content": "Real message"},
        ]
        prompt = summarizer._build_summary_prompt(messages, "daily", "2025-01-01T00:00:00+00:00", "2025-01-02T00:00:00+00:00")
        assert prompt[1]["content"].strip() == "user: Real message"


class TestGenerateSummary:
    @pytest.mark.asyncio
    async def test_calls_chat_with_prompt(self):
        with patch("storage.get_period_messages", new_callable=AsyncMock) as mock_msgs:
            with patch("summarizer.chat", new_callable=AsyncMock) as mock_chat:
                mock_msgs.return_value = [
                    {"role": "user", "content": "Hi"},
                    {"role": "assistant", "content": "Hello"},
                ]
                mock_chat.return_value = "Summary text"

                result = await summarizer.generate_summary("user1", "daily", "2025-01-01T00:00:00+00:00", "2025-01-02T00:00:00+00:00")

                assert result == "Summary text"
                mock_msgs.assert_called_once_with("user1", "2025-01-01T00:00:00+00:00", "2025-01-02T00:00:00+00:00")
                mock_chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_propagates_llm_error(self):
        from llm import LLMError
        with patch("storage.get_period_messages", new_callable=AsyncMock) as mock_msgs:
            with patch("summarizer.chat", new_callable=AsyncMock, side_effect=LLMError("API error")):
                mock_msgs.return_value = []
                with pytest.raises(LLMError, match="API error"):
                    await summarizer.generate_summary("user1", "daily", "2025-01-01T00:00:00+00:00", "2025-01-02T00:00:00+00:00")


class TestGenerateSummaries:
    @pytest.mark.asyncio
    async def test_generates_and_saves(self):
        with patch("storage.get_pending_summaries", new_callable=AsyncMock) as mock_pending:
            with patch("summarizer.generate_summary", new_callable=AsyncMock) as mock_gen:
                with patch("storage.save_summary", new_callable=AsyncMock) as mock_save:
                    mock_pending.return_value = [
                        ("daily", "2025-01-01T00:00:00+00:00", "2025-01-02T00:00:00+00:00"),
                        ("weekly", "2024-12-25T00:00:00+00:00", "2025-01-01T00:00:00+00:00"),
                    ]
                    mock_gen.return_value = "Summary"

                    results = await summarizer.generate_summaries("user1")

                    assert len(results) == 2
                    assert all(r["status"] == "ok" for r in results)
                    assert mock_save.call_count == 2

    @pytest.mark.asyncio
    async def test_handles_llm_error_per_summary(self):
        from llm import LLMError
        with patch("storage.get_pending_summaries", new_callable=AsyncMock) as mock_pending:
            with patch("summarizer.generate_summary", new_callable=AsyncMock, side_effect=LLMError("API error")):
                mock_pending.return_value = [
                    ("daily", "2025-01-01T00:00:00+00:00", "2025-01-02T00:00:00+00:00"),
                ]

                results = await summarizer.generate_summaries("user1")

                assert len(results) == 1
                assert results[0]["status"] == "error"
                assert "API error" in results[0]["error"]

    @pytest.mark.asyncio
    async def test_no_pending(self):
        with patch("storage.get_pending_summaries", new_callable=AsyncMock) as mock_pending:
            mock_pending.return_value = []
            results = await summarizer.generate_summaries("user1")
            assert results == []
