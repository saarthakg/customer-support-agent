# Decisions log

Each entry records the choice, the alternative considered, and the reason. Entries are added when a decision is made, not reconstructed at the end.
Status: **Accepted** = settled; **Proposed** = recommendation awaiting review.
**★ Headline** marks the decisions the README's design section leads with.
Entries D-01–D-25 were reviewed at the end of Phase 0. Those not explicitly discussed were accepted when Phase 1 was approved.

---

## Data

### D-01 Datasets transcribed from the PDF appendices · Accepted
- **Choice:** `pdftotext -layout`, then a throwaway script that (a) drops the stray `None` line the PDF prints under each appendix heading, and (b) rejoins string literals that the PDF wrapped across lines, using a single space. Every value is otherwise byte-for-byte, including the typo `Caffnated`, the trailing space in the Skis description (`"...thrilling adventure. "`), the `". ."` at the end of the Plane description, and `—` / `décor` in the Lampshade description. Written with `ensure_ascii=False`, 2-space indent.
- **Alternative:** hand-copying, or "cleaning" the typos.
- **Why:** this is mechanical and auditable, and the brief says the data is static. Cleaning the source would make tests and grounding diverge from what Sierra gave us. The agent can still say the correct product *name* aloud.

### D-02 Tags are not sent to the model · Accepted
- **Choice:** `list_products` returns `sku, name, description, inventory, low_stock` and omits `Tags`.
- **Alternative:** send tags as hints (§0.1 allows a pre-filter that never excludes on tags alone).
- **Why:** tags are wrong in ways that produce exactly the claims we must not make: the energy drink is tagged `Weatherproof`, the jetpack `Safety-Enhanced`, the hairbrush `Trail`. Descriptions are the only grounding. Omitting tags removes the temptation instead of prompting against it. At catalog scale, tags would be cleaned and used as retrieval filters.

### D-03 Low stock is a code-computed flag · Accepted
- **Choice:** `low_stock = inventory <= 20` is computed in code. The agent may say "only a few left" when the flag is set, and gives exact counts only if asked. It never invents restock or shipping dates.
- **Alternative:** let the model decide what "low" means from the raw number.
- **Why:** P1. A threshold is a business rule, and the model shouldn't choose a value code can compute.

---

## Architecture

### D-04 Chat Completions API with a hand-rolled loop · Accepted · ★ Headline
- **Choice:** `client.chat.completions.create(..., tools=...)`. We own the `messages` list and run the loop: call → execute tool calls → append results → repeat, capped at N iterations per user turn.
- **Alternative:** the Responses API (server-side state), or any agent SDK (banned).
- **Why:** the full conversation is a plain Python list we can print, trace, and explain line by line. Server-held state would hide the thing Sierra wants to see.

### D-05 Skill = instructions + tools; registry is one list · Accepted · ★ Headline
- **Choice:** each `skills/<name>.py` exposes `build(deps) -> Skill`. `registry.py` holds `SKILL_BUILDERS = [orders.build, products.build, early_risers.build]`. The prompt and tool list are assembled from it. Adding a feature means one new file plus one line, and the loop never changes.
- **Alternative:** module-level globals or decorator auto-discovery (a plugin system, which §4 rules out).
- **Why:** dependencies (datasets, clock, code store) are explicit and injectable for tests, and registration is visible in one place.

### D-06 Single `list_products` tool, no `get_product` · Accepted
- **Choice:** one tool that returns the compact catalog (10 items).
- **Alternative:** `list_products` + `get_product(sku)` as P3 sketches.
- **Why:** with 10 items, `get_product` duplicates data `list_products` already returns. It's a natural live extension (e.g. an inventory-check skill), not core.

### D-07 Status meanings live in code · Accepted
- **Choice:** a `STATUS_INFO` dict in `skills/orders.py` maps each of the four statuses to a factual customer-facing meaning, and the tool returns it. *How* to say it (empathy, emoji rules) lives in the journey spec.
- **Alternative:** let the model interpret `fulfilled` / `error` itself.
- **Why:** P7. The model would improvise different meanings each run, and §0.1 requires explicit definitions.

### D-08 No current time in the system prompt · Accepted · ★ Headline
- **Choice:** the model is never told the time. Promo eligibility is learned only from the tool result.
- **Alternative:** inject "current time: 9:12 AM PT" into the prompt.
- **Why:** with the time in context, the model would decide eligibility itself and skip the tool, which defeats P1/P8. The tool result includes the current PT time so the model can phrase "it's 7:42 AM PT, so check back at 8".

### D-09 Supervisor allow-list = values from tool results in this conversation · Accepted · ★ Headline
- **Choice:** any URL or code-shaped token in an outgoing reply must appear in a tool result from *this conversation*. P11 originally said "this turn" for URLs and "in the issued-codes store" for codes. AGENT_PRINCIPLES.md P11 has been updated to match.
- **Alternative:** P11 as originally written.
- **Why:** "this turn" would block a legitimate "can you resend that link?" one turn later. Store-wide would let a code issued to *another* customer pass. Session-scoped tool output is stricter than the store and looser than the turn, and it's one rule for both URLs and codes.

### D-10 Dataclasses, not pydantic · Accepted
- **Choice:** `dataclasses` for records and skills, with plain dicts for tool results (they're JSON anyway).
- **Alternative:** pydantic (P13 allows either).
- **Why:** pydantic isn't in the approved dependency list.

---

## Order status journey

### D-11 Order-number normalization · Accepted
- **Choice:** in code, accept `W001`, `#W001`, `w001`, ` #W001 `, `order #W001`, and bare digits `1` / `001` → `#W001`. Anything else → `invalid_order_number`.
- **Alternative:** exact match only, or let the model normalize.
- **Why:** P3. Bare digits are unambiguous because every order uses the `W` prefix. If real data had several prefixes, we'd drop that rule.

### D-12 One generic error for not-found and mismatch · Accepted · ★ Headline
- **Choice:** the tool returns `order_not_found` whether the order doesn't exist or exists under a different email. The agent asks the customer to double-check both, with one message. The tool never returns any data from a non-matching record.
- **Alternative:** "that email doesn't match this order."
- **Why:** P6. A distinct message is an enumeration oracle for emails and order numbers.

### D-13 Cap failed lookups per session · Accepted
- **Choice:** after 3 failed lookups in a session, the tool returns `too_many_attempts`. The agent stops retrying and *offers escalation* (D-16) instead of hitting a dead end.
- **Alternative:** rely on the prompt, or no cap.
- **Why:** the order space is tiny (`W001`–`W010`) and emails are guessable. A prompt can be talked out of a limit, a counter can't. It's about five lines and a good trust talking point.

### D-14 `fulfilled` = packed, not yet handed to the carrier · Accepted
- **Choice:** "Your order is packed and getting ready to ship. Tracking isn't available yet; it'll appear once the carrier has it." No link, and no date promised.
- **Alternative:** treat fulfilled as shipped.
- **Why:** both fulfilled orders (#W003, #W007) have `TrackingNumber: null`. That only makes sense pre-carrier.

### D-15 `error` = apologize, no speculation, human handoff, no emojis · Accepted
- **Choice:** templated meaning: "There's a problem with this order that I can't resolve here; a member of our support team needs to look at it." No guessed cause (payment, stock…), no exuberance, no emojis, no link.
- **Why:** P5/P9, the highest-empathy path.

### D-16 Minimal human-handoff skill, built now · Accepted · ★ Headline
- **Conflict resolved:** P9 requires a human-handoff offer on the error path, and §3 forbids claiming actions that didn't happen. With no handoff mechanism, the offer would be hollow.
- **Choice:** an `escalation` skill with `escalate_to_human(email, order_number, summary)`. It appends a ticket to `logs/handoffs.jsonl` and returns a `ticket_id`. It's used on the `error`-status path and when the lookup cap (D-13) is hit, offered first and filed when the customer agrees. The agent can then truthfully say "I've passed this to our support team; your ticket is HT-XXXXXX."
- **Detail:** on the lookup-cap path the order number is unverified by definition. The tool records `verified: true/false` (computed in code by matching email and order) so support knows what they're getting. The model never asserts verification.
- **Alternative:** honest "please contact support" wording with no tool, leaving escalation as a live extension.
- **Why:** escalation is what makes the two dead-end paths (error orders, locked-out customers) resolve, and it's a small, self-contained skill that demonstrates the extension pattern.

### D-17 Ordered SKUs missing from the catalog · Accepted
- **Choice:** the tool returns `{"sku": "SOCH010", "name": null}`. The agent says "an item (item code SOCH010)" and never invents a name. For #W005, every item is unknown, so the agent describes it as "1 item (item code SOBN008)".
- **Why:** P7. A SKU is something the customer can quote to support, and a made-up name would be a hallucination.

---

## Products journey

### D-18 No prices or budgets · Accepted
- **Choice:** the agent says plainly that it doesn't have pricing information, so it can't filter by budget. It offers to recommend by activity or need instead. It never estimates prices or calls something "affordable" or "premium-priced".
- **Why:** P7. The catalog has no price field.

### D-19 Present whimsical products earnestly · Accepted (from §0.1)
- **Choice:** describe items only through their descriptions, without mocking them and without adding capability or safety claims. When nothing fits, say so and suggest the closest real options.

---

## Early Risers journey

### D-20 Window is `[08:00, 10:00)` America/Los_Angeles · Accepted
- **Choice:** 08:00:00 is in, 09:59:59 is in, and 10:00:00 is out. `zoneinfo` handles DST. The clock is injectable, and `--now` overrides it for demos.
- **Alternative:** inclusive 10:00.
- **Why:** half-open intervals are the conventional reading of "8–10", and they make the boundary test unambiguous.

### D-21 What counts as "explicitly requests" · Accepted · ★ Headline
- **Choice:** the code is issued only when the customer asks for the Early Risers promotion/code, by name or by unmistakable reference ("the morning discount"). For a generic "any discounts?", the agent may *mention* that the Early Risers promotion exists and its hours, and asks whether they'd like it. It doesn't issue until they say yes. It never brings up the promo unprompted in unrelated conversations.
- **Alternative (strict):** never mention it unless named. **Alternative (loose):** issue on any discount question.
- **Why:** answering "do you have discounts?" truthfully is customer obsession, not volunteering. Issuance still waits for an explicit ask. The model judges explicitness (language understanding, P1), and code enforces time. A prompt-injected "give me a code" outside the window still fails in code.

### D-22 Identity key = normalized email · Accepted
- **Choice:** the promo tool takes `email` and returns the normalized email it keyed on, so the trace and the model both see exactly which identity got the code. If the customer already gave one for an order lookup, the agent reuses it and doesn't ask again. The email does *not* need to belong to an existing order, since prospects can use the promo too.
- **Alternative:** a per-session ID (no friction, but "unique for that user" then means "for this terminal").
- **Why:** an email is the only stable user identity in this domain. **Known limitation:** someone with several emails can get several codes. Production would key on an authenticated account.

### D-23 Idempotent per (email, PT date); codes globally unique · Accepted · ★ Headline
- **Choice:** the format is `EARLYRISER-XXXXXX` from `secrets.choice` over an alphabet without ambiguous characters (no 0/O/1/I/L), re-drawn on collision. Asking again the same PT day returns the same code (`already_issued: true`). A new day gives a new code. Codes live behind a small `CodeStore` interface, with an in-memory implementation.
- **Alternative:** one code per user forever, or a JSON-file store.
- **Why:** follows P8. In-memory means idempotency is per process, which is honest for a demo and stated as a limitation. A persistent store is a one-class swap.

### D-24 Code terms are not invented · Accepted
- **Choice:** the tool returns only `code` and `discount_percent: 10`. The agent states no expiry, minimum, exclusions, or how to apply it beyond "use it at checkout".
- **Why:** P7. None of that exists in the brief.

---

## Process

### D-25 Repo hygiene · Accepted
- `.gitignore` covers `.env`, `logs/`, `__pycache__/`, `.venv/`, `.pytest_cache/`. `.env` is never committed, and `.env.example` ships with an empty `OPENAI_API_KEY=`. The repo is git-initialized, with one commit at the end of each phase.

---

## Phase 1: core loop

### D-26 Retries and timeouts via the openai client's built-ins · Accepted
- **Choice:** `OpenAI(timeout=30, max_retries=2)`. The client already retries 429/5xx/connection errors with exponential backoff. `llm.py` converts any remaining `OpenAIError` into our own `LLMError`.
- **Alternative:** a hand-written retry/backoff loop.
- **Why:** the behavior is the same with less code to explain. The values live in `config.py`, so the policy is still visible.

### D-27 A failed turn is rolled back from history · Accepted
- **Choice:** if a turn ends in `llm_error` or hits the iteration cap, every message from that turn (user message included) is removed, and the customer sees an in-voice "please try again".
- **Alternative:** keep the partial turn (dangling tool calls, no final answer).
- **Why:** history always ends in a clean state, the next request can't be confused by half-finished tool rounds, and it's one rule for both failure modes. Tool side effects are safe to repeat because issuance is idempotent (D-23).

### D-28 Tool arguments are validated at the loop boundary · Accepted
- **Choice:** before calling a handler, the loop checks that the arguments parse as a JSON object and contain the schema's `required` keys, and it drops keys not in `properties`. Unknown tool, bad JSON, missing args and handler exceptions all become `{"ok": false, "error": ...}` results the model can recover from. Handlers stay plain typed functions that are testable directly.
- **Alternative:** let `TypeError` from `handler(**args)` signal bad args (it would also swallow real bugs inside handlers).
- **Why:** P3. Structured errors, never raised into the loop. The one `except Exception` is a documented boundary.

### D-29 Fixed greeting, not model-generated · Accepted
- **Choice:** the opener is a constant, added to history as the assistant's first message.
- **Why:** it's free, instant, identical every demo run, and it sets the scope (orders, products, Early Risers) before the customer types.

### D-30 Wire format lives in `llm.py` · Accepted
- **Choice:** `llm.py` owns the Chat Completions message shapes (`assistant_message`, `tool_result_message`) as well as the client. `loop.py` handles only our own `LLMResponse`/`ToolCall` dataclasses.
- **Why:** swapping to another provider or the Responses API is a one-file change.

### D-31 Exact dependency pins · Accepted
- **Choice:** `openai==3.42.1`, `python-dotenv==1.2.4`, `pytest==9.2.0`, the versions tested.
- **Why:** the demo must run first try on the day. A floating `openai` could change the client surface under us.

### D-32 Data extraction script kept in the repo · Accepted
- **Choice:** `scripts/extract_data.py` regenerates `data/*.json` from `pdftotext -layout` output. It isn't imported by the agent.
- **Why:** reviewers can audit exactly how the PDFs became JSON (D-01).

---

## Phase 1 review fixes

### D-33 Startup checks with a one-line fix · Accepted
- **Choice:** `main.py` checks the Python version and catches `ModuleNotFoundError` *before* importing third-party code. A missing `OPENAI_API_KEY` is also caught. Each prints a one-line fix, and the process exits 1.
- **Why:** the onsite starts by running the code live. Running in the wrong interpreter (e.g. conda base) is the most likely failure, and a traceback costs minutes to read under pressure. Verified from a fresh clone with an empty environment (`env -i`).

### D-34 Submission zip = `git archive` · Accepted
- **Choice:** `git archive --format=zip -o sierra-outfitters-agent.zip HEAD`.
- **Why:** only tracked files ship, so `.env`, `.venv/`, `logs/`, and the confidential *Interviewing at Sierra* PDF (git-ignored) are excluded by construction rather than by remembering to delete them. Verified by listing the archive.

### D-35 No promotion advertising in greeting or self-introduction (amends D-21, D-29) · Accepted
- **Found:** the fixed greeting advertised Early Risers to everyone at any hour, and the model's self-introduction listed "promotions" (session 5ee19862). That came from the scope rule in GLOBAL_RULES, which literally listed "orders, products, promotions".
- **Choice:** the greeting lists only order status and product help. GLOBAL_RULES tells the model to describe only those two when introducing itself, and to discuss promotions only when the customer asks about discounts. A unit test guards the greeting, and the self-introduction was checked live (3/3 runs clean).
- **Why:** D-21 already said "never unprompted", and the greeting was a contradiction of our own making. A scope list in the prompt is also something the model reads as a menu to recite.

### D-36 Grounding rule plus deterministic URL check, pulled forward from Phase 3 · Accepted · ★ Headline
- **Found:** with no tools enabled, the model invented three boot products, size availability, prices, and a `sierraoutfitters.com` link. Every turn was traced as `"ok"` (sessions 9cd1151d, 009a475d, exhibited in `docs/before_grounding.md`).
- **Choice:** (1) GLOBAL_RULES: "If no tool provides a fact, say plainly that you can't help with that here", plus an explicit never-invent list (products, links, prices, sizes, specs, availability, dates, codes). (2) `supervisor.py`: every URL in a final reply must exactly match a URL from a tool result earlier in this conversation. On a block, the bad draft is replaced in history by a corrective system note and the model gets one retry. A second block shows a fixed, honest fallback, and the turn is rolled back (D-27).
- **Detection:** scheme or `www.` links, plus bare domains with common TLDs, with a lookbehind so emails don't count. Trailing sentence punctuation is stripped. Markdown links are handled.
- **Alternative:** a prompt rule only, or an LLM supervisor.
- **Why:** the rule cuts the rate, and the regex guarantees the damage never reaches the customer. It costs nothing at runtime and is fully unit-testable. After the change, replaying both sessions produced no invented products or links.
- **Known gap:** prose referrals like "check our website" contain no URL, so the regex can't see them. They're tracked as a scenario check (`NO_WEBSITE_REFERRAL`) rather than blocked. An LLM supervisor would be the next layer.
- **Detail:** the supervisor is skill-agnostic. It learns allowed values by observing tool results, and Early Risers will register a code pattern alongside the URL pattern.

### D-37 Trace records carry supervisor outcome and an agent-config fingerprint · Accepted
- **Found:** `outcome` alone marked the invented-URL turns as `"ok"`.
- **Choice:** each record adds `supervisor` (`pass` / `retried` / `fallback` / `not_run`) plus `supervisor_blocked`, a list of `"<kind>: <value>"` such as `"blocked_url: https://…"` (and `blocked_code` once Early Risers exists). It also adds `model`, `temperature`, and `prompt_hash`: the first 12 hex characters of the SHA-256 of the system prompt plus tool schemas.
- **Alternative:** a single `supervisor` field with five values (pass / blocked_url / blocked_code / retried / fallback), as in the review note.
- **Why split:** "what happened" (pass, retried, fallback) and "what was blocked" (url, code) vary independently. A retry can follow a blocked URL *or* code, and one draft can contain both. A status plus a list records that without combinatorial values. `not_run` covers turns that failed before a final reply (API error, iteration cap).
- **Why the hash:** a prompt or tool-description edit changes behavior as much as a model change. With the hash, any traced reply can be tied to the exact agent configuration. That's the cheap version of immutable versioned releases.

### D-38 Emails redacted in traces · Accepted
- **Choice:** `trace.redact()` masks every email anywhere in a record (user text, tool args, tool results, replies) as `j***@example.com` before writing. Order numbers and first names are kept for debuggability.
- **Alternative:** no redaction (it's a local demo), or dropping user text entirely.
- **Why:** traces are the artifact most likely to get pasted into a bug report or shared. Masking keeps the domain (useful for debugging typos) without the identity. **Exception:** escalation tickets (`logs/handoffs.jsonl`) keep the full email, because support needs it to contact the customer. In production that file would be a ticketing system with access control. A full PII pass (names, addresses, free text) is a production step.

### D-39 Malformed tool calls: one retry, then fallback · Accepted
- **Found:** a malformed call (bad JSON, missing required argument, unknown tool) already went back to the model as a structured tool observation, but the model could retry until the iteration cap (5 model calls).
- **Choice:** count *rounds* containing a malformed call. The first round's error goes back as an observation and the model retries. A second malformed round ends the turn with the in-voice "please try again" fallback (`outcome: "malformed_tool_call"`), and the turn is rolled back (D-27). Business errors (`order_not_found`, `outside_promo_window`, …) don't count, because they're valid calls with an answer the model must relay.
- **Alternative:** count individual calls, which would punish two parallel bad calls with no retry, or rely on the iteration cap.
- **Why:** a model that fails to form a call twice in a row is unlikely to fix it on the third try. Failing fast saves latency and tokens, and it's a distinct, traceable outcome instead of a generic `loop_limit`.

---

## Phase 2: orders and escalation

### D-40 Enabled-skill list lives in `agent/skills/__init__.py` (amends D-05) · Accepted
- **Choice:** `SKILL_BUILDERS` moved from `registry.py` to `agent/skills/__init__.py`. `registry.py` keeps only the `Tool` / `Skill` / `Deps` types and `build_skills()`.
- **Why:** skills import their types from `registry.py`, so `registry.py` importing the skills would be circular. The extension story is unchanged: one new module plus one line, in the package where skills live.

### D-41 Normalization and identity match live in the data layer · Accepted
- **Choice:** `normalize_email`, `normalize_order_number` and `Datasets.find_order(email, order_number)` are in `data.py`, shared by the orders and escalation skills.
- **Why:** both skills need the same definition of "this email owns this order". Two copies would drift, and a skill importing from another skill would couple them.

### D-42 Lockout details · Accepted
- Only `order_not_found` counts toward the cap. Malformed inputs (`invalid_email`, `invalid_order_number`) don't, because they reveal nothing about the data.
- The 3rd failure itself returns `too_many_attempts`, so the agent offers escalation immediately rather than inviting a doomed 4th try.
- The counter never resets within a session, even after a success, because "find my order, then probe others" is still enumeration. It lives on an `OrderLookup` instance built per conversation.

### D-43 Escalation contract details (extends D-16) · Accepted
- `order_number` is optional, so a customer with a returns question or no order can still be handed off. An unrecognizable value is kept verbatim on the ticket for support.
- The tool returns only `ticket_id`. `verified` is written to the ticket but not shown to the model, so the model can't repeat it to the customer as a claim.
- The ticket ID is `HT-` plus 6 characters from an alphabet without 0/O/1/I/L, because it gets read aloud.
- The escalation journey uses a plain tone: no emojis, no exclamation marks.

### D-44 "Ask for what's missing" wording (deviates from §3's literal "one thing at a time") · Accepted · flag for review
- **Found:** the prompt rule "Ask for exactly what is missing, one thing at a time" made the model say "Just one at a time, please" to customers.
- **Choice:** "Ask only for what you're missing, in one short question (e.g. if you have the order number, ask only for the email). Never ask again for something the customer already gave you, and never tell them how to pace or format their answers."
- **Why:** §3's intent, shown by its own example, is "don't re-ask for what you have". The literal "one at a time" got echoed to customers as an instruction. With both identifiers missing, the model still tends to ask for one and then the other. That's acceptable, and it's a Phase 4 voice-tuning candidate.

### D-45 Remember identifiers across a failed lookup · Accepted
- **Found:** in the first live mismatch transcript, after `order_not_found` the model asked for the email again instead of reusing it, so the lockout was never reached.
- **Choice:** the orders journey spec tells the model to reuse earlier identifiers when the customer corrects one ("try W003"). The scenario `order_mismatch_lockout_escalates` guards it.
