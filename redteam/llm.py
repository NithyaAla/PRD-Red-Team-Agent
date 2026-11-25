"""Thin LLM layer. Every call returns a validated Pydantic object.

Structured output is enforced with Anthropic tool use: we give the model exactly
one tool whose input schema is the Pydantic schema, and force it to call it.
"""
from __future__ import annotations

import copy
import os
from typing import Any, Callable, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = os.getenv("REDTEAM_MODEL", "claude-sonnet-5-5")


class LLM(Protocol):
    model: str
    usage: dict[str, int]

    async def structured(self, *, system: str, user: str, schema: type[T], tool_name: str, max_tokens: int = 8000) -> T: ...


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve $ref/$defs so the tool schema is a single self-contained object."""
    schema = copy.deepcopy(schema)
    defs = schema.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].split("/")[-1]
                resolved = walk(copy.deepcopy(defs[name]))
                extra = {k: v for k, v in node.items() if k != "$ref"}
                return {**resolved, **extra}
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


class AnthropicLLM:
    def __init__(self, model: str = DEFAULT_MODEL, temperature: float | None = None, max_retries: int = 2):
        try:
            from anthropic import AsyncAnthropic
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("pip install anthropic") from e
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it to your environment or .env file, or use --offline.")
        self.client = AsyncAnthropic(max_retries=4)
        self.model = model
        self.temperature = temperature
        self.max_retries = max_retries
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

    async def structured(self, *, system: str, user: str, schema: type[T], tool_name: str, max_tokens: int = 8000) -> T:
        tool = {
            "name": tool_name,
            "description": f"Submit your {tool_name.replace('_', ' ')}. You must call this tool exactly once.",
            "input_schema": _inline_refs(schema.model_json_schema()),
        }
        messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
        last_err: Exception | None = None

        for _ in range(self.max_retries + 1):
            kwargs: dict[str, Any] = dict(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                tools=[tool],
                tool_choice={"type": "tool", "name": tool_name},
            )
            if self.temperature is not None:
                kwargs["temperature"] = self.temperature
            resp = await self.client.messages.create(**kwargs)
            self.usage["calls"] += 1
            self.usage["input_tokens"] += resp.usage.input_tokens
            self.usage["output_tokens"] += resp.usage.output_tokens

            block = next((b for b in resp.content if b.type == "tool_use"), None)
            if block is None:
                last_err = RuntimeError(f"Model did not call {tool_name} (stop_reason={resp.stop_reason})")
                continue
            try:
                return schema.model_validate(block.input)
            except ValidationError as e:
                last_err = e
                # Feed the validation error back so the model can repair its output.
                messages = messages + [
                    {"role": "assistant", "content": resp.content},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "is_error": True,
                                "content": f"Schema validation failed, call {tool_name} again with a corrected payload:\n{e}",
                            }
                        ],
                    },
                ]
        raise RuntimeError(f"{tool_name} failed after retries: {last_err}")


class ScriptedLLM:
    """Deterministic fake for tests and demos: maps tool_name -> handler(system, user) -> dict | BaseModel."""

    def __init__(self, handlers: dict[str, Callable[[str, str], Any]], model: str = "scripted"):
        self.handlers = handlers
        self.model = model
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}
        self.calls: list[tuple[str, str, str]] = []

    async def structured(self, *, system: str, user: str, schema: type[T], tool_name: str, max_tokens: int = 8000) -> T:
        self.usage["calls"] += 1
        self.calls.append((tool_name, system, user))
        out = self.handlers[tool_name](system, user)
        return out if isinstance(out, schema) else schema.model_validate(out)
