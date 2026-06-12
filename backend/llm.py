from openai import OpenAI
from dotenv import load_dotenv
import os

load_dotenv()

client = OpenAI(
    base_url=os.getenv("QWEN_API_URL", "https://inference.beestorm.ai/v1"),
    api_key=os.getenv("QWEN_API_KEY"),
)

MODEL = os.getenv("MODEL_NAME", "google/gemma-4-12B-it-qat-w4a16-ct")


def chat(messages: list[dict]) -> str:
    resp = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0.6,
    )
    return resp.choices[0].message.content
