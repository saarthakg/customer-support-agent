"""The CLI loop end to end, with a scripted model: blank lines, exit words, Ctrl-D and Ctrl-C."""

import sys

import pytest

import agent.main as cli
from agent import config
from tests.fakes import FakeLLM, text


def interrupt(messages):
    raise KeyboardInterrupt


@pytest.fixture
def run_cli(monkeypatch, tmp_path, capsys):
    """Run main() with scripted keyboard input; returns (exit code, stdout, the fake model)."""

    def run(inputs: list, *responses):
        llm = FakeLLM(*responses)
        script = iter(inputs)

        def fake_input(prompt=""):
            item = next(script)
            if isinstance(item, BaseException):
                raise item
            return item

        monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
        monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
        monkeypatch.setattr(cli, "LLM", lambda: llm)
        monkeypatch.setattr(config, "TRACE_LOG", tmp_path / "trace.jsonl")
        monkeypatch.setattr(config, "HANDOFF_LOG", tmp_path / "handoffs.jsonl")
        monkeypatch.setattr(config, "CODE_STORE", tmp_path / "issued_codes.json")
        monkeypatch.setattr(sys, "argv", ["agent.main"])
        monkeypatch.setattr("builtins.input", fake_input)
        code = cli.main()
        return code, capsys.readouterr().out, llm

    return run


def test_blank_lines_are_skipped_and_eof_exits_cleanly(run_cli):
    code, out, llm = run_cli(["", "   ", "hello", EOFError()], text("Hi there!"))
    assert code == 0
    assert len(llm.seen_messages) == 1  # only "hello" reached the model
    assert "Switchback: Hi there!" in out and out.rstrip().endswith("Happy trails! 🌲")


@pytest.mark.parametrize("word", ["exit", "QUIT", "bye"])
def test_exit_words_end_the_chat_without_a_model_call(run_cli, word):
    code, out, llm = run_cli([word])
    assert code == 0 and llm.seen_messages == []


def test_ctrl_c_at_the_prompt_exits_cleanly(run_cli):
    code, out, _ = run_cli([KeyboardInterrupt()])
    assert code == 0 and "Happy trails!" in out


def test_ctrl_c_while_the_agent_is_answering_exits_cleanly(run_cli):
    code, out, _ = run_cli(["where's my order?"], interrupt)
    assert code == 0 and "Happy trails!" in out


def test_missing_api_key_prints_the_fix(monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["agent.main"])
    assert cli.main() == 1
    assert "OPENAI_API_KEY is not set" in capsys.readouterr().err


def test_bad_data_dir_prints_a_clear_error(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)  # empty: both files missing
    monkeypatch.setattr(sys, "argv", ["agent.main"])
    assert cli.main() == 1
    assert "Could not load data" in capsys.readouterr().err
