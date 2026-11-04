"""Terminal chat for the Sierra Outfitters agent.

    python -m agent.main                          # chat
    python -m agent.main --debug                  # also show tool calls, tokens and latency inline
    python -m agent.main --now 2026-11-03T08:30   # freeze the clock (Pacific if no offset) to demo Early Risers
"""

import argparse
import json
import logging
import os
import sys
import uuid

# Startup checks run before third-party imports so a wrong interpreter or a
# missing virtualenv gets a one-line fix instead of a traceback.
SETUP_HINT = "source .venv/bin/activate && pip install -r requirements.txt  (see README Quickstart)"
if sys.version_info < (3, 11):
    sys.exit(f"Python 3.11+ required (found {sys.version.split()[0]}). Fix: {SETUP_HINT}")
try:
    from dotenv import load_dotenv

    from agent.llm import LLM
except ModuleNotFoundError as e:
    sys.exit(f"Missing dependency '{e.name}' (is the virtualenv active?). Fix: {SETUP_HINT}")

from agent import config
from agent.clock import PACIFIC, fixed_clock, parse_now, system_clock
from agent.code_store import JsonCodeStore
from agent.data import DataError, load_datasets
from agent.loop import Agent, ToolCallRecord, TurnResult
from agent.registry import Deps, build_skills
from agent.skills import SKILL_BUILDERS
from agent.trace import Tracer

DIM, RESET = "\033[2m", "\033[0m"
EXIT_WORDS = {"exit", "quit", "bye"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Sierra Outfitters support agent")
    parser.add_argument("--debug", action="store_true", help="show tool calls, tokens and latency inline")
    parser.add_argument(
        "--now", type=parse_now, metavar="ISO_TIME",
        help="freeze the clock, e.g. 2026-11-03T08:30 (Pacific if no offset) or 2026-11-03T16:30+00:00",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    load_dotenv()
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set. Fix: cp .env.example .env, then put your key in .env", file=sys.stderr)
        return 1

    try:
        datasets = load_datasets(config.DATA_DIR)
    except DataError as e:
        print(f"Could not load data: {e}", file=sys.stderr)
        return 1

    deps = Deps(
        datasets=datasets,
        now=fixed_clock(args.now) if args.now else system_clock,
        handoff_log=config.HANDOFF_LOG,
        code_store=JsonCodeStore(config.CODE_STORE),
    )
    session_id = uuid.uuid4().hex[:8]
    llm = LLM()
    agent = Agent(
        llm=llm,
        skills=build_skills(deps, SKILL_BUILDERS),
        tracer=Tracer(config.TRACE_LOG, session_id),
        on_tool_call=_print_tool_call if args.debug else None,
    )

    if args.debug:
        print(f"{DIM}[session {session_id} · model {config.MODEL} · tools: {', '.join(agent.tools) or 'none'}]{RESET}")
    if args.now:
        # Always shown, not just in --debug: a demo with a faked clock should say so.
        print(f"{DIM}[clock frozen at {args.now.astimezone(PACIFIC):%Y-%m-%d %I:%M %p} Pacific]{RESET}")
    print(f"\nSierra: {agent.greet()}\n")

    try:
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
    except KeyboardInterrupt:  # Ctrl-C while the agent is answering: exit like Ctrl-D, no traceback
        print()

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
    extras = f" · supervisor {result.supervisor}"
    if result.supervisor_blocked:
        extras += f" (blocked {', '.join(result.supervisor_blocked)})"
    if result.redundant_tool_calls:
        extras += f" · {result.redundant_tool_calls} redundant call(s)"
    if result.turn_context:
        extras += f" · context: {'; '.join(result.turn_context)}"
    print(
        f"{DIM}  [{result.outcome} · {result.model_calls} model call(s) · "
        f"{result.prompt_tokens}+{result.completion_tokens} tokens · {result.latency_ms} ms{extras}]{RESET}"
    )


if __name__ == "__main__":
    sys.exit(main())
