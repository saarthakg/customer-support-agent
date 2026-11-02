"""Skills: the unit of extension.

A Skill bundles a journey spec (prompt text) with the tools that implement it.
To add a feature: write `agent/skills/<name>.py` exposing `build(deps) -> Skill`,
then add it to SKILL_BUILDERS in `agent/skills/__init__.py`. The loop and prompt
assembly never change.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from agent.clock import Clock
from agent.code_store import CodeStore
from agent.data import Datasets


@dataclass(frozen=True)
class Tool:
    name: str
    description: str  # written for the model: this is its only documentation
    parameters: dict  # JSON Schema for the arguments
    handler: Callable[..., dict]  # called with keyword args; returns {"ok": True, ...} or {"ok": False, "error": ...}

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }


@dataclass(frozen=True)
class Skill:
    name: str
    instructions: str  # the journey spec, inserted into the system prompt
    tools: tuple[Tool, ...]
    # Values this skill mints that must never be invented, e.g. {"blocked_ticket": <HT-XXXXXX regex>}.
    # The supervisor blocks any match in a reply unless one of this conversation's tool results returned it.
    guarded_values: dict[str, re.Pattern[str]] = field(default_factory=dict)
    # A fact computed by code on every model call (e.g. "Early Risers status: OPEN until 10:00 AM PT"),
    # sent as a separate system message: never stored in history, never part of the base prompt (D-64).
    turn_context: Callable[[], str] | None = None


@dataclass(frozen=True)
class Deps:
    """Everything a skill may depend on, passed in explicitly so tests can substitute fakes."""

    datasets: Datasets
    now: Clock  # timezone-aware; injectable so tests and --now can control time
    handoff_log: Path  # where escalation tickets are appended
    code_store: CodeStore  # issued Early Risers codes


SkillBuilder = Callable[[Deps], Skill]


def build_skills(deps: Deps, builders: list[SkillBuilder]) -> list[Skill]:
    skills = [build(deps) for build in builders]
    names = [t.name for s in skills for t in s.tools]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        raise ValueError(f"duplicate tool names across skills: {sorted(duplicates)}")
    kinds = [k for s in skills for k in s.guarded_values]
    if len(kinds) != len(set(kinds)):
        raise ValueError(f"duplicate guarded value kinds across skills: {sorted(kinds)}")
    return skills
