"""Thin wrapper around the OpenAI client. This is the only module that imports `openai`.

Swapping providers or models means changing this file (and config), nothing else.
"""

import json
import time
from dataclasses import dataclass, field

import openai

from agent import config


class LLMError(Exception):
    """Raised when the model can't be reached after retries. The loop turns this into a friendly fallback."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON string, exactly as the model produced it; parsed by the loop


@dataclass(frozen=True)
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall]
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


@dataclass
class TokenUsage:
    prompt: int = 0
    completion: int = 0
    calls: int = 0


@dataclass
class LLM:
    model: str = config.MODEL
    temperature: float = config.TEMPERATURE
    usage: TokenUsage = field(default_factory=TokenUsage)

    def __post_init__(self) -> None:
        # Reads OPENAI_API_KEY from the environment. Retries/backoff and timeouts are
        # handled by the client itself on 429s, 5xx and connection errors.
        self._client = openai.OpenAI(timeout=config.REQUEST_TIMEOUT_S, max_retries=config.MAX_RETRIES)

    def complete(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        start = time.monotonic()
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                messages=messages,
                # The API rejects an empty tools list, so omit it when no skills are enabled.
                **({"tools": tools} if tools else {}),
            )
        except openai.OpenAIError as e:
            raise LLMError(str(e)) from e
        latency_ms = int((time.monotonic() - start) * 1000)

        message = resp.choices[0].message
        tool_calls = [
            ToolCall(id=tc.id, name=tc.function.name, arguments=tc.function.arguments)
            for tc in (message.tool_calls or [])
        ]
        prompt_tokens = resp.usage.prompt_tokens if resp.usage else 0
        completion_tokens = resp.usage.completion_tokens if resp.usage else 0
        self.usage.prompt += prompt_tokens
        self.usage.completion += completion_tokens
        self.usage.calls += 1
        return LLMResponse(message.content, tool_calls, prompt_tokens, completion_tokens, latency_ms)


def assistant_message(response: LLMResponse) -> dict:
    """The history entry for a model response, in the shape the Chat Completions API expects back."""
    msg: dict = {"role": "assistant", "content": response.content}
    if response.tool_calls:
        msg["tool_calls"] = [
            {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": tc.arguments}}
            for tc in response.tool_calls
        ]
    return msg


def tool_result_message(call_id: str, result: dict) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": json.dumps(result)}
