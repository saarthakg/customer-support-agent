"""Test doubles shared across test modules: a scripted model and a trivial skill."""

import json
from collections.abc import Callable

from agent.llm import LLMResponse, ToolCall
from agent.registry import Skill, Tool


class FakeLLM:
    """Returns pre-scripted responses in order and records what it was sent.

    A scripted item may also be a function of the messages so far, for replies that
    depend on what a tool returned (e.g. a randomly generated ticket ID).
    """

    model = "fake-model"
    temperature = 0.0

    def __init__(self, *responses: LLMResponse | Exception | Callable[[list[dict]], LLMResponse]) -> None:
        self.responses = list(responses)
        self.seen_messages: list[list[dict]] = []

    def complete(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        self.seen_messages.append([dict(m) for m in messages])
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item(messages) if callable(item) else item


def text(content: str) -> LLMResponse:
    return LLMResponse(content, [], 10, 5, 1)


def calls(*tool_calls: tuple[str, str]) -> LLMResponse:
    return LLMResponse(None, [ToolCall(f"call_{i}", n, a) for i, (n, a) in enumerate(tool_calls)], 10, 5, 1)


def echo_skill(handler: Callable[..., dict] | None = None) -> Skill:
    tool = Tool(
        name="echo",
        description="Echo a word.",
        parameters={"type": "object", "properties": {"word": {"type": "string"}}, "required": ["word"]},
        handler=handler or (lambda word: {"ok": True, "echo": word}),
    )
    return Skill(name="Echo", instructions="Use echo when asked.", tools=(tool,))


def last_tool_result(messages: list[dict]) -> dict:
    return json.loads(messages[-1]["content"])
