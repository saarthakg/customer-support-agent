import json

from agent.llm import LLMResponse, ToolCall
from agent.loop import Agent
from agent.registry import Skill, Tool
from agent.trace import Tracer, redact
from tests.fakes import FakeLLM, echo_skill, text


def test_redact_masks_emails_at_any_depth():
    record = {
        "user": "it's John.Doe@Example.com, order W001",
        "tool_calls": [{"arguments": {"email": "jane.smith@example.com"}, "result": {"ok": True}}],
        "count": 3,
    }
    assert redact(record) == {
        "user": "it's J***@Example.com, order W001",
        "tool_calls": [{"arguments": {"email": "j***@example.com"}, "result": {"ok": True}}],
        "count": 3,
    }


def test_redact_leaves_non_emails_alone():
    assert redact("Track: https://tools.usps.com/go/TrackConfirmAction?tLabels=TRK1 #W001") == (
        "Track: https://tools.usps.com/go/TrackConfirmAction?tLabels=TRK1 #W001"
    )


def test_turn_record_ties_reply_to_config_and_masks_email(tmp_path):
    path = tmp_path / "trace.jsonl"
    llm = FakeLLM(
        LLMResponse(None, [ToolCall("c1", "echo", '{"word": "bob.brown@example.com"}')], 10, 5, 1),
        text("Done!"),
    )
    agent = Agent(llm, skills=[echo_skill()], tracer=Tracer(path, "sess1"))
    agent.respond("my email is bob.brown@example.com")

    record = json.loads(path.read_text().strip())
    assert record["session_id"] == "sess1"
    assert record["model"] == "fake-model" and record["temperature"] == 0.0
    assert record["prompt_hash"] == agent.prompt_hash and len(agent.prompt_hash) == 12
    assert record["supervisor"] == "pass" and record["supervisor_blocked"] == []
    assert record["outcome"] == "ok"
    assert "bob.brown@example.com" not in path.read_text()
    assert record["tool_calls"][0]["arguments"] == {"word": "b***@example.com"}


def test_prompt_hash_changes_when_tool_contract_changes():
    base = Agent(FakeLLM(), skills=[echo_skill()]).prompt_hash
    tool = echo_skill().tools[0]
    reworded = Skill("Echo", "Use echo when asked.", (Tool(tool.name, "Repeat a word.", tool.parameters, tool.handler),))
    assert Agent(FakeLLM(), skills=[reworded]).prompt_hash != base
    assert Agent(FakeLLM(), skills=[echo_skill()]).prompt_hash == base
