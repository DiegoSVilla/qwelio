import pytest
from unittest.mock import patch, AsyncMock, Mock
from tools import ToolRegistry
from llm import LLMError
import llm


class TestToolRegistry:
    def setup_method(self):
        ToolRegistry.reset()

    def teardown_method(self):
        ToolRegistry.reset()

    def test_register_and_get_definitions(self):
        ToolRegistry.register(
            "test_tool",
            "A test tool",
            {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]},
            lambda x: x * 2,
        )
        defs = ToolRegistry.get_definitions()
        assert len(defs) == 1
        assert defs[0]["type"] == "function"
        assert defs[0]["function"]["name"] == "test_tool"
        assert defs[0]["function"]["description"] == "A test tool"

    def test_execute_sync_handler(self):
        ToolRegistry.register("double", "Double a number", {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}, lambda x: {"result": x * 2})
        import asyncio
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(ToolRegistry.execute("double", {"x": 5}))
        assert result == '{"result": 10}'
        loop.close()

    def test_execute_unknown_tool(self):
        import asyncio
        loop = asyncio.new_event_loop()
        with pytest.raises(KeyError, match="Unknown tool: nonexistent"):
            loop.run_until_complete(ToolRegistry.execute("nonexistent", {}))
        loop.close()

    def test_execute_async_handler(self):
        async def async_handler(x):
            return {"value": x + 1}
        ToolRegistry.register("async_tool", "Async tool", {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}, async_handler)
        import asyncio
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(ToolRegistry.execute("async_tool", {"x": 10}))
        assert result == '{"value": 11}'
        loop.close()

    def test_execute_timeout(self):
        async def slow_handler():
            await asyncio.sleep(20)
            return 1
        import asyncio
        ToolRegistry.register("slow", "Slow tool", {"type": "object", "properties": {}}, slow_handler)
        loop = asyncio.new_event_loop()
        with pytest.raises(RuntimeError, match="timed out"):
            loop.run_until_complete(ToolRegistry.execute("slow", {}))
        loop.close()

    def test_execute_non_serializable_result(self):
        """Tool returning datetime or other non-JSON-serializable types must fail loudly."""
        import asyncio
        from datetime import datetime, timezone
        def bad_handler():
            return {"time": datetime.now(timezone.utc)}
        ToolRegistry.register("bad", "Bad tool", {"type": "object", "properties": {}}, bad_handler)
        loop = asyncio.new_event_loop()
        with pytest.raises(RuntimeError, match="non-JSON-serializable"):
            loop.run_until_complete(ToolRegistry.execute("bad", {}))
        loop.close()

    def test_reset_clears_registry(self):
        ToolRegistry.register("a", "a", {"type": "object", "properties": {}}, lambda: None)
        assert len(ToolRegistry._tools) == 1
        ToolRegistry.reset()
        assert len(ToolRegistry._tools) == 0


class TestChatWithTools:
    @pytest.mark.asyncio
    async def test_no_tool_calls_returns_content(self):
        mock_resp = Mock()
        mock_resp.choices = [Mock(message=Mock(content="Hello", tool_calls=None))]
        with patch("llm._get_client") as mock_client_fn:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
            mock_client_fn.return_value = mock_client
            with patch("llm._get_model", return_value="test-model"):
                from llm import chat_with_tools
                content, new_msgs = await chat_with_tools([{"role": "user", "content": "hi"}], [])
                assert content == "Hello"
                assert len(new_msgs) == 1
                assert new_msgs[0]["content"] == "Hello"

    @pytest.mark.asyncio
    async def test_tool_call_injected_and_loops(self):
        mock_msg_with_tool = Mock()
        mock_tool_call = Mock()
        mock_tool_call.id = "call-1"
        mock_tool_call.function.name = "test_tool"
        mock_tool_call.function.arguments = '{"x": 1}'
        mock_tool_call.model_dump.return_value = {"id": "call-1", "function": {"name": "test_tool", "arguments": '{"x": 1}'}}
        mock_msg_with_tool.tool_calls = [mock_tool_call]
        mock_msg_with_tool.content = None

        mock_msg_final = Mock()
        mock_msg_final.tool_calls = None
        mock_msg_final.content = "Done!"

        mock_resp_tool = Mock()
        mock_resp_tool.choices = [Mock(message=mock_msg_with_tool)]
        mock_resp_final = Mock()
        mock_resp_final.choices = [Mock(message=mock_msg_final)]

        with patch("llm._get_client") as mock_client_fn:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(side_effect=[mock_resp_tool, mock_resp_final])
            mock_client_fn.return_value = mock_client
            with patch("llm._get_model", return_value="test-model"):
                with patch("tools.ToolRegistry.execute", new_callable=AsyncMock) as mock_exec:
                    mock_exec.return_value = '{"result": 42}'
                    from llm import chat_with_tools
                    content, new_msgs = await chat_with_tools([{"role": "user", "content": "hi"}], [])
                    assert content == "Done!"
                    mock_exec.assert_called_once_with("test_tool", {"x": 1})

    @pytest.mark.asyncio
    async def test_max_iterations_exceeded(self):
        mock_msg = Mock()
        mock_tool_call = Mock()
        mock_tool_call.id = "call-1"
        mock_tool_call.function.name = "loop_tool"
        mock_tool_call.function.arguments = "{}"
        mock_tool_call.model_dump.return_value = {"id": "call-1"}
        mock_msg.tool_calls = [mock_tool_call]
        mock_msg.content = None

        mock_resp = Mock()
        mock_resp.choices = [Mock(message=mock_msg)]

        with patch("llm._get_client") as mock_client_fn:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
            mock_client_fn.return_value = mock_client
            with patch("llm._get_model", return_value="test-model"):
                mock_s = Mock()
                mock_s.temperature = 0.6
                mock_s.max_tool_iterations = 2
                with patch.object(llm, "_get_settings", return_value=mock_s):
                    with patch("tools.ToolRegistry.execute", new_callable=AsyncMock) as mock_exec:
                        mock_exec.return_value = '{"ok": true}'
                        from llm import chat_with_tools
                        with pytest.raises(LLMError, match="exceeded"):
                            await chat_with_tools([{"role": "user", "content": "hi"}], [])

    @pytest.mark.asyncio
    async def test_invalid_json_args(self):
        mock_msg = Mock()
        mock_tool_call = Mock()
        mock_tool_call.id = "call-1"
        mock_tool_call.function.name = "bad_tool"
        mock_tool_call.function.arguments = "not-json"
        mock_tool_call.model_dump.return_value = {"id": "call-1"}
        mock_msg.tool_calls = [mock_tool_call]
        mock_msg.content = None

        mock_msg_final = Mock()
        mock_msg_final.tool_calls = None
        mock_msg_final.content = "Got it"

        mock_resp1 = Mock()
        mock_resp1.choices = [Mock(message=mock_msg)]
        mock_resp2 = Mock()
        mock_resp2.choices = [Mock(message=mock_msg_final)]

        with patch("llm._get_client") as mock_client_fn:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(side_effect=[mock_resp1, mock_resp2])
            mock_client_fn.return_value = mock_client
            with patch("llm._get_model", return_value="test-model"):
                with patch("tools.ToolRegistry.execute", new_callable=AsyncMock) as mock_exec:
                    from llm import chat_with_tools
                    content, new_msgs = await chat_with_tools([{"role": "user", "content": "hi"}], [])
                    assert content == "Got it"
                    mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_tool_error(self):
        mock_msg = Mock()
        mock_tool_call = Mock()
        mock_tool_call.id = "call-1"
        mock_tool_call.function.name = "unknown_tool"
        mock_tool_call.function.arguments = "{}"
        mock_tool_call.model_dump.return_value = {"id": "call-1"}
        mock_msg.tool_calls = [mock_tool_call]
        mock_msg.content = None

        mock_msg_final = Mock()
        mock_msg_final.tool_calls = None
        mock_msg_final.content = "OK"

        mock_resp1 = Mock()
        mock_resp1.choices = [Mock(message=mock_msg)]
        mock_resp2 = Mock()
        mock_resp2.choices = [Mock(message=mock_msg_final)]

        with patch("llm._get_client") as mock_client_fn:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(side_effect=[mock_resp1, mock_resp2])
            mock_client_fn.return_value = mock_client
            with patch("llm._get_model", return_value="test-model"):
                from llm import chat_with_tools
                content, new_msgs = await chat_with_tools([{"role": "user", "content": "hi"}], [])
                assert content == "OK"

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_single_message(self):
        mock_tool_call_1 = Mock()
        mock_tool_call_1.id = "call-1"
        mock_tool_call_1.function.name = "tool_a"
        mock_tool_call_1.function.arguments = '{"x": 1}'
        mock_tool_call_1.model_dump.return_value = {"id": "call-1"}

        mock_tool_call_2 = Mock()
        mock_tool_call_2.id = "call-2"
        mock_tool_call_2.function.name = "tool_b"
        mock_tool_call_2.function.arguments = '{"y": 2}'
        mock_tool_call_2.model_dump.return_value = {"id": "call-2"}

        mock_msg_with_tools = Mock()
        mock_msg_with_tools.tool_calls = [mock_tool_call_1, mock_tool_call_2]
        mock_msg_with_tools.content = None

        mock_msg_final = Mock()
        mock_msg_final.tool_calls = None
        mock_msg_final.content = "Both done"

        mock_resp1 = Mock()
        mock_resp1.choices = [Mock(message=mock_msg_with_tools)]
        mock_resp2 = Mock()
        mock_resp2.choices = [Mock(message=mock_msg_final)]

        with patch("llm._get_client") as mock_client_fn:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(side_effect=[mock_resp1, mock_resp2])
            mock_client_fn.return_value = mock_client
            with patch("llm._get_model", return_value="test-model"):
                with patch("tools.ToolRegistry.execute", new_callable=AsyncMock) as mock_exec:
                    mock_exec.side_effect = ['{"a": 1}', '{"b": 2}']
                    from llm import chat_with_tools
                    content, new_msgs = await chat_with_tools([{"role": "user", "content": "hi"}], [])
                    assert content == "Both done"
                    assert mock_exec.call_count == 2
                    assert mock_exec.call_args_list[0].args == ("tool_a", {"x": 1})
                    assert mock_exec.call_args_list[1].args == ("tool_b", {"y": 2})

    @pytest.mark.asyncio
    async def test_input_messages_not_mutated(self):
        original_messages = [{"role": "user", "content": "hi"}]
        mock_msg = Mock()
        mock_tool_call = Mock()
        mock_tool_call.id = "call-1"
        mock_tool_call.function.name = "test"
        mock_tool_call.function.arguments = "{}"
        mock_tool_call.model_dump.return_value = {"id": "call-1"}
        mock_msg.tool_calls = [mock_tool_call]
        mock_msg.content = None

        mock_msg_final = Mock()
        mock_msg_final.tool_calls = None
        mock_msg_final.content = "Done"

        mock_resp1 = Mock()
        mock_resp1.choices = [Mock(message=mock_msg)]
        mock_resp2 = Mock()
        mock_resp2.choices = [Mock(message=mock_msg_final)]

        with patch("llm._get_client") as mock_client_fn:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(side_effect=[mock_resp1, mock_resp2])
            mock_client_fn.return_value = mock_client
            with patch("llm._get_model", return_value="test-model"):
                with patch("tools.ToolRegistry.execute", new_callable=AsyncMock) as mock_exec:
                    mock_exec.return_value = '{"ok": true}'
                    from llm import chat_with_tools
                    await chat_with_tools(original_messages, [])
                    assert len(original_messages) == 1
                    assert original_messages == [{"role": "user", "content": "hi"}]
