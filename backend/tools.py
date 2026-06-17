import json
import asyncio
import inspect

from pydantic import BaseModel
from typing import Callable


class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: dict


class ToolRegistry:
    _tools: dict[str, ToolDefinition] = {}
    _handlers: dict[str, Callable] = {}

    @classmethod
    def register(cls, name: str, description: str, parameters: dict, handler: Callable):
        cls._tools[name] = ToolDefinition(name=name, description=description, parameters=parameters)
        cls._handlers[name] = handler

    @classmethod
    def get_definitions(cls) -> list[dict]:
        return [{"type": "function", "function": t.model_dump()} for t in cls._tools.values()]

    @classmethod
    async def execute(cls, name: str, arguments: dict) -> str:
        if name not in cls._handlers:
            raise KeyError(f"Unknown tool: {name}")
        handler = cls._handlers[name]
        try:
            if inspect.iscoroutinefunction(handler):
                result = await asyncio.wait_for(handler(**arguments), timeout=30.0)
            else:
                coro = asyncio.to_thread(handler, **arguments)
                result = await asyncio.wait_for(coro, timeout=30.0)
            if isinstance(result, dict):
                try:
                    return json.dumps(result)
                except (TypeError, ValueError) as e:
                    raise RuntimeError(f"Tool {name} returned non-JSON-serializable result: {e}") from e
            return str(result)
        except asyncio.TimeoutError:
            raise RuntimeError(f"Tool {name} timed out after 10s")

    @classmethod
    def reset(cls):
        cls._tools.clear()
        cls._handlers.clear()
