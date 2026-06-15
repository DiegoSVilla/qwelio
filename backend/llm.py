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
    client = _get_client()
    model = _get_model()
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=s.temperature,
        )
        if not resp.choices:
            raise LLMError("Empty response from LLM")
        return resp.choices[0].message.content or ""
    except APIConnectionError as e:
        raise LLMError(f"Connection failed: {e}")
    except RateLimitError as e:
        raise LLMError(f"Rate limited: {e}")
    except APIStatusError as e:
        raise LLMError(f"API error {e.status_code}: {e.message}")


async def chat_with_tools(messages: list[dict], tool_definitions: list[dict]) -> tuple[str, list[dict]]:
    """Execute the tool call loop. Never mutates the input messages list.

    Returns (content, new_messages) where new_messages contains all assistant/tool
    messages generated during the tool call loop for persistence.
    """
    s = _get_settings()
    client = _get_client()
    model = _get_model()

    working_messages = list(messages)
    new_messages = []

    for iteration in range(s.max_tool_iterations):
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=working_messages,
                temperature=s.temperature,
                tools=tool_definitions,
            )
        except APIConnectionError as e:
            raise LLMError(f"Connection failed: {e}")
        except RateLimitError as e:
            raise LLMError(f"Rate limited: {e}")
        except APIStatusError as e:
            raise LLMError(f"API error {e.status_code}: {e.message}")

        if not resp.choices:
            raise LLMError("Empty response from LLM")

        message = resp.choices[0].message

        if message.tool_calls:
            tool_results = []
            tool_call_dumps = []

            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                tool_call_dumps.append(tool_call.model_dump())

                try:
                    arguments = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    result = f"Error: Invalid JSON in tool arguments for {tool_name}"
                    tool_results.append((tool_call.id, result))
                    continue

                try:
                    result = await ToolRegistry.execute(tool_name, arguments)
                except KeyError:
                    result = "Error: Tool not found"
                except LLMError as e:
                    result = f"Error: {e}"
                except Exception:
                    result = f"Error: Tool {tool_name} failed"

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
        else:
            new_messages.append({
                "role": "assistant",
                "content": message.content,
                "tool_calls": None,
                "tool_call_id": None,
            })
            return message.content or "", new_messages

    raise LLMError(f"Tool loop exceeded {s.max_tool_iterations} iterations")
