"""The agent loop: user message -> model -> (tool calls -> results -> model)* -> reply.

This file knows nothing about orders, products or promotions. It runs whatever
tools the enabled skills provide, which is why adding a skill never touches it.
"""

import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Protocol

from agent import config
from agent.llm import LLMError, LLMResponse, assistant_message, tool_result_message
from agent.prompt import build_system_prompt
from agent.registry import Skill, Tool
from agent.supervisor import BASE_PATTERNS, Supervisor
from agent.trace import Tracer

logger = logging.getLogger(__name__)

# Promotions are deliberately absent: they're mentioned only when a customer asks (DECISIONS D-21).
GREETING = (
    "Welcome to Sierra Outfitters! 🏔️ I can check on an order or help you find gear "
    "from our catalog. What can I help with today?"
)
FALLBACK_REPLY = (
    "Sorry, I hit a snag on the trail and couldn't finish that. Could you try again in a moment?"
)
# Shown when the supervisor blocks a reply twice: honest, and never repeats the blocked content.
SUPERVISOR_FALLBACK_REPLY = (
    "Sorry, I couldn't put together an answer I'm confident is accurate. I can check on an order "
    "or help you find gear from our catalog. Could you try asking another way?"
)


# Tool-call errors that mean the model produced a broken call (as opposed to a valid call
# with a business outcome like "order_not_found"). The model gets one retry after these.
MALFORMED_CALL_ERRORS = frozenset({"unknown_tool", "invalid_arguments"})


class ChatModel(Protocol):
    model: str
    temperature: float

    def complete(self, messages: list[dict], tools: list[dict]) -> LLMResponse: ...


@dataclass
class ToolCallRecord:
    name: str
    arguments: dict | str  # str only when the model sent unparseable JSON
    result: dict
    latency_ms: int


@dataclass
class TurnResult:
    reply: str
    outcome: str  # "ok" | "loop_limit" | "llm_error" | "supervisor_fallback" | "malformed_tool_call"
    supervisor: str = "not_run"  # "pass" | "retried" (blocked, then fixed) | "fallback" (blocked twice) | "not_run"
    supervisor_blocked: list[str] = field(default_factory=list)  # e.g. ["blocked_url: https://..."]
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    # Calls identical (same tool, same arguments) to one made earlier in the conversation.
    # Data is static, so these cost tokens and latency without new information.
    redundant_tool_calls: int = 0
    model_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0


class Agent:
    def __init__(
        self,
        llm: ChatModel,
        skills: list[Skill],
        tracer: Tracer | None = None,
        on_tool_call: Callable[[ToolCallRecord], None] | None = None,
        max_tool_iterations: int = config.MAX_TOOL_ITERATIONS,
    ) -> None:
        self.llm = llm
        self.tools: dict[str, Tool] = {t.name: t for s in skills for t in s.tools}
        self.tool_schemas = [t.schema() for t in self.tools.values()]
        self.tracer = tracer
        self.on_tool_call = on_tool_call
        self.max_tool_iterations = max_tool_iterations
        system_prompt = build_system_prompt(skills)
        self.messages: list[dict] = [{"role": "system", "content": system_prompt}]
        # Fingerprint of everything that shapes behavior besides the model itself, so any
        # traced reply can be tied to the exact prompt + tool contract that produced it.
        config_blob = json.dumps({"system": system_prompt, "tools": self.tool_schemas}, sort_keys=True)
        self.prompt_hash = hashlib.sha256(config_blob.encode()).hexdigest()[:12]
        skill_patterns = {kind: p for s in skills for kind, p in s.guarded_values.items()}
        self.supervisor = Supervisor({**BASE_PATTERNS, **skill_patterns})
        self.previous_calls: set[str] = set()
        self.turn_count = 0

    def greet(self) -> str:
        # A fixed opener: free, instant, and identical on every run of the demo.
        self.messages.append({"role": "assistant", "content": GREETING})
        return GREETING

    def respond(self, user_text: str) -> TurnResult:
        self.turn_count += 1
        start = time.monotonic()
        history_len = len(self.messages)
        self.messages.append({"role": "user", "content": user_text})
        result = TurnResult(reply=FALLBACK_REPLY, outcome="loop_limit")
        malformed_rounds = 0

        try:
            for _ in range(self.max_tool_iterations):
                response = self.llm.complete(self.messages, self.tool_schemas)
                result.model_calls += 1
                result.prompt_tokens += response.prompt_tokens
                result.completion_tokens += response.completion_tokens
                self.messages.append(assistant_message(response))

                if response.tool_calls:
                    records = [self._run_tool(call.name, call.arguments) for call in response.tool_calls]
                    for call, record in zip(response.tool_calls, records):
                        result.tool_calls.append(record)
                        if self._is_repeat(record):
                            result.redundant_tool_calls += 1
                        self.supervisor.observe(record.result)
                        self.messages.append(tool_result_message(call.id, record.result))
                        if self.on_tool_call:
                            self.on_tool_call(record)
                    # The error went back to the model as an observation; it gets one round to fix it.
                    if any(r.result.get("error") in MALFORMED_CALL_ERRORS for r in records):
                        malformed_rounds += 1
                        if malformed_rounds > 1:
                            result.outcome = "malformed_tool_call"
                            break
                    continue

                # A final reply: check it before the customer sees it.
                verdict = self.supervisor.check(response.content or "")
                if verdict.ok:
                    result.reply = response.content or FALLBACK_REPLY
                    result.outcome = "ok"
                    if result.supervisor == "not_run":
                        result.supervisor = "pass"
                    break
                result.supervisor_blocked += verdict.violations
                if result.supervisor == "retried":  # the one retry is used up
                    result.reply = SUPERVISOR_FALLBACK_REPLY
                    result.outcome = "supervisor_fallback"
                    result.supervisor = "fallback"
                    break
                # One corrective retry: swap the bad draft for a system note and ask again.
                result.supervisor = "retried"
                self.messages[-1] = {"role": "system", "content": Supervisor.correction(verdict)}
        except LLMError as e:
            logger.warning("model call failed: %s", e)
            result.outcome = "llm_error"

        if result.outcome != "ok":
            # Drop the failed turn from history so the next turn starts clean
            # (no dangling tool calls); the customer just asks again.
            del self.messages[history_len:]

        result.latency_ms = int((time.monotonic() - start) * 1000)
        self._trace(user_text, result)
        return result

    def _is_repeat(self, record: ToolCallRecord) -> bool:
        args = json.dumps(record.arguments, sort_keys=True) if isinstance(record.arguments, dict) else record.arguments
        key = f"{record.name}:{args}"
        seen = key in self.previous_calls
        self.previous_calls.add(key)
        return seen

    def _run_tool(self, name: str, raw_arguments: str) -> ToolCallRecord:
        """Execute one tool call. Never raises: every failure becomes a structured error the model can read."""
        start = time.monotonic()
        arguments: dict | str = raw_arguments
        tool = self.tools.get(name)
        if tool is None:
            result = {"ok": False, "error": "unknown_tool"}
        else:
            try:
                arguments = json.loads(raw_arguments or "{}")
                result = self._call_handler(tool, arguments)
            except json.JSONDecodeError:
                result = {"ok": False, "error": "invalid_arguments", "detail": "arguments were not valid JSON"}
        return ToolCallRecord(name, arguments, result, int((time.monotonic() - start) * 1000))

    @staticmethod
    def _call_handler(tool: Tool, arguments: object) -> dict:
        if not isinstance(arguments, dict):
            return {"ok": False, "error": "invalid_arguments", "detail": "arguments must be a JSON object"}
        # Check required args up front so a TypeError raised *inside* a handler is never mistaken for a bad call.
        missing = [p for p in tool.parameters.get("required", []) if p not in arguments]
        if missing:
            return {"ok": False, "error": "invalid_arguments", "detail": f"missing: {', '.join(missing)}"}
        known = tool.parameters.get("properties", {})
        try:
            return tool.handler(**{k: v for k, v in arguments.items() if k in known})
        except Exception:  # deliberate boundary: a tool bug must not crash the conversation
            logger.exception("tool %s failed", tool.name)
            return {"ok": False, "error": "tool_failed"}

    def _trace(self, user_text: str, result: TurnResult) -> None:
        if self.tracer is None:
            return
        self.tracer.write({
            "turn": self.turn_count,
            "model": self.llm.model,
            "temperature": self.llm.temperature,
            "prompt_hash": self.prompt_hash,
            "user": user_text,
            **asdict(result),
        })
