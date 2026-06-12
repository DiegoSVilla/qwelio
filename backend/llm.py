from openai import AsyncOpenAI, APIConnectionError, RateLimitError, APIStatusError
from dotenv import load_dotenv
from pathlib import Path
import os

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


class LLMError(Exception):
    pass


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
