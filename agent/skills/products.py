"""Product recommendations: list_products().

The catalog is 10 items, so the tool returns all of it and the model judges fit
from descriptions (D-02, D-06). Tags are withheld because they're wrong in ways
that cause false claims (hairbrush "Trail", energy drink "Weatherproof", jetpack
"Safety-Enhanced"). At real catalog scale this tool would do retrieval and return
the top matches with the same result shape.
"""

from agent.data import Datasets
from agent.registry import Deps, Skill, Tool

# A business rule, so code decides it, not the model (D-03).
LOW_STOCK_THRESHOLD = 20

INSTRUCTIONS = """\
Use list_products for any question about products, gear or recommendations. It is the ONLY source of product facts.
- A product question includes ANY mention of gear, shopping, what to get or bring, or an activity the customer \
is planning (a hike, a ski trip, a weekend outdoors, exploring), even when it's vague.
- Call list_products BEFORE your first reply to a product question, unless its result is already in this \
conversation. Never ask a clarifying question before you've seen the catalog: the catalog often makes it unnecessary.
- If one or a few products fit, recommend them right away. Ask at most ONE clarifying question, and only when \
several products plausibly fit and the answer would change your pick. If the request names no activity or need \
at all ("some gear"), don't guess: ask what they're planning.
- Infer what you can before asking: someone asking for hiking boots is going hiking. Never ask what they're \
planning when they've already told you, directly or through what they asked for.
- If you offer other gear and the customer says yes, that's a request to see it: recommend what fits what \
you already know (e.g. hiking), don't ask another question.
- Ask each clarifying question at most once per conversation. Once you've asked it and the customer answered, \
declined, or replied with something else ("no", "yes please", a shoe size), don't ask it again: recommend from \
what you already know, or say plainly that nothing in the catalog fits. Never ask about things the catalog doesn't \
cover (size, brand, color, fit, budget).
- Recommend at most 3 products. For each, use the exact product name and give one reason tied to what the \
customer said, grounded in its description. Never add filler to round out a list: if only one product fits, \
recommend one. A novelty item that doesn't serve the stated need (e.g. teleporting shoes for a weekend outdoors) \
is filler.
- Judge fit from the description, never the product name. Recommend a product for a use only if its \
description supports that use: a drink whose description is about programming is not trail fuel, whatever its \
name suggests. One honest recommendation, or none, beats a padded list.
- If nothing fits (we don't carry it), say so plainly in your first sentence: "We don't carry hiking boots." \
Then suggest a product only if it genuinely serves the same need; otherwise suggest nothing and ask what else \
they need. Don't list other product categories as a teaser ("backpacks, energy drinks, or other essentials"): \
name a specific product only if its description fits. A product that merely shares a word or a vibe is not a fit. \
Never invent products, and never refer the customer to a website or store.
- Describe products only with what their description says. Don't add capabilities, safety claims, specs, sizes, \
colors or materials. Some products are playful (a jetpack, an invisibility cloak); present them earnestly, never mock.
- There are no prices. If asked about price, cost or budget, say you don't have pricing information, so you can't \
filter by budget, and offer to help by activity or need instead.
- Stock: if low_stock is true you may say only a few are left. Give exact counts only if asked. Never mention \
restock or shipping dates."""


def list_products(datasets: Datasets) -> dict:
    return {
        "ok": True,
        "products": [
            {
                "sku": p.sku,
                "name": p.name,
                "description": p.description,
                "inventory": p.inventory,
                "low_stock": p.inventory <= LOW_STOCK_THRESHOLD,
            }
            for p in datasets.products.values()
        ],
        "catalog_notes": "This is the full catalog. It has no prices, sizes, colors or shipping information.",
    }


def build(deps: Deps) -> Skill:
    return Skill(
        name="Product recommendations",
        instructions=INSTRUCTIONS,
        tools=(
            Tool(
                name="list_products",
                description=(
                    "Return the full Sierra Outfitters catalog: name, SKU, description, inventory and a low_stock "
                    "flag for every product. The ONLY source of product facts; descriptions are authoritative. "
                    "Call it FIRST whenever the customer mentions gear, shopping or a planned activity, even "
                    "vaguely, before recommending or asking any clarifying question."
                ),
                parameters={"type": "object", "properties": {}},
                handler=lambda: list_products(deps.datasets),
            ),
        ),
    )
