# Sierra Outfitters Agent

A terminal customer-support agent for **Sierra Outfitters**, built on `gpt-4.1-mini` with a hand-rolled tool-calling loop and no agent frameworks. It handles three journeys from the brief, plus a human handoff that the unhappy paths need:

| Journey | Tool | What code guarantees |
|---|---|---|
| Order status and tracking | `lookup_order(email, order_number)` | identity match on email **and** order number, one generic error on mismatch, status meanings, USPS link built from a template, 3-failure lockout |
| Product recommendations | `list_products()` | facts come only from the catalog; tags withheld (they're wrong); low-stock flag; no prices exist |
| Early Risers promotion | `issue_early_risers_code(email?)` | 8:00–10:00 AM Pacific (zoneinfo, DST-safe), an OPEN/CLOSED fact computed each turn, window checked first, unique `secrets` codes, same code per customer per day, survives restarts |
| Human handoff | `escalate_to_human(email, summary, order_number?)` | a real ticket in `logs/handoffs.jsonl` with a code-computed `verified` flag, so "I've passed this on" is true |

Built with Claude Code against a written engineering-principles doc and a phase-by-phase review process (the brief encouraged AI tooling). Every non-obvious decision is in **[DECISIONS.md](DECISIONS.md)** with the alternative and the reason, logged as it was made. **[DEMO.md](DEMO.md)** is the live-demo runbook.

## Quickstart

Requires Python 3.11+. From the repo root, in a fresh shell (deactivate conda first if your prompt shows `(base)`: `conda deactivate`):

```bash
python3 -m venv .venv && source .venv/bin/activate   # 1. create + activate the virtualenv
pip install -r requirements.txt                      # 2. install openai, python-dotenv, pytest
cp .env.example .env                                 # 3. then edit .env: OPENAI_API_KEY=sk-...
python -m agent.main            # chat   (add --debug to see tool calls, tokens, latency)
python -m agent.main --now 2026-11-03T08:30   # freeze the clock (Pacific) to demo Early Risers any time
pytest                          # 133 deterministic tests, no network, no API key needed
python -m tests.scenarios.run_scenarios -k 3  # 30 live conversation scenarios, reports pass^k
```

Every new shell needs `source .venv/bin/activate` again. If it's skipped, the agent exits with a one-line fix instead of a traceback. Issued promo codes persist in `state/issued_codes.json`; delete `state/` to reset a demo.

## Architecture

```
  customer ──▶ main.py (CLI, --debug, --now)
                  │
                  ▼
              loop.py ── Agent.respond(): one user turn ─────────────────────────────┐
                  │   messages ──▶ llm.py (only file importing openai) ──▶ gpt-4.1-mini│
                  │   ◀── tool calls ── run tool (validate args, never raise) ◀──────┤
                  │   ◀── final reply ── supervisor.py: every URL / ticket / code    │
                  │                       must match a tool result in this chat;     │
                  │                       1 corrective retry, then safe fallback     │
                  │   bounded: ≤5 model calls per turn; failed turns rolled back     │
                  └── trace.py: one JSONL record per turn (emails redacted) ─────────┘

  prompt.py   = VOICE + GLOBAL_RULES + one "# Skill:" section per enabled skill
                (+ per model call: code-computed facts from skills, e.g. "Early Risers status: OPEN"; never stored)
  skills/     = orders · products · early_risers · escalation   (listed in skills/__init__.py)
  data.py     = load + validate the two JSON datasets; normalization; identity match
```

**The core idea: the model owns judgment, code owns rules.**

| The model decides | Code decides |
|---|---|
| what the customer wants, and which tool to call | whether email + order number match the same order |
| what to ask for next (one short question) | what each order status means to the customer |
| whether a promo request is *explicit* | whether it's 8:00–10:00 AM Pacific right now |
| which catalog products fit, and why | the tracking URL, the discount code, the ticket ID |
| tone: brand voice on happy paths, plain on problems | uniqueness, idempotency, lockout, what may appear in a reply |

## How skills work

A **skill** is one feature: a journey spec (prompt text), its tools, and the values it mints. The skill list in `agent/skills/__init__.py` is the only registration point. **The loop and prompt assembly never change when a skill is added.** Adding, say, returns means writing `agent/skills/returns.py` with a `build(deps) -> Skill`, adding one line to the list, and writing a scenario.

- **Skill specs override global rules (D-48).** The system prompt is voice, then global rules, then one section per skill. The global rules say explicitly that a skill's spec wins on conflict. That's how the handoff journey drops the brand's upbeat "anything else for your next adventure?" close for a plain one, without special-casing it in the global rules.
- **Skills can supply per-turn facts computed in code (D-64).** A skill may provide `turn_context`, for example Early Risers' `Early Risers status: OPEN until 10:00 AM PT` or `CLOSED (runs 8:00-10:00 AM PT)`. The loop sends it as a separate system message on every model call. It's never stored in history and never part of the base prompt, so `prompt_hash` is the same at every hour. The model gets the *fact*, never the clock.
- **Skills declare the values they mint, and the supervisor guards them (D-47).** A skill can declare `guarded_values`, for example escalation's `{"blocked_ticket": HT-…}` and Early Risers' `{"blocked_code": EARLYRISER-…}`. The supervisor combines these with the global URL pattern and blocks any match in a reply that no tool returned earlier in the conversation. The skill that creates a value knows its shape, so guarding a new kind of value (an RMA number, a gift card) is a change to that one skill, and the supervisor stays skill-agnostic.

## Design decisions

The headline decisions are below. All 60+ entries, each with the alternative considered, are in [DECISIONS.md](DECISIONS.md).

| Decision | Alternative considered | Why |
|---|---|---|
| **Hand-rolled loop over Chat Completions** (D-04) | an agent SDK (banned), or the Responses API with server-held state | The whole conversation is a Python list we can print, trace and explain line by line. `llm.py` is the only file that knows the wire format (D-30), so swapping providers is a one-file change. |
| **Single agent, workflow-shaped** | multi-agent / planner–executor | Three known journeys. The model's autonomy is limited to choosing tools and phrasing. More agents would add failure modes without adding capability. |
| **Skills as the unit of extension** (D-05, D-40) | decorators / plugin discovery | Explicit dependencies (`Deps`: data, clock, code store, handoff log) that tests can replace; one visible list of what's enabled. |
| **Grounding is enforced, not requested: the before/after exhibit** (D-36, [docs/before_grounding.md](docs/before_grounding.md)) | trust the prompt | With no tools, the model invented three boot products, size availability, prices and a `sierraoutfitters.com` link, and every turn was traced as `"ok"`. That exhibit drove the explicit never-invent rule, the supervisor, the `supervisor` trace field, and two regression scenarios. |
| **Deterministic supervisor** (D-09, D-36, D-47) | an LLM supervisor | Every URL, ticket ID and promo code in a reply must exactly match one a tool returned *in this conversation* (not just this turn, so "resend that link?" works; not the global store, so another customer's code can't pass). One corrective retry, then a fixed fallback. Free, instant, unit-tested. |
| **Shared prompt means the full suite reruns after every skill change** (D-60) | test only the skill you touched | Skills are independent in code but share one prompt. Adding Early Risers silently dropped an unrelated product scenario from 5/5 to 0/2. The whole scenario suite is the regression gate. |
| **The model never sees the clock, only a code-computed OPEN/CLOSED fact** (D-08, D-64), and **the tool checks the window first** (D-62) | put the time in the prompt; prompt examples; ask for email first | With the raw time in context, the model would do its own time arithmetic and decide eligibility. A fact computed in code each turn gives it what it needs to talk correctly ("it's closed right now; it runs 8–10 PT") without asking for an email it can't use. The tool still enforces the window. This took the outside-window scenario from 5/6 to 6/6. |
| **Promo window `[08:00, 10:00)` Pacific** (D-20) | inclusive 10:00 | Half-open is the conventional reading of "8–10" and makes the boundary test unambiguous: 9:59:59 is in, 10:00:00 is out. `zoneinfo` handles DST. `--now` freezes the clock for demos. |
| **"Explicitly requests"** (D-21) | never mention it / issue on any discount question | Never advertised unprompted (not even in the greeting, D-35). A general "any discounts?" gets a mention with the hours, and a code only after an explicit yes. The model judges explicitness; code enforces time. |
| **Promo identity = normalized email; one code per customer per Pacific day** (D-22, D-23, D-61) | per-session codes; one code forever | Email is the only stable identity here. Asking again the same day, even after a restart, returns the same code (`already_issued: true`). Codes come from `secrets` with an alphabet without ambiguous characters. |
| **Identity check on orders: one generic error** (D-12, D-46) | "that email doesn't match this order" | A distinct message would let someone discover emails and order numbers. Both email and order number must match one record. After 3 *failures* (not attempts) the agent says "For security, I can't run more order lookups in this chat" and offers a handoff. |
| **Human handoff built, not faked** (D-16) | "please contact support" | Error-status orders need a handoff offer, and the agent must never claim an action that didn't happen. A real ticket ID makes "I've passed this to our support team" true. `verified` is computed in code and never shown to the model. |
| **Brand voice in two tiers** (D-63) | one tone everywhere | Happy paths always carry one outdoors phrase plus 1–2 emojis, *after* the link or code, which sits on its own line. Error, lockout and handoff paths are plain: empathy first, no emojis. Checked deterministically in scenarios. |
| **No RAG; tags withheld** (D-02, D-06) | embeddings, tag filtering | 10 products fit in one tool result. Tags are actively wrong (the energy drink is tagged `Weatherproof`, the jetpack `Safety-Enhanced`), so the model judges fit from descriptions only. At catalog scale, `list_products` becomes retrieval behind the same contract. |

## Testing

- **133 deterministic tests** (`pytest`, no network): every tool and edge case (order-number normalization, all four statuses, null tracking, missing SKUs, mismatch, lockout boundaries; window boundaries at 7:59:59, 8:00, 9:59:59 and 10:00; DST; idempotency across restarts; code uniqueness and collisions), the supervisor patterns, loop mechanics against a scripted fake model (bad tool calls, one retry for malformed JSON, iteration cap, rollback), trace redaction, and dataset integrity.
- **30 conversation scenarios** (`tests/scenarios/`): 22 journey scenarios plus 8 trust and adversarial ones (prompt injection, identity probes, invented codes and links, a frustrated customer, off-scope actions). Each is a scripted multi-turn conversation with checkable assertions: the right tool returned the right thing, links and codes appear verbatim and on their own line, nothing leaks on a mismatch, no code outside the window, no invented products or prices, brand voice on happy paths, no emojis on problem paths. `run_scenarios.py` runs each k times and reports **pass^k**. A scenario passes only if every run passes.

### Measured behavior

Live runs against `gpt-4.1-mini`. Every number is from a real run, failures included:

| Run | Result |
|---|---|
| Journey scenarios, k=1, final prompt (produced [docs/transcripts.md](docs/transcripts.md)) | **20/22**: two order scenarios hit the flakes below |
| Trust and adversarial scenarios, k=3 | **5/8 pass^3**. Both prompt injections, the identity probe, the cross-customer probe and the frustrated customer pass 3/3. Returns, cancellation and invented codes fail 3/3: open gaps below. |
| Promo scenarios after the per-turn status fact (D-64), k=6 | outside-window **6/6** (was 5/6); explicit-in-window **6/6** |
| `order_mismatch_lockout_escalates` re-measured, k=4 | 4/4 (its k=1 miss above was a one-off) |
| `order_error_escalates`, k=8 A/B with and without the status fact | 6/8 with, 7/8 without: the same pre-existing detour, not caused by D-64 |
| Full suite, k=2, before D-64 | 21/22 scenarios pass^2; 43/44 runs (98%) |
| Boots, repeated-question and vague-gear scenarios, k=5, before D-64 | 5/5 each |

**Known flakes, observed and not chased:**
- `order_error_escalates`: the model sometimes inserts "Just to confirm, your email is … and order W004?" before looking up, so the 3-turn script ends before the handoff (about 6/8). Tone and content are correct when it does reach the error path.
- `order_mismatch_lockout_escalates`: once, the model missed the order number in "check order W002, my email is …" and asked for it again. 4/4 on re-measurement.
- `product_playful_presented_earnestly`: once, the reply had no emoji, so only the voice check failed. Content was correct.
- *Resolved:* the model used to ask for an email before calling the promo tool, including outside the window (5/6). The per-turn OPEN/CLOSED fact fixed it (D-64, D-65).

The boots assertion is "never presents a catalog item as a *replacement* for the requested product type". Mentioning what we do carry is allowed. An earlier, stricter version that failed on any mention of a poorly fitting product measured about 2/5. Those failures were category mentions, not substitutions, so the check was redefined to match the principle rather than tuning the prompt further (D-54). Two other checks were also corrected because they flagged correct behavior: the agent echoing a customer's "$50 budget", and its correct "can't confirm size 10.5" (D-52). Scenario checks are code too.

## Observability

Every turn appends one record to `logs/trace.jsonl`. It holds the user message, reply, outcome, supervisor result (`pass` / `retried` / `fallback`, plus what was blocked), tool calls (args, results, latency), redundant identical tool calls, the per-turn facts the model saw (`turn_context`), token counts, `model`, `temperature`, and a `prompt_hash` that fingerprints the system prompt plus tool schemas. With the hash, any reply can be tied to the exact agent configuration that produced it. Emails are masked (`j***@example.com`) before anything is written (D-38). `--debug` prints the same information inline.

Model retries and timeouts use the openai client's built-in exponential backoff. The values (`MAX_RETRIES`, `REQUEST_TIMEOUT_S`, `MAX_TOOL_ITERATIONS`) live in `agent/config.py` (D-26). Any failed turn shows an in-voice "please try again" and is rolled back from history.

## Known limitations

- **Open trust gaps, measured and not yet fixed** (each has a failing scenario, so a fix is verifiable):
  - *Returns and cancellations don't get a handoff offer* (`trust_no_invented_returns_link`, `trust_cancel_not_claimed`, 0/3 each). The agent is honest (no link, no false "cancelled"), but it redirects to what it can do instead of offering the support team. The global "stay in scope, say what you can help with" rule wins over the escalation spec's "offer a handoff for things you can't do".
  - *Asking about a customer-supplied code* (`trust_invented_codes`, 0/3). If the reply quotes the customer's "SIERRA10", the supervisor blocks it as an unissued code (twice), and the customer gets the generic fallback. For "Can I use EARLYRISER-ABC123?" the agent never says it's valid, but sometimes says "come back during that time to use the code", which implies it will work.

- **The order-lookup lockout is a demo control, not rate limiting.** After 3 failed lookups (failures, not attempts), the agent stops looking up orders *in that chat* and offers a handoff. It lives in process memory, so a new session resets it. Real protection needs server-side, per-identity, time-windowed limits (D-13, D-42).
- **One person with several emails can get several promo codes.** Email is the only identity available. Production would key on an authenticated account (D-22).
- **The supervisor only sees what a regex can see.** Prose like "check our website" names no URL and passes. It's tracked as a scenario check, not blocked.
- **Scenario pass rates are small samples** (k=2–5). They show the shape of reliability, not a confident estimate.
- **Within one chat, a repeated promo request is answered from history**, not by calling the tool again. The supervisor verifies the code is exact. Cross-chat idempotency is code's job (D-58).
- **The tracking numbers in the data (`TRK…`) aren't real USPS numbers**, so the links don't resolve. The URL is built from the brief's template exactly.
- English only; no streaming; one conversation per process; each model call sends about 2.8k prompt tokens (system prompt plus tool schemas; the catalog is fetched by tool, not embedded), and a turn with a tool call makes two calls.

## Taking this to production

- **An LLM supervisor layer.** The deterministic supervisor catches invented URLs, ticket IDs and codes. It can't catch prose hallucinations like "check our website's hiking boots section", which names no URL but still sends the customer somewhere we can't vouch for. A second model that grades each reply against the tool results and policy would cover that class. Sierra's supervisor pattern is a checker layered over the agent, observing first and intercepting for high-risk topics.
- **A user simulator and larger pass^k evals.** Model-driven customers with personas and goals, many runs per scenario, tracked per release.
- **A conversation-review loop.** Reviewers annotate real conversations, and each annotated failure becomes a scenario (as `docs/before_grounding.md` became two).
- **Immutable versioned releases.** Prompt + tool schemas (already fingerprinted by `prompt_hash`) + model + data snapshot, promoted only when the scenario suite passes.
- **Auth and PII.** Authenticated identity instead of email-in-chat, full PII redaction (names, addresses, free text), and access-controlled handoff tickets.
- **Human handoff into a real queue** (Zendesk, Salesforce) with the conversation summary attached. The tool contract stays the same.
- **Metrics:** resolution rate, containment, escalation rate, CSAT proxy, tool-error rate, supervisor block rate, redundant-call rate, and latency and cost per conversation. Peak season (which the client flagged) makes cost per conversation and rate limits first-class.
- **Retrieval at catalog scale.** `list_products` becomes search (embeddings plus cleaned tag filters) returning the top matches in the same shape.

## Sample transcripts

Excerpts from live runs. One run of each of the 22 journey scenarios, failures shown, is in [docs/transcripts.md](docs/transcripts.md), generated by `python -m tests.scenarios.run_scenarios -k 1 --transcripts docs/transcripts.md` (all 22 scenarios, with tool calls). Tool calls are summarized in italics.

**Orders, happy path**
> **Customer:** Hi, where's my order? · **Sierra:** asks for email and order number · **Customer:** john.doe@example.com · **Sierra:** "Now I just need your order number." · **Customer:** W001
> *`lookup_order` → delivered, tracking_url*
> **Sierra:** Your order #W001 has been delivered. It included Bhavish's Backcountry Blaze Backpack and Beth's Caffeinated Energy Drink. You can track it here for details:
> https://tools.usps.com/go/TrackConfirmAction?tLabels=TRK123456789
> See you on the summit! 🏔️🥾 Is there anything else I can help with?

**Orders, unhappy path: error status, unknown item, handoff**
> **Customer:** W004, bob.brown@example.com
> *`lookup_order` → error, items: Invisibility Cloak + {SOCH010, name: null}*
> **Sierra:** I'm sorry, Bob, there is a problem with your order #W004 that our support team needs to resolve. It includes Nishita's Invisibility Cloak and an item (item code SOCH010). Would you like me to pass this issue to our support team for you?
> **Customer:** yes please · *`escalate_to_human` → HT-XFJ7NE*
> **Sierra:** I've passed your issue to our support team. Your ticket ID is HT-XFJ7NE. Is there anything else I can help with?

**Orders, unhappy path: mismatch, lockout, handoff** (nothing about W002's real owner leaks)
> **Customer:** check order W002, my email is john.doe@example.com · *→ order_not_found*
> **Sierra:** I couldn't find an order matching that email and order number together. Could you please double-check both?
> **Customer:** hmm, try W003 · *→ order_not_found* · **Customer:** what about W004? · *→ too_many_attempts*
> **Sierra:** For security, I can't run more order lookups in this chat. If you'd like, I can pass your request to our support team for help. Would you like me to do that?

**Products, happy path**
> **Customer:** I'm heading on a ski trip next month, what should I get? · *`list_products`*
> **Sierra:** For your ski trip, I recommend Crain's Summit Pro X Skis. They offer ultimate precision and performance with an advanced vibration-dampening system for a smooth ride on every descent. See you on the summit! ⛷️🏔️

**Products, unhappy path: something we don't carry** (replay of the session that once invented three boots)
> **Customer:** interested in hiking boots · *`list_products`*
> **Sierra:** We don't carry hiking boots in our catalog. Is there any other gear or outdoor essentials you need for your hike?
> **Customer:** men's waterproof ones · **Sierra:** We don't carry men's waterproof hiking boots or any hiking boots at all…
> **Customer:** 10.5 US
> **Sierra:** I don't have size details for the products in our catalog, so I can't filter by shoe size…

**Early Risers, happy path: generic question, then an explicit yes** (clock frozen at 9:00 AM PT; the model is told `OPEN`)
> **Customer:** Do you have any discounts right now?
> **Sierra:** We have the Early Risers promotion running now, which gives you 10% off if you shop between 8:00-10:00 AM Pacific Time. Would you like me to get you a code for that?
> **Customer:** Yes please! It's alice.johnson@example.com · *`issue_early_risers_code` → EARLYRISER-NKJNB8*
> **Sierra:** Here's your 10% off Early Risers discount code:
> EARLYRISER-NKJNB8
> Use it at checkout. Happy trails! 🌲🥾

**Early Risers, unhappy path: outside the window** (clock frozen at 2:20 PM PT; the model is told `CLOSED`, and never asks for an email)
> **Customer:** Do you have any discounts right now?
> **Sierra:** We have the Early Risers promotion, which offers 10% off between 8:00 and 10:00 AM Pacific Time. It is currently closed, but feel free to come back during those hours for the discount.
> **Customer:** yes please
> **Sierra:** The Early Risers promotion runs only from 8:00 to 10:00 AM Pacific Time and is currently closed. Please check back during those hours to get the 10% discount code.

## Data

`data/CustomerOrders.json` and `data/ProductCatalog.json` are transcribed from the PDF appendices by `scripts/extract_data.py`:

```bash
pdftotext -layout "Agent Building Prompt Appendices.pdf" appendices.txt
python3 scripts/extract_data.py appendices.txt data
```

The script fixes only PDF artifacts (a stray `None` line under each heading, and description strings wrapped across lines). Every value, typos included, is preserved exactly (D-01). Data realities the code handles: four statuses, with `fulfilled` and `error` having no tracking number; three ordered SKUs (`SOCH010`, `SOBN008`, `SOGK009`) missing from the catalog; no prices; noisy tags; two low-stock items.

## Repository layout

```
agent/
  main.py          CLI: --debug, --now; startup checks
  config.py        model, temperature, limits, paths
  llm.py           the only openai import: client, retries, token usage, message shapes
  loop.py          Agent: bounded tool loop, supervisor retry, rollback, tracing
  prompt.py        VOICE + GLOBAL_RULES + skill specs
  registry.py      Tool, Skill, Deps, build_skills
  supervisor.py    deterministic reply check (URLs + skill-declared values)
  trace.py         JSONL trace with email redaction
  data.py          dataset loading/validation, normalization, identity match
  clock.py         Pacific time, --now parsing, fixed clock
  code_store.py    CodeStore interface; in-memory and JSON-backed stores
  skills/          orders, products, early_risers, escalation (+ __init__.py: the enabled list)
tests/             133 unit tests; scenarios/ holds the conversation scenarios and pass^k runner
docs/              before_grounding.md (exhibit), transcripts.md (generated)
scripts/           extract_data.py (PDF to JSON)
DECISIONS.md       every decision, its alternative, and why
DEMO.md            live-demo runbook
```
