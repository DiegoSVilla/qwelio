import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import llm
from llm import chat, LLMError


@pytest.fixture
def mock_env():
    with patch.dict("os.environ", {
        "QWEN_API_URL": "https://test.example.com/v1",
        "QWEN_API_KEY": "test-key",
        "MODEL_NAME": "test-model",
    }):
        yield


class TestChat:
    @pytest.mark.asyncio
    async def test_chat_success(self, mock_env):
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content="Hello world"))]

        with patch("llm.AsyncOpenAI") as MockClient:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
            MockClient.return_value = mock_client

            result = await chat([{"role": "user", "content": "Hi"}])
            assert result == "Hello world"

    @pytest.mark.asyncio
    async def test_chat_empty_content_returns_empty(self, mock_env):
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content=None))]

        with patch("llm.AsyncOpenAI") as MockClient:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
            MockClient.return_value = mock_client

            result = await chat([{"role": "user", "content": "Hi"}])
            assert result == ""

    @pytest.mark.asyncio
    async def test_chat_no_choices_raises_llm_error(self, mock_env):
        mock_resp = MagicMock()
        mock_resp.choices = []

        with patch("llm.AsyncOpenAI") as MockClient:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
            MockClient.return_value = mock_client

            with pytest.raises(LLMError, match="Empty response"):
                await chat([{"role": "user", "content": "Hi"}])

    @pytest.mark.asyncio
    async def test_chat_connection_error(self, mock_env):
        from openai import APIConnectionError

        with patch("llm.AsyncOpenAI") as MockClient:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(
                side_effect=APIConnectionError(message="Connection refused", request=MagicMock())
            )
            MockClient.return_value = mock_client

            with pytest.raises(LLMError, match="Connection failed"):
                await chat([{"role": "user", "content": "Hi"}])

    @pytest.mark.asyncio
    async def test_chat_rate_limit_error(self, mock_env):
        from openai import RateLimitError

        with patch("llm.AsyncOpenAI") as MockClient:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(
                side_effect=RateLimitError("Rate limited", response=MagicMock(), body={})
            )
            MockClient.return_value = mock_client

            with pytest.raises(LLMError, match="Rate limited"):
                await chat([{"role": "user", "content": "Hi"}])

    def test_no_api_key_raises(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(RuntimeError, match="QWEN_API_KEY not set"):
                _ = llm._get_client()

    @pytest.mark.asyncio
    async def test_chat_passes_correct_params(self, mock_env):
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content="OK"))]

        with patch("llm.AsyncOpenAI") as MockClient:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
            MockClient.return_value = mock_client

            await chat([{"role": "system", "content": "Be nice"}, {"role": "user", "content": "Hi"}])

            mock_client.chat.completions.create.assert_called_once_with(
                model="test-model",
                messages=[{"role": "system", "content": "Be nice"}, {"role": "user", "content": "Hi"}],
                temperature=0.6,
            )
