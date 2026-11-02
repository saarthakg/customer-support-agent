"""Skills: the unit of extension.

A Skill bundles a journey spec (prompt text) with the tools that implement it.
To add a feature: write `agent/skills/<name>.py` exposing `build(deps) -> Skill`,
then add it to SKILL_BUILDERS below. The loop and prompt assembly never change.
"""

from collections.abc import Callable
from dataclasses import dataclass

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


@dataclass(frozen=True)
class Deps:
    """Everything a skill may depend on, passed in explicitly so tests can substitute fakes."""

    datasets: Datasets


SKILL_BUILDERS: list[Callable[[Deps], Skill]] = []


def build_skills(deps: Deps, builders: list[Callable[[Deps], Skill]] | None = None) -> list[Skill]:
    skills = [build(deps) for build in (SKILL_BUILDERS if builders is None else builders)]
    names = [t.name for s in skills for t in s.tools]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        raise ValueError(f"duplicate tool names across skills: {sorted(duplicates)}")
    return skills
