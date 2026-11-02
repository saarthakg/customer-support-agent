"""Terminal chat for the Sierra Outfitters agent.

    python -m agent.main            # chat
    python -m agent.main --debug    # also show tool calls, tokens and latency inline
"""

import argparse
import json
import logging
import os
import sys
import uuid

from dotenv import load_dotenv

from agent import config
from agent.data import DataError, load_datasets
from agent.llm import LLM
from agent.loop import Agent, ToolCallRecord, TurnResult
from agent.registry import Deps, build_skills
from agent.trace import Tracer

DIM, RESET = "\033[2m", "\033[0m"
EXIT_WORDS = {"exit", "quit", "bye"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Sierra Outfitters support agent")
    parser.add_argument("--debug", action="store_true", help="show tool calls, tokens and latency inline")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    load_dotenv()
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set. Copy .env.example to .env and add your key.", file=sys.stderr)
        return 1

    try:
        datasets = load_datasets(config.DATA_DIR)
    except DataError as e:
        print(f"Could not load data: {e}", file=sys.stderr)
        return 1

    session_id = uuid.uuid4().hex[:8]
    llm = LLM()
    agent = Agent(
        llm=llm,
        skills=build_skills(Deps(datasets=datasets)),
        tracer=Tracer(config.LOG_DIR / "trace.jsonl", session_id),
        on_tool_call=_print_tool_call if args.debug else None,
    )

    if args.debug:
        print(f"{DIM}[session {session_id} · model {config.MODEL} · tools: {', '.join(agent.tools) or 'none'}]{RESET}")
    print(f"\nSierra: {agent.greet()}\n")

    while True:
        try:
            user_text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_text:
            continue
        if user_text.lower() in EXIT_WORDS:
            break
        result = agent.respond(user_text)
        if args.debug:
            _print_turn_stats(result)
        print(f"\nSierra: {result.reply}\n")

    if args.debug:
        u = llm.usage
        print(f"{DIM}[session total: {u.calls} model call(s) · {u.prompt}+{u.completion} tokens]{RESET}")
    print("Happy trails! 🌲")
    return 0


def _print_tool_call(record: ToolCallRecord) -> None:
    args = json.dumps(record.arguments, ensure_ascii=False) if isinstance(record.arguments, dict) else record.arguments
    print(f"{DIM}  → {record.name}({args})")
    print(f"  ← {json.dumps(record.result, ensure_ascii=False)}{RESET}")


def _print_turn_stats(result: TurnResult) -> None:
    print(
        f"{DIM}  [{result.outcome} · {result.model_calls} model call(s) · "
        f"{result.prompt_tokens}+{result.completion_tokens} tokens · {result.latency_ms} ms]{RESET}"
    )


if __name__ == "__main__":
    sys.exit(main())
