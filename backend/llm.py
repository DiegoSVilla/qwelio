import json
import os

from openai import AsyncOpenAI, APIConnectionError, RateLimitError, APIStatusError
from dotenv import load_dotenv
from pathlib import Path

from tools import ToolRegistry

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


class LLMError(Exception):
    pass


def _get_settings():
    """Lazy import to pick up reloaded settings singleton in tests."""
    from settings import settings
    return settings


def _get_client():
    s = _get_settings()
    api_key = os.getenv("QWEN_API_KEY")
    if not api_key:
        raise RuntimeError("QWEN_API_KEY not set")
    return AsyncOpenAI(
        base_url=os.getenv("QWEN_API_URL", "https://inference.beestorm.ai/v1"),
        api_key=api_key,
        timeout=s.timeout,
        max_retries=s.max_retries,
    )


def _get_model():
    return _get_settings().model_name


async def chat(messages: list[dict]) -> str:
    s = _get_settings()
    print(f"[QW-L001] chat: start, model={_get_model()}, messages={len(messages)}, temp={s.temperature}")
    client = _get_client()
    model = _get_model()
    try:
        print("[QW-L002] chat: calling LLM API")
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=s.temperature,
        )
        print(f"[QW-L003] chat: response received, choices={len(resp.choices) if resp.choices else 0}")
        if not resp.choices:
            raise LLMError("Empty response from LLM")
        content = resp.choices[0].message.content or ""
        print(f"[QW-L004] chat: success, content length={len(content)}")
        return content
    except APIConnectionError as e:
        print(f"[QW-L005] chat: APIConnectionError: {e}")
        raise LLMError(f"Connection failed: {e}")
    except RateLimitError as e:
        print(f"[QW-L006] chat: RateLimitError: {e}")
        raise LLMError(f"Rate limited: {e}")
    except APIStatusError as e:
        print(f"[QW-L007] chat: APIStatusError {e.status_code}: {e.message}")
        raise LLMError(f"API error {e.status_code}: {e.message}")


async def chat_with_tools(messages: list[dict], tool_definitions: list[dict]) -> tuple[str, list[dict]]:
    """Execute the tool call loop. Never mutates the input messages list.

    Returns (content, new_messages) where new_messages contains all assistant/tool
    messages generated during the tool call loop for persistence.
    """
    s = _get_settings()
    client = _get_client()
    model = _get_model()

    print(f"[QW-L010] chat_with_tools: start, model={model}, messages={len(messages)}, tools={len(tool_definitions)}, max_iter={s.max_tool_iterations}")
    working_messages = list(messages)
    new_messages = []

    for iteration in range(s.max_tool_iterations):
        print(f"[QW-L011] chat_with_tools: iteration {iteration + 1}/{s.max_tool_iterations}, working_messages={len(working_messages)}")
        try:
            print(f"[QW-L012] chat_with_tools: calling LLM API (iteration {iteration + 1})")
            resp = await client.chat.completions.create(
                model=model,
                messages=working_messages,
                temperature=s.temperature,
                tools=tool_definitions,
            )
            print(f"[QW-L013] chat_with_tools: LLM response received (iteration {iteration + 1})")
        except APIConnectionError as e:
            print(f"[QW-L014] chat_with_tools: APIConnectionError (iteration {iteration + 1}): {e}")
            raise LLMError(f"Connection failed: {e}")
        except RateLimitError as e:
            print(f"[QW-L015] chat_with_tools: RateLimitError (iteration {iteration + 1}): {e}")
            raise LLMError(f"Rate limited: {e}")
        except APIStatusError as e:
            print(f"[QW-L016] chat_with_tools: APIStatusError (iteration {iteration + 1}) {e.status_code}: {e.message}")
            raise LLMError(f"API error {e.status_code}: {e.message}")

        if not resp.choices:
            print(f"[QW-L017] chat_with_tools: empty response (iteration {iteration + 1})")
            raise LLMError("Empty response from LLM")

        message = resp.choices[0].message

        if message.tool_calls:
            print(f"[QW-L018] chat_with_tools: tool_calls detected ({len(message.tool_calls)} calls, iteration {iteration + 1})")
            tool_results = []
            tool_call_dumps = []

            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                tool_call_dumps.append(tool_call.model_dump())
                print(f"[QW-L019] chat_with_tools: executing tool '{tool_name}'")

                try:
                    arguments = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    result = f"Error: Invalid JSON in tool arguments for {tool_name}"
                    print(f"[QW-L020] chat_with_tools: tool '{tool_name}' INVALID JSON args")
                    tool_results.append((tool_call.id, result))
                    continue

                try:
                    result = await ToolRegistry.execute(tool_name, arguments)
                    print(f"[QW-L021] chat_with_tools: tool '{tool_name}' success, result length={len(str(result))}")
                except KeyError as e:
                    result = f"Error: Tool not found: {e}"
                    print(f"[QW-L022] chat_with_tools: tool '{tool_name}' NOT FOUND: {e}")
                except LLMError as e:
                    result = f"Error: {e}"
                    print(f"[QW-L023] chat_with_tools: tool '{tool_name}' LLMError: {e}")
                except Exception as e:
                    result = f"Error: Tool {tool_name} failed: {type(e).__name__}: {e}"
                    print(f"[QW-L024] chat_with_tools: tool '{tool_name}' EXCEPTION: {type(e).__name__}: {e}")

                tool_results.append((tool_call.id, result))

            assistant_msg = {
                "role": "assistant",
                "content": None,
                "tool_calls": tool_call_dumps,
            }
            working_messages.append(assistant_msg)
            new_messages.append(assistant_msg)

            for tool_call_id, result in tool_results:
                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": result,
                }
                working_messages.append(tool_msg)
                new_messages.append(tool_msg)

            print(f"[QW-L025] chat_with_tools: iteration {iteration + 1} complete, working_messages={len(working_messages)}, new_messages={len(new_messages)}")
        else:
            print(f"[QW-L026] chat_with_tools: final text response (iteration {iteration + 1}), content length={len(message.content) if message.content else 0}")
            new_messages.append({
                "role": "assistant",
                "content": message.content,
                "tool_calls": None,
                "tool_call_id": None,
            })
            return message.content or "", new_messages

    print(f"[QW-L027] chat_with_tools: EXCEEDED max iterations ({s.max_tool_iterations})")
    raise LLMError(f"Tool loop exceeded {s.max_tool_iterations} iterations")
