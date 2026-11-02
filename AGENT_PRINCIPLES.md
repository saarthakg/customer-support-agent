# Guiding Principles: Sierra Outfitters Agent

> Standing instructions for the coding agent on this project. Read this file in full before writing code, and re-read the relevant section before each phase. When a principle conflicts with a convenient shortcut, the principle wins. If you think a principle is wrong for a specific case, say so and explain why before you deviate.

---

## 0. The job in one paragraph

Build a terminal chat agent for **Sierra Outfitters**, a fictional outdoor retailer. It uses **`gpt-4.1-mini`** through the official `openai` Python client and needs three capabilities:

1. **Order status and tracking.** Ask for email and order number, then return the status and the USPS tracking link.
2. **Product recommendations.** Answer only from the product catalog.
3. **Early Risers Promotion.** Issue a unique 10% code only when the customer explicitly asks, and only between 8:00 and 10:00 AM Pacific.

Hard constraints:
- **No agent frameworks or orchestration libraries.** That rules out the OpenAI Agents SDK, LangChain, AutoGen and templates. The loop is hand-written.
- Budget is about 2–3 hours.
- No UI.

The code will be **walked through for 20 minutes and then extended live** with Sierra engineers. Optimize for code that is easy to explain and easy to extend under pressure, not for the most impressive architecture.

Sierra grades on four things. Every decision should map to at least one:

| Criterion | What it means here |
|---|---|
| **Craft & code quality** | Small, typed, readable modules. Adding a feature should be one obvious edit. |
| **Use of AI** | The LLM does what LLMs are good at (understanding, conversation, tone, choosing tools). Code does what code is good at (rules, data, time, IDs). |
| **Conversation design** | Correct behavior with the right brand tone, every time, including on unhappy paths. |
| **Communication** | Every non-obvious choice is written down with the alternative and the trade-off. |

### How the onsite actually runs (from Sierra's "Interviewing at Sierra" guide)
- **Agent Building round:**
  1. Walk through the implementation, **run the code live**, and explain design decisions, "including how you structured your solution."
  2. Then **collaborate to extend the agent with new functionality**, building on top of this code.
- The solution must be **tested end-to-end** and **already running on the laptop** at the start. Submit it 24h before.
- AI tools are encouraged; **agentic frameworks (e.g., LangChain) are not.** Sierra wants to see *my own* approach to designing, structuring and orchestrating an agent.
- The separate Debugging round bans AI tools. Sierra values engineers who can reason about code unaided.

So this codebase must be something its author can **explain line by line and modify confidently under live pressure**. Prefer plain, explicit code over clever abstractions. Every file should be readable in under two minutes.

---

## 0.1 Data realities (Appendix A & B, verified)

These come from the actual appendices, which are provided as **PDFs**. The first build step is to transcribe them into clean JSON under `data/`. Use `pdftotext` or copy the text, rejoin the line-wrapped description strings, and preserve all content exactly; fix only PDF line-wrap artifacts. Then add a test asserting **10 orders and 10 products** with the expected keys.

**CustomerOrders.json**: fields `CustomerName, Email, OrderNumber, ProductsOrdered, Status, TrackingNumber`.
- `OrderNumber` includes a `#` prefix (`"#W001"`). Customers will type `W001`, `#W001`, `w001` or `order 1`. Normalize in code; don't make the model do it.
- **Four statuses:** `delivered`, `in-transit`, `fulfilled`, `error`. Each needs its own customer-facing explanation, defined in code or the journey spec, not improvised:
  - `delivered` and `in-transit` → have a tracking number, so give the link.
  - `fulfilled` → **`TrackingNumber` is null** (#W003, #W007). This is likely packed but not yet handed to the carrier. Say tracking isn't available yet and don't print a link. Log this interpretation as a decision.
  - `error` → **`TrackingNumber` is null** (#W004, #W008). Something went wrong. Apologize, don't speculate about the cause, and offer escalation to a human. This is the highest-empathy path, so keep the brand exuberance minimal.
- **Dangling SKUs:** orders reference `SOCH010`, `SOBN008`, `SOGK009`, which **do not exist in the catalog** (#W004, #W005, #W006, #W009). The order tool must handle missing products gracefully. Show the SKU or "an item," never invent a product name, and never crash.
- One order per customer, and emails are unique and lowercase. Still normalize case and whitespace on input.

**ProductCatalog.json**: fields `ProductName, SKU, Inventory, Description, Tags`.
- **There is no price field.** The agent must never state or estimate prices, and "budget" is not a filter it can honor. Say so honestly if asked.
- `Inventory` exists. Two items are low (14 units: `SOSV008`, `SOSV010`). Stock can be mentioned factually. Don't invent shipping or restock dates.
- **Tags are noisy and sometimes wrong.** The hairbrush is tagged `Trail`/`Adventure`, and the energy drink `Weatherproof`. Keyword or tag matching alone would give bad recommendations.
  - **Decision:** with only 10 items, the product tool returns the compact full catalog (or a light pre-filter that never excludes on tags alone), and the model judges fit from **descriptions**.
  - README talking point: at real catalog scale this becomes retrieval (embeddings + filters) feeding the same tool contract.
- The catalog is **deliberately whimsical**: a plane, a jetpack, an invisibility cloak, teleporting shoes, a lampshade. Present items earnestly, grounded strictly in their descriptions. Don't add capability, safety or spec claims the description doesn't make, and don't mock the products. When nothing fits, say so and suggest the closest real options.
- There are small data typos (e.g., "Caffnated" in one description, stray spaces and punctuation). Preserve the source data; the agent can use the correct product **name** when speaking.

---

## 1. What Sierra believes, and what it means for this build

These are drawn from Sierra's own engineering writing, its job description and its research (sources in §9). They are why the principles below are defensible, not just preferences.

| Sierra's position | Implication for this project |
|---|---|
| Agents should be **creative in conversation but deterministic where business logic matters** (orders, plan changes, promotions). Goals are declared, and guardrails are enforced in code. *(ADLC post)* | Promotion eligibility, code minting, order lookup and identity checks live in Python. The model never decides whether it is 8–10 AM PT and never invents a code. |
| Plain function-calling / ReAct loops **aren't reliable enough on their own** for production. τ-bench showed GPT-4o at about 61% pass^1 on retail tasks, falling below 25% at pass^8. *(Meet the Agent Engineer; τ-bench)* | Don't rely on the prompt alone for correctness. Put structure around the model: validated tool inputs, deterministic tools, a bounded loop and post-checks. |
| Agents are built from **composable skills**, "LEGO bricks instead of pouring concrete." *(Meet the Agent Engineer)* | Each feature is a self-contained **skill**: prompt fragment + tool schemas + handlers. A new feature is a new skill, registered in one place. This is the live-extension strategy. |
| Agents need a **manual**: journey specs, plus the *"policy behind the policy."* *(Shipping & Scaling post)* | Write each feature as a mini journey spec before coding it. Define unhappy paths: outside the promo window, order not found, email/order mismatch, item not in the catalog. |
| **Supervisors** layer verification over the agent. A second check that catches errors compounds reliability (Sierra's example: 90% + a 90%-accurate checker ≈ 99%). For high-risk topics a supervisor can switch from observing to intercepting. *(Meet the Agent Engineer; Enterprise-grade agents)* | Add a cheap **deterministic output check**: any tracking URL or discount code in a reply must match one a tool actually returned. An LLM supervisor is a "next step" talking point, not part of the core build. |
| **Conversation tests and simulation** are the regression suite, so the agent "never makes the same mistake twice." Reliability is measured over **repeated trials (pass^k)**, not single runs. *(ADLC; τ-bench)* | Deterministic unit tests for every tool, plus scripted conversation scenarios run against the real model several times. Report pass rate over k runs. |
| Agents are **highly observable**. Every decision has a trace. *(ADLC; Shipping & Scaling)* | Structured per-turn trace (JSONL): messages, tool calls, args, results, latency, tokens. A `--debug` flag prints it live. |
| Model-agnostic by design: behavior is declared abstractly from the underlying LLM, so it improves as models improve. *(ADLC; Constellation of models)* | One thin `llm.py` wrapper. Model name and parameters live in config. Nothing outside that file imports `openai`. |
| Values: **Trust, Customer Obsession, Craftsmanship, Intensity, Family.** Craftsmanship is described as "getting the details right, from the words on the page to the system architecture." *(Job description)* | Details count: copy-pasteable links and codes, sensible emoji density, no leaked customer data, clean README. |
| "Every agent is a product." *(Shipping & Scaling)* | Make product calls, not just engineering ones, and write them down. Examples: what the agent says outside the promo window, and whether it offers to escalate to a human. |

---

## 2. Architecture principles

### P1. The model owns judgment; code owns rules.
- **Model:** understand intent, ask for missing info, choose tools, phrase answers in brand voice, recommend among *catalog* products.
- **Code:** data lookup, identity matching, time-zone math, eligibility, code generation, URL construction, uniqueness and idempotency.
- **Test:** if a wrong answer would cost the business money or trust, code decides it. If a model is choosing a value that code could compute, the design is wrong.

### P2. Use the simplest architecture that works, and say why.
- One agent, one hand-rolled tool-calling loop. **No multi-agent, no planner/executor split, no vector DB, no RAG.** The catalog is small and fits in a tool result.
- This is a *workflow-shaped* problem with three known journeys. Autonomy is limited to choosing which tool to call and how to talk.
- Keep the heavier patterns (supervisor models, simulators, routing, memory) as **"how I'd scale this"** in the README. Don't build them.

### P3. Tools are the contract.
- Use **few, well-named tools** with tight JSON schemas and descriptions written as if they are the model's only documentation, because they are. For example: `lookup_order(email, order_number)`, `list_products()` / `get_product(sku)`, `issue_early_risers_code(email)`. See §0.1 for why products aren't tag-searched.
- **Validate arguments in code** before acting: normalize email case and whitespace, strip `#` from order numbers, and so on.
- **Return structured results, including errors**, as tool observations, for example `{"ok": false, "error": "order_not_found"}`. Don't raise errors into the loop. The model reads the error and recovers in-conversation.
- Tool output stays **concise and relevant**. Return what the model needs, not whole records.

### P4. Each feature is a skill, and adding one is a single, obvious change.
- A `Skill` bundles: a name, a short prompt fragment (its journey spec), tool schemas, and handler functions.
- A registry assembles the system prompt and tool list from the enabled skills. **The core loop never changes when a feature is added.**
- This is the onsite story. Be ready to add a new skill live, for example returns/exchanges, escalation to a human, inventory checks, or a cancellation save offer.

### P5. Policy lives in code; voice lives in the prompt; keep them separate.
- The system prompt has distinct, labelled sections: **identity & voice**, **global rules**, then **per-skill journey specs**.
- **Brand voice:** frequent outdoors references, enthusiastic phrases like "Onward into the unknown!", and mountain or trail emojis. Calibrate it:
  - Use 1–2 emojis per message, and none on the `error`-status path.
  - Never let the tone obscure a status, link or code.
  - Drop the exuberance when the customer is frustrated or something went wrong. Empathy first, then a light touch of voice.
- Voice is a persona, separate from what the agent is *allowed* to do. A tone change should never require touching business logic, and the reverse.

### P6. Trust: verify identity, and never leak data.
- Order details are returned only when **both** the email and the order number match the same record.
- On a mismatch, give **one generic message**. Never reveal whether an email exists, or whose order a number belongs to.
- Never return other customers' data in tool results, so the model can't leak it.
- The API key comes from an **environment variable**. Never hardcode or commit it. Ship a `.env.example`.

### P7. Ground everything in the data.
- Product answers come **only** from the catalog: no invented products, prices, specs or stock. The catalog has no prices at all. If nothing fits, say so and offer the closest real options.
- Order status and tracking come **only** from the orders data. Map each of the four statuses to an explicit explanation (§0.1). `fulfilled` and `error` orders have no tracking number, so never print a link for them. Resolve ordered SKUs to product names where they exist, and handle the three SKUs missing from the catalog without inventing names.
- The tracking URL is built in code from the template `https://tools.usps.com/go/TrackConfirmAction?tLabels={trackingNumber}`.
- **Before writing any tool, open the actual JSON files and read their real field names, value sets and edge cases.** Don't assume a schema.

### P8. Time and codes are computed, injectable and testable.
- Compute Pacific time in code with `zoneinfo.ZoneInfo("America/Los_Angeles")`, which handles DST.
- Inject the clock (a `now()` dependency) so tests can freeze time on both sides of the window.
- **Window semantics:** decide and document them. Recommended: `[08:00, 10:00)` PT, so 10:00:00 is outside.
- **"Explicitly requests":** the agent does not volunteer the promo or proactively issue a code. If asked outside the window, it explains the hours in PT, which is the policy behind the policy. Document whether it may *mention* the promo exists.
- **Codes:** generated with `secrets`, in a readable format such as `EARLYRISER-7KQ2XM`.
  - The code is unique.
  - Issuing is idempotent per customer per day: asking twice returns the same code.
  - Codes are stored behind a small interface (in-memory by default) so the supervisor check can verify them.
  - "For that user" needs an identity key. Recommended: ask for email, and reuse it if it was already given for an order lookup. Document this choice.

### P9. Bound the loop and fail gracefully.
- Set a max number of tool-call iterations per user turn, a request timeout, and a small retry with backoff for transient API errors.
- When something fails, the customer gets an **in-voice, honest fallback**, not a stack trace.
- Out-of-scope requests (returns, complaints, anything without a tool) get a helpful redirect and an offer to connect with a human. Don't pretend the agent can do it.
- `error`-status orders are the one in-scope journey that always ends in a human handoff offer. Keep that message templated in the journey spec so it's consistent.

### P10. Make every turn observable.
- Each turn appends one structured record to `logs/trace.jsonl`: user message, model messages, tool calls with args and results, latency, token usage, and supervisor-check outcome.
- A `--debug` CLI flag pretty-prints tool calls inline during the demo. Showing reasoning and actions live is a strong part of the walkthrough.
- No PII in logs beyond what's needed. Mention redaction as a production step.

### P11. Lightweight deterministic supervision.
After the model writes a reply and before it is shown, run a **deterministic post-check**:
- Any URL in the reply must equal a URL returned by a tool **earlier in this conversation**.
- Any discount-code-shaped string must equal a code returned by a tool **earlier in this conversation**.

Scoping to the conversation (not the single turn, not the global code store) is deliberate: "this turn" would block a legitimate "can you resend that link?", and the global store would let a code issued to a different customer pass. See DECISIONS.md D-09.

On failure, retry once with a corrective system note, then fall back to a safe templated message. This is the cheap version of Sierra's supervisors and blocks the highest-damage hallucinations.

### P12. Test like it's an agent, not just a program.
- **Unit tests (no network):**
  - Every tool and edge case:
    - mismatched email/order, unknown order, order-number normalization (`W001`, `#w001`, ` #W001 `)
    - each of the four statuses, null tracking, SKUs missing from the catalog
    - window boundaries at 7:59, 8:00, 9:59 and 10:00 PT, DST
    - code uniqueness and idempotency
    - dataset integrity (10 orders, 10 products, expected keys)
  - The supervisor check.
- **Conversation scenarios (real model):** a handful of scripted multi-turn conversations per journey, each with checkable assertions:
  - the right tool was called with the right args
  - the link or code appears verbatim
  - no code was issued outside the window
  - no data leaked on a mismatch
- Run each scenario k times (e.g., k=3–5) and report pass^k. Small, but it shows you understand that reliability is a distribution.
- Every bug found manually becomes a scenario. Regression tests are how the agent never makes the same mistake twice.

### P13. Craftsmanship in the code itself.
- Python 3.11+ with type hints throughout. Use `dataclass` or `pydantic` for records and tool results.
- Keep modules small and single-purpose. Config (model, temperature, limits, timezone, paths) lives in one place.
- Use `logging` for diagnostics and keep `print` for the chat UI. No bare `except`.
- Use low temperature for consistency, since this is a support agent.
- The README is a first-class deliverable (see §6).

---

## 3. Conversation design rules

- **Ask for exactly what's missing, one thing at a time.** For example, if the customer gives the order number, ask only for the email.
- **Confirm the outcome plainly first, then add flavor.** "Your order #W001 has shipped! 🏔️ Track it here: <link>". Never bury the link or code mid-paragraph.
- **Keep replies short.** Most replies should be 1–4 sentences, plus a link or code if relevant. Product recommendations can run longer, but each item gets a reason tied to what the customer said.
- **Ask clarifying questions for recommendations** when the need is vague (activity, season, conditions). Don't dump the whole catalog. There are no prices, so don't promise budget filtering.
- **Keep it in scope.** Politely decline unrelated tasks, stay in character, and steer back to how the agent can help.
- **Never claim an action that didn't happen.** "I've issued your code" appears only after the tool succeeded.
- **Read the room.** Match energy for excited customers and lead with empathy for frustrated ones. Brand exuberance is a seasoning, not the meal.
- **Close the loop.** End resolved threads with a brief "anything else for your next adventure?" Don't ask it after every message.

---

## 4. Scope discipline (anti-goals)

The builder's natural instinct is heavy rigor: ledgers, phase gates, replay harnesses, multi-agent orchestration. **For this project, resist it.** Rigor shows up here as correctness, clarity and tests, not as infrastructure.

Do **not** build:
- multi-agent systems, planners, vector stores, RAG, embeddings
- databases beyond a JSON-backed or in-memory store
- web UI, async frameworks, plugin systems, config DSLs
- streaming, voice, or an LLM-based supervisor

Mention any of these in the README's "Next steps" section if they're relevant. When in doubt, ask: *would a Sierra engineer extending this live be helped or slowed by it?*

---

## 5. Suggested layout

```
sierra-outfitters-agent/
├── README.md               # run instructions, design decisions, trade-offs, next steps
├── .env.example            # OPENAI_API_KEY=
├── requirements.txt        # openai, python-dotenv, pytest (keep it minimal)
├── data/
│   ├── CustomerOrders.json
│   └── ProductCatalog.json
├── agent/
│   ├── main.py             # CLI chat loop (--debug flag)
│   ├── config.py           # model, limits, timezone, paths
│   ├── llm.py              # thin OpenAI wrapper: retries, timeouts, token accounting
│   ├── loop.py             # the agent loop: messages -> model -> tool calls -> results -> reply
│   ├── prompt.py           # assembles system prompt from voice + rules + enabled skills
│   ├── registry.py         # Skill dataclass + registry of enabled skills
│   ├── supervisor.py       # deterministic post-checks on outgoing replies
│   ├── trace.py            # JSONL tracing
│   ├── data_store.py       # loads/validates JSON datasets once
│   └── skills/
│       ├── orders.py       # lookup_order
│       ├── products.py     # list_products / get_product
│       └── early_risers.py # issue_early_risers_code (+ clock, code store)
└── tests/
    ├── test_tools.py       # deterministic, no network
    ├── test_supervisor.py
    └── scenarios/          # scripted multi-turn conversations + pass^k runner
```

This is a suggestion, not a mandate. Collapse files if they'd be trivially small. Clarity beats ceremony.

---

## 6. README requirements

The README is how decisions get communicated before anyone opens the code. It must include:

1. **Quickstart.** Setup and run in 3 commands or fewer, and how to run the tests.
2. **Architecture in one diagram or short paragraph.** Loop, skills, tools, supervisor check, trace.
3. **Design decisions.** For each: the choice, the alternative considered, and why. At minimum:
   - hand-rolled loop vs framework
   - single agent vs multi
   - what's deterministic vs model-driven
   - promo window boundary semantics
   - code identity key and idempotency
   - identity verification behavior on mismatch
   - how brand voice is calibrated
   - why no RAG
4. **Known limitations and failure modes**, stated honestly.
5. **How I'd take this to production**:
   - an LLM supervisor
   - a user simulator with larger pass^k evals
   - conversation-review loop (annotations become regression tests)
   - immutable versioned releases (prompt + model + data snapshot)
   - auth and PII handling
   - human handoff
   - metrics: resolution rate, containment, escalation rate, CSAT proxy, tool-error rate, latency and cost per conversation
6. **Sample transcripts** for each journey, including at least one unhappy path each.

Maintain `DECISIONS.md` (or a section in the README) **as you go**. Log each decision when it's made, not reconstructed at the end.

---

## 7. Likely onsite extensions (design so these are cheap)

- A new journey: returns/exchanges, order cancellation, inventory/availability, store hours, warranty questions.
- Escalation/handoff to a human with a conversation summary.
- Policy changes: a new promo window, a different discount, a loyalty tier "policy behind the policy," a region-specific rule.
- Behavior changes: a different tone for a VIP segment, multi-language, a cancellation save offer.
- Peak-season concerns (the client flagged peak traffic and product issues): rate limits, cost per conversation, faster model routing, surfacing product-issue trends from conversations.

If the skill registry, tool contract and tests are clean, each of these is one new skill plus a scenario or two.

---

## 8. Working agreement with the coding agent

- Work **sequentially, in phases**, and stop at each checkpoint for review. Don't run ahead.
- **Inspect before you build.** Read the data files and confirm assumptions before writing tools.
- When a requirement is ambiguous, **pick the most defensible reading, log it in DECISIONS.md, and flag it**. Don't silently guess.
- Keep diffs small. Run the deterministic tests after every change.
- Don't add dependencies beyond `openai`, `python-dotenv` and `pytest` without asking.
- Explain *why* in code comments where the reason isn't obvious from the code. Don't narrate *what*.
- **The author must be able to explain and change every line without AI help.** If a piece of code would be hard to explain in the walkthrough, simplify it.
- Keep a `DEMO.md` runbook: setup check, then one happy path and one unhappy path per journey, then `--debug` on to show tool calls. The onsite starts with running the code live, so this must work first try. Include a way to fake the clock (e.g., `--now 2026-11-03T08:30-08:00`) so the promo can be demoed at any hour.

---

## 9. Sources

- Sierra Take-Home brief: *Agent Chat Loop* (the assignment, provided separately as `sierra-take-home.md`)
- Sierra, *Interviewing at Sierra* guide (PDF in project folder): Agent Building, Debugging and Hiring Manager rounds; values
- Appendix A `CustomerOrders.json` and Appendix B `ProductCatalog.json` (PDFs in project folder)
- Sierra, *The Agent Development Life Cycle*: https://sierra.ai/blog/agent-development-life-cycle
- Sierra, *Meet the AI agent engineer*: https://sierra.ai/blog/meet-the-ai-agent-engineer
- Sierra, *Shipping and scaling AI agents*: https://sierra.ai/blog/shipping-and-scaling-ai-agents
- Sierra, *Enterprise-grade agents* (supervisors observe/intercept): https://sierra.ai/blog/enterprise-grade-agents
- Sierra, *Constellation of models*: https://sierra.ai/blog/constellation-of-models
- Yao et al. (Sierra), *τ-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains*, ICLR 2025: https://arxiv.org/abs/2406.12045
- Sierra, *Software Engineer, Agent (New Grad 2027)* job description and company values: https://jobs.ashbyhq.com/Sierra/149f368c-52d5-408f-ba26-ad888f318a00
- Sierra talk, *Building AI agents that elevate millions* (Dorothy Hu; covers agent development, the ADLC, point-and-click → code → Agent SDK, chat + voice)
- Sierra Resources hub: https://sierra.ai/resources
