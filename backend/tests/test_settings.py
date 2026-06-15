import pytest
import os
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport
from settings import settings, InferenceSettings


class TestInferenceSettingsDefaults:
    def test_default_model_name(self):
        with patch.dict(os.environ, {}, clear=True):
            s = InferenceSettings()
            assert s.model_name == "google/gemma-4-12B-it-qat-w4a16-ct"

    def test_default_temperature(self):
        with patch.dict(os.environ, {}, clear=True):
            s = InferenceSettings()
            assert s.temperature == 0.6

    def test_default_timeout(self):
        with patch.dict(os.environ, {}, clear=True):
            s = InferenceSettings()
            assert s.timeout == 30.0

    def test_default_max_retries(self):
        with patch.dict(os.environ, {}, clear=True):
            s = InferenceSettings()
            assert s.max_retries == 2

    def test_default_max_context_turns(self):
        with patch.dict(os.environ, {}, clear=True):
            s = InferenceSettings()
            assert s.max_context_turns == 20

    def test_default_max_tool_iterations(self):
        with patch.dict(os.environ, {}, clear=True):
            s = InferenceSettings()
            assert s.max_tool_iterations == 5


class TestInferenceSettingsEnvOverride:
    def test_model_name_override(self):
        with patch.dict(os.environ, {"MODEL_NAME": "claude-4"}):
            s = InferenceSettings()
            assert s.model_name == "claude-4"

    def test_temperature_override(self):
        with patch.dict(os.environ, {"LLM_TEMPERATURE": "0.9"}):
            s = InferenceSettings()
            assert s.temperature == 0.9

    def test_timeout_override(self):
        with patch.dict(os.environ, {"LLM_TIMEOUT": "60.0"}):
            s = InferenceSettings()
            assert s.timeout == 60.0

    def test_max_retries_override(self):
        with patch.dict(os.environ, {"LLM_MAX_RETRIES": "5"}):
            s = InferenceSettings()
            assert s.max_retries == 5

    def test_max_context_turns_override(self):
        with patch.dict(os.environ, {"MAX_CONTEXT_TURNS": "50"}):
            s = InferenceSettings()
            assert s.max_context_turns == 50

    def test_max_tool_iterations_override(self):
        with patch.dict(os.environ, {"MAX_TOOL_ITERATIONS": "10"}):
            s = InferenceSettings()
            assert s.max_tool_iterations == 10


class TestInferenceSettingsInvalidValues:
    def test_invalid_temperature_raises(self):
        with patch.dict(os.environ, {"LLM_TEMPERATURE": "not-a-number"}):
            with pytest.raises(ValueError):
                InferenceSettings()

    def test_invalid_timeout_raises(self):
        with patch.dict(os.environ, {"LLM_TIMEOUT": "bad"}):
            with pytest.raises(ValueError):
                InferenceSettings()

    def test_invalid_max_retries_raises(self):
        with patch.dict(os.environ, {"LLM_MAX_RETRIES": "abc"}):
            with pytest.raises(ValueError):
                InferenceSettings()

    def test_invalid_max_context_turns_raises(self):
        with patch.dict(os.environ, {"MAX_CONTEXT_TURNS": "xyz"}):
            with pytest.raises(ValueError):
                InferenceSettings()

    def test_invalid_max_tool_iterations_raises(self):
        with patch.dict(os.environ, {"MAX_TOOL_ITERATIONS": "abc"}):
            with pytest.raises(ValueError):
                InferenceSettings()

    def test_negative_temperature_raises(self):
        with patch.dict(os.environ, {"LLM_TEMPERATURE": "-0.5"}):
            with pytest.raises(ValueError, match="temperature"):
                InferenceSettings()

    def test_temperature_over_2_raises(self):
        with patch.dict(os.environ, {"LLM_TEMPERATURE": "3.0"}):
            with pytest.raises(ValueError, match="temperature"):
                InferenceSettings()

    def test_zero_timeout_raises(self):
        with patch.dict(os.environ, {"LLM_TIMEOUT": "0"}):
            with pytest.raises(ValueError, match="timeout"):
                InferenceSettings()

    def test_negative_timeout_raises(self):
        with patch.dict(os.environ, {"LLM_TIMEOUT": "-1"}):
            with pytest.raises(ValueError, match="timeout"):
                InferenceSettings()

    def test_negative_max_retries_raises(self):
        with patch.dict(os.environ, {"LLM_MAX_RETRIES": "-1"}):
            with pytest.raises(ValueError, match="max_retries"):
                InferenceSettings()

    def test_zero_max_context_turns_raises(self):
        with patch.dict(os.environ, {"MAX_CONTEXT_TURNS": "0"}):
            with pytest.raises(ValueError, match="max_context_turns"):
                InferenceSettings()

    def test_zero_max_tool_iterations_raises(self):
        with patch.dict(os.environ, {"MAX_TOOL_ITERATIONS": "0"}):
            with pytest.raises(ValueError, match="max_tool_iterations"):
                InferenceSettings()

    def test_empty_model_name_raises(self):
        with patch.dict(os.environ, {"MODEL_NAME": ""}):
            with pytest.raises(ValueError, match="model_name"):
                InferenceSettings()


class TestLLMUsesSettings:
    def test_get_client_uses_settings_timeout(self):
        import llm as llm_mod
        with patch.object(settings, "timeout", 45.0):
            with patch.object(settings, "max_retries", 3):
                with patch.dict(os.environ, {"QWEN_API_KEY": "test-key"}):
                    with patch.object(llm_mod, "AsyncOpenAI") as MockClient:
                        MockClient.return_value = AsyncMock()
                        llm_mod._get_client()
                        MockClient.assert_called_once()
                        call_kwargs = MockClient.call_args[1]
                        assert call_kwargs["timeout"] == 45.0
                        assert call_kwargs["max_retries"] == 3

    def test_chat_uses_settings_temperature(self):
        import llm as llm_mod
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content="OK"))]
        with patch.object(settings, "temperature", 0.95):
            with patch("llm.AsyncOpenAI") as MockClient:
                mock_client = AsyncMock()
                mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
                MockClient.return_value = mock_client
                with patch.dict(os.environ, {"QWEN_API_KEY": "test-key"}):
                    import asyncio
                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(llm_mod.chat([{"role": "user", "content": "hi"}]))
                    loop.close()
                    call_kwargs = mock_client.chat.completions.create.call_args[1]
                    assert call_kwargs["temperature"] == 0.95

    def test_chat_with_tools_uses_settings_iterations(self):
        import llm as llm_mod
        mock_msg = MagicMock()
        mock_msg.tool_calls = []
        mock_msg.content = "Done"
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=mock_msg)]
        with patch.object(settings, "max_tool_iterations", 3):
            with patch("llm.AsyncOpenAI") as MockClient:
                mock_client = AsyncMock()
                mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
                MockClient.return_value = mock_client
                with patch.dict(os.environ, {"QWEN_API_KEY": "test-key"}):
                    import asyncio
                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(llm_mod.chat_with_tools([{"role": "user", "content": "hi"}], []))
                    loop.close()


class TestSettingsEndpoint:
    @pytest.fixture
    async def client(self, app_no_calendar):
        transport = ASGITransport(app=app_no_calendar)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    @pytest.fixture
    async def auth_client(self, app_no_calendar):
        transport = ASGITransport(app=app_no_calendar)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            await c.post("/api/auth/login", json={"username": "admin", "password": "lels1234"})
            yield c

    @pytest.mark.asyncio
    async def test_settings_unauthenticated(self, client):
        resp = await client.get("/api/settings")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_settings_authenticated(self, auth_client):
        resp = await auth_client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "model_name" in data
        assert "temperature" in data
        assert "timeout" in data
        assert "max_retries" in data
        assert "max_context_turns" in data
        assert "max_tool_iterations" in data

    @pytest.mark.asyncio
    async def test_settings_returns_correct_values(self, auth_client):
        resp = await auth_client.get("/api/settings")
        data = resp.json()
        assert data["temperature"] == settings.temperature
        assert data["timeout"] == settings.timeout
        assert data["max_retries"] == settings.max_retries
        assert data["max_context_turns"] == settings.max_context_turns
        assert data["max_tool_iterations"] == settings.max_tool_iterations
