import json
import os

from openai import AsyncOpenAI, APIConnectionError, RateLimitError, APIStatusError
from dotenv import load_dotenv
from pathlib import Path

from tools import ToolRegistry

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


class LLMError(Exception):
    pass


MAX_TOOL_ITERATIONS = int(os.getenv("MAX_TOOL_ITERATIONS", "5"))


def _get_client():
    api_key = os.getenv("QWEN_API_KEY")
    if not api_key:
        raise RuntimeError("QWEN_API_KEY not set")
    return AsyncOpenAI(
        base_url=os.getenv("QWEN_API_URL", "https://inference.beestorm.ai/v1"),
        api_key=api_key,
        timeout=30.0,
        max_retries=2,
    )


def _get_model():
    return os.getenv("MODEL_NAME", "google/gemma-4-12B-it-qat-w4a16-ct")


async def chat(messages: list[dict]) -> str:
    client = _get_client()
    model = _get_model()
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.6,
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


async def chat_with_tools(messages: list[dict], tool_definitions: list[dict]) -> str:
    """Execute the tool call loop. Never mutates the input messages list."""
    client = _get_client()
    model = _get_model()

    working_messages = list(messages)

    for iteration in range(MAX_TOOL_ITERATIONS):
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=working_messages,
                temperature=0.6,
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
                except KeyError as e:
                    result = f"Error: {e}"
                except Exception as e:
                    result = f"Error: {e}"

                tool_results.append((tool_call.id, result))

            working_messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": tool_call_dumps,
            })

            for tool_call_id, result in tool_results:
                working_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": result,
                })
        else:
            return message.content or ""

    raise LLMError(f"Tool loop exceeded {MAX_TOOL_ITERATIONS} iterations")
