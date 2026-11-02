"""The enabled skills, in the order their journey specs appear in the system prompt.

Adding a feature = one new module in this package + one entry in this list.
"""

from agent.registry import SkillBuilder
from agent.skills import early_risers, escalation, orders, products

SKILL_BUILDERS: list[SkillBuilder] = [
    orders.build,
    products.build,
    early_risers.build,
    escalation.build,
]
