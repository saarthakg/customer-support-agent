"""The enabled skills, in the order their journey specs appear in the system prompt.

Adding a feature = one new module in this package + one entry in this list.
"""

from agent.registry import SkillBuilder
from agent.skills import escalation, orders

SKILL_BUILDERS: list[SkillBuilder] = [
    orders.build,
    escalation.build,
]
