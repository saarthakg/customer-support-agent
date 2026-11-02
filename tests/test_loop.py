"""Loop mechanics against a scripted fake model: no network, fully deterministic."""

import json

import pytest

from agent.llm import LLMError, LLMResponse, ToolCall
from agent.loop import FALLBACK_REPLY, SUPERVISOR_FALLBACK_REPLY, Agent
from agent.prompt import build_system_prompt
from agent.registry import Deps, Skill, Tool, build_skills


class FakeLLM:
    """Returns pre-scripted responses in order and records what it was sent."""

    def __init__(self, *responses: LLMResponse | Exception) -> None:
        self.responses = list(responses)
        self.seen_messages: list[list[dict]] = []

    def complete(self, messages, tools):
        self.seen_messages.append([dict(m) for m in messages])
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def text(content: str) -> LLMResponse:
    return LLMResponse(content, [], 10, 5, 1)


def calls(*tool_calls: tuple[str, str]) -> LLMResponse:
    return LLMResponse(None, [ToolCall(f"call_{i}", n, a) for i, (n, a) in enumerate(tool_calls)], 10, 5, 1)


def echo_skill(handler=None) -> Skill:
    tool = Tool(
        name="echo",
        description="Echo a word.",
        parameters={"type": "object", "properties": {"word": {"type": "string"}}, "required": ["word"]},
        handler=handler or (lambda word: {"ok": True, "echo": word}),
    )
    return Skill(name="Echo", instructions="Use echo when asked.", tools=(tool,))


def test_plain_reply_without_tools():
    agent = Agent(FakeLLM(text("Hello, trail friend!")), skills=[])
    result = agent.respond("hi")
    assert result.reply == "Hello, trail friend!"
    assert result.outcome == "ok"
    assert agent.messages[-1] == {"role": "assistant", "content": "Hello, trail friend!"}


def test_tool_result_is_fed_back_to_model():
    llm = FakeLLM(calls(("echo", '{"word": "summit"}')), text("You said summit."))
    agent = Agent(llm, skills=[echo_skill()])
    result = agent.respond("echo summit")

    assert result.reply == "You said summit."
    assert [r.name for r in result.tool_calls] == ["echo"]
    assert result.tool_calls[0].result == {"ok": True, "echo": "summit"}
    tool_msg = llm.seen_messages[1][-1]
    assert tool_msg["role"] == "tool" and json.loads(tool_msg["content"])["echo"] == "summit"


@pytest.mark.parametrize(
    "name, raw_args, error",
    [
        ("nope", "{}", "unknown_tool"),
        ("echo", "{not json", "invalid_arguments"),
        ("echo", "[1, 2]", "invalid_arguments"),
        ("echo", "{}", "invalid_arguments"),  # missing required "word"
    ],
)
def test_bad_tool_calls_become_structured_errors(name, raw_args, error):
    agent = Agent(FakeLLM(calls((name, raw_args)), text("Recovered.")), skills=[echo_skill()])
    result = agent.respond("go")
    assert result.tool_calls[0].result["error"] == error
    assert result.reply == "Recovered."


def test_unknown_arguments_are_dropped_not_fatal():
    agent = Agent(FakeLLM(calls(("echo", '{"word": "a", "extra": 1}')), text("ok")), skills=[echo_skill()])
    assert agent.respond("go").tool_calls[0].result == {"ok": True, "echo": "a"}


def test_handler_exception_does_not_crash_the_turn():
    def boom(word):
        raise RuntimeError("bug")

    agent = Agent(FakeLLM(calls(("echo", '{"word": "a"}')), text("Sorry.")), skills=[echo_skill(boom)])
    result = agent.respond("go")
    assert result.tool_calls[0].result == {"ok": False, "error": "tool_failed"}
    assert result.outcome == "ok"


def test_iteration_cap_returns_fallback_and_rolls_back_history():
    looping = [calls(("echo", '{"word": "again"}')) for _ in range(3)]
    agent = Agent(FakeLLM(*looping), skills=[echo_skill()], max_tool_iterations=3)
    before = list(agent.messages)
    result = agent.respond("loop forever")
    assert result.outcome == "loop_limit"
    assert result.reply == FALLBACK_REPLY
    assert result.model_calls == 3
    assert agent.messages == before


def test_llm_error_returns_fallback_and_rolls_back_history():
    agent = Agent(FakeLLM(LLMError("timeout")), skills=[])
    before = list(agent.messages)
    result = agent.respond("hello?")
    assert result.outcome == "llm_error"
    assert result.reply == FALLBACK_REPLY
    assert agent.messages == before


def test_system_prompt_includes_each_skill_spec():
    prompt = build_system_prompt([echo_skill()])
    assert prompt.index("# Identity and voice") < prompt.index("# Rules") < prompt.index("# Skill: Echo")
    assert "Use echo when asked." in prompt


def test_registry_rejects_duplicate_tool_names():
    builder = lambda deps: echo_skill()  # noqa: E731
    with pytest.raises(ValueError, match="duplicate"):
        build_skills(Deps(datasets=None), builders=[builder, builder])


def test_greeting_does_not_advertise_promotions():
    # D-21: promotions are mentioned only when a customer asks about discounts.
    from agent.loop import GREETING

    assert not any(word in GREETING.lower() for word in ("promo", "discount", "early riser", "deal"))


# --- supervisor integration (P11) ---

BAD_LINK = "Browse here: https://www.sierraoutfitters.com/hiking-boots"


def test_supervisor_passes_clean_reply():
    result = Agent(FakeLLM(text("Happy trails!")), skills=[]).respond("hi")
    assert result.supervisor == "pass"
    assert result.supervisor_blocked == []


def test_supervisor_retries_once_with_correction_then_passes():
    llm = FakeLLM(text(BAD_LINK), text("I can't share a link for that here."))
    agent = Agent(llm, skills=[])
    result = agent.respond("boots?")

    assert result.reply == "I can't share a link for that here."
    assert result.outcome == "ok"
    assert result.supervisor == "retried"
    assert result.supervisor_blocked == ["blocked_url: https://www.sierraoutfitters.com/hiking-boots"]
    # The model saw a correction note in place of its bad draft; the draft never reaches history.
    retry_messages = llm.seen_messages[1]
    assert retry_messages[-1]["role"] == "system" and "sierraoutfitters.com" in retry_messages[-1]["content"]
    assert all(BAD_LINK not in str(m.get("content")) for m in agent.messages)


def test_supervisor_falls_back_after_second_block_and_rolls_back():
    agent = Agent(FakeLLM(text(BAD_LINK), text("Try sierraoutfitters.com/boots")), skills=[])
    before = list(agent.messages)
    result = agent.respond("boots?")

    assert result.reply == SUPERVISOR_FALLBACK_REPLY
    assert result.outcome == "supervisor_fallback"
    assert result.supervisor == "fallback"
    assert len(result.supervisor_blocked) == 2
    assert agent.messages == before


def test_supervisor_allows_links_returned_by_tools():
    url = "https://tools.usps.com/go/TrackConfirmAction?tLabels=TRK1"
    skill = echo_skill(lambda word: {"ok": True, "tracking_url": url})
    agent = Agent(FakeLLM(calls(("echo", '{"word": "x"}')), text(f"Track it:\n{url}")), skills=[skill])
    assert agent.respond("track").supervisor == "pass"
