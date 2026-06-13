# Issue #6: Configurable Inference Settings (max context, model, temperature)

## Functional Requirements
- Admin can configure LLM inference settings without code changes
- Configurable: model name, temperature, max context turns, API timeout, max retries
- Settings stored in `.env` with sensible defaults
- Settings can be changed at runtime via admin API (optional, phase 2)

## Current State
- Model name read from `.env` `MODEL_NAME` in `_get_model()`
- Temperature hardcoded to 0.6 in `chat()`
- Timeout hardcoded to 30s in `_get_client()`
- Max retries hardcoded to 2
- Max context turns hardcoded to 20 in `app.js`

## Technical Implementation

### Settings Model (`backend/settings.py`)
```python
import os

class InferenceSettings:
    def __init__(self):
        self.model_name = os.getenv("MODEL_NAME", "google/gemma-4-12B-it-qat-w4a16-ct")
        self.temperature = float(os.getenv("LLM_TEMPERATURE", "0.6"))
        self.timeout = float(os.getenv("LLM_TIMEOUT", "30.0"))
        self.max_retries = int(os.getenv("LLM_MAX_RETRIES", "2"))
        self.max_context_turns = int(os.getenv("MAX_CONTEXT_TURNS", "20"))
        self.max_tool_iterations = int(os.getenv("MAX_TOOL_ITERATIONS", "5"))

settings = InferenceSettings()
```

### Updated `.env`
```env
MODEL_NAME=google/gemma-4-12B-it-qat-w4a16-ct
LLM_TEMPERATURE=0.6
LLM_TIMEOUT=30.0
LLM_MAX_RETRIES=2
MAX_CONTEXT_TURNS=20
MAX_TOOL_ITERATIONS=5
```

### Modified `llm.py`
```python
from settings import settings

def _get_client():
    api_key = os.getenv("QWEN_API_KEY")
    if not api_key:
        raise RuntimeError("QWEN_API_KEY not set")
    return AsyncOpenAI(
        base_url=os.getenv("QWEN_API_URL", "https://inference.beestorm.ai/v1"),
        api_key=api_key,
        timeout=settings.timeout,
        max_retries=settings.max_retries,
    )

def _get_model():
    return settings.model_name

async def chat(messages: list[dict]) -> str:
    client = _get_client()
    model = _get_model()
    resp = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=settings.temperature,
    )
    # ... rest unchanged
```

### Modified `app.js` (frontend)
- Fetch `MAX_CONTEXT_TURNS` from backend on startup: `GET /api/settings` → use for `chatHistory.slice(-max_turns)`

### Admin API (phase 2, optional)
```python
@app.get("/api/settings")
async def get_settings(user: User = Depends(get_current_user)):
    return {
        "model_name": settings.model_name,
        "temperature": settings.temperature,
        "max_context_turns": settings.max_context_turns,
        "max_tool_iterations": settings.max_tool_iterations,
    }
```

## Acceptance Criteria
- [ ] All inference settings read from `.env` with defaults
- [ ] `LLM_TEMPERATURE` controls chat temperature
- [ ] `LLM_TIMEOUT` controls API timeout
- [ ] `LLM_MAX_RETRIES` controls retry count
- [ ] `MAX_CONTEXT_TURNS` controls conversation history length
- [ ] `MAX_TOOL_ITERATIONS` controls tool loop max iterations
- [ ] `GET /api/settings` returns current settings (requires auth)
- [ ] Settings changes require server restart (env vars) — runtime API is phase 2
- [ ] Tests: settings defaults, env override, invalid values, settings endpoint
