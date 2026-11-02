# Sierra Outfitters Agent

A terminal customer-support agent for Sierra Outfitters, built on `gpt-4.1-mini` with a hand-rolled tool-calling loop (no agent frameworks).

> Work in progress: the full README (architecture, design decisions, transcripts) lands in Phase 4. Decisions are logged as they're made in [DECISIONS.md](DECISIONS.md).

## Quickstart

Requires Python 3.11+. From the repo root, in a fresh shell (deactivate conda first if your prompt shows `(base)`: `conda deactivate`):

```bash
python3 -m venv .venv && source .venv/bin/activate   # 1. create + activate the virtualenv
pip install -r requirements.txt                      # 2. install openai, python-dotenv, pytest
cp .env.example .env                                 # 3. then edit .env: OPENAI_API_KEY=sk-...
python -m agent.main            # chat   (add --debug to see tool calls, tokens, latency)
python -m agent.main --now 2026-11-03T08:30   # freeze the clock (Pacific) to demo Early Risers any time
pytest                          # deterministic tests, no network, no API key needed
```

Every new shell needs `source .venv/bin/activate` again. If it's skipped, the agent exits with a one-line fix instead of a traceback.

## Data

`data/CustomerOrders.json` and `data/ProductCatalog.json` are transcribed from the PDF appendices by `scripts/extract_data.py`:

```bash
pdftotext -layout "Agent Building Prompt Appendices.pdf" appendices.txt
python3 scripts/extract_data.py appendices.txt data
```

The script fixes only PDF artifacts (a stray `None` line under each heading, and description strings wrapped across lines). Every value, typos included, is preserved exactly (DECISIONS D-01).

## How skills work

A **skill** is one feature: a journey spec (prompt text), its tools, and the values it mints. The skill list in `agent/skills/__init__.py` is the only registration point. The loop and prompt assembly never change when a skill is added.

- **Skill specs override global rules (D-48).** The system prompt is voice, then global rules, then one section per skill. The global rules say explicitly that a skill's spec wins on conflict. That's how the handoff journey drops the brand's upbeat "anything else for your next adventure?" close for a plain one, without special-casing it in the global rules.
- **Skills declare the values they mint, and the supervisor guards them (D-47).** A skill can declare `guarded_values`, for example escalation's `{"blocked_ticket": HT-…}` and Early Risers' `{"blocked_code": EARLYRISER-…}`. The supervisor combines these with the global URL pattern and blocks any match in a reply that no tool returned earlier in the conversation. The skill that creates a value knows its shape, so guarding a new kind of value (an RMA number, a gift card) is a change to that one skill, and the supervisor stays skill-agnostic.

## Measured behavior

Conversation scenarios run against the real model, k times each (pass^k: a scenario passes only if all k runs pass). Results from the latest run:

| Scenario | Rate | What it checks |
|---|---|---|
| `hiking_boots_vague_start` | 5/5 | says we don't carry boots; never presents a catalog item as a replacement; no invented links, prices or website referrals |
| `hiking_boots_size_and_price` | 5/5 | same, plus no size-availability claims |
| `product_no_repeated_clarifying_question` | 5/5 | asks "what are you planning?" at most once across turns |
| all 21 scenarios | 20/21 at k=2, then the one regression fixed and re-measured 5/5 | full regression pass after Early Risers was added |

The boots assertion is "never presents a catalog item as a *replacement* for the requested product type". Mentioning what we do carry ("I can help with backpacks or other gear") is allowed. An earlier, stricter version that failed on any mention of a poorly fitting product measured about 2/5. Those failures were category mentions, not substitutions, so the check was redefined to match the principle rather than tuning the prompt further (DECISIONS D-54).

## Observability

Every turn appends one record to `logs/trace.jsonl`. It holds the user message, reply, outcome, supervisor result, tool calls (args, results, latency), token counts, `model`, `temperature`, and a `prompt_hash` that fingerprints the system prompt plus tool schemas. Emails are masked (`j***@example.com`) before anything is written (DECISIONS D-38).

`--debug` prints the same tool calls and per-turn stats inline.

Model retries and timeouts use the openai client's built-in exponential backoff. The values (`MAX_RETRIES`, `REQUEST_TIMEOUT_S`, `MAX_TOOL_ITERATIONS`) live in `agent/config.py` (D-26).

## Known limitations

- **The order-lookup lockout is a demo control, not rate limiting.** After 3 failed lookups (failures, not attempts), the agent stops looking up orders *in that chat* and offers a handoff. It lives in process memory, so a new session resets it. Real protection needs server-side, per-identity, time-windowed limits (D-13, D-42).

## Taking this to production

- **An LLM supervisor layer.** The deterministic supervisor only catches what a regex can see: URLs, ticket IDs, discount codes. It can't catch prose hallucinations like "check our website's hiking boots section", which names no URL but still points the customer somewhere we can't vouch for. A second model that grades each reply against the tool results and policy would cover that class. Sierra's supervisor pattern is a checker layered over the agent, observing first and intercepting for high-risk topics. Today those prose cases are tracked as conversation-scenario checks (`NO_WEBSITE_REFERRAL`) rather than blocked.
