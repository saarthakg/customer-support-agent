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

## Observability

Every turn appends one record to `logs/trace.jsonl`. It holds the user message, reply, outcome, supervisor result, tool calls (args, results, latency), token counts, `model`, `temperature`, and a `prompt_hash` that fingerprints the system prompt plus tool schemas. Emails are masked (`j***@example.com`) before anything is written (DECISIONS D-38).

`--debug` prints the same tool calls and per-turn stats inline.

Model retries and timeouts use the openai client's built-in exponential backoff. The values (`MAX_RETRIES`, `REQUEST_TIMEOUT_S`, `MAX_TOOL_ITERATIONS`) live in `agent/config.py` (D-26).

## Known limitations

- **The order-lookup lockout is a demo control, not rate limiting.** After 3 failed lookups (failures, not attempts), the agent stops looking up orders *in that chat* and offers a handoff. It lives in process memory, so a new session resets it. Real protection needs server-side, per-identity, time-windowed limits (D-13, D-42).

## Taking this to production

- **An LLM supervisor layer.** The deterministic supervisor only catches what a regex can see: URLs, ticket IDs, discount codes. It can't catch prose hallucinations like "check our website's hiking boots section", which names no URL but still points the customer somewhere we can't vouch for. A second model that grades each reply against the tool results and policy would cover that class. Sierra's supervisor pattern is a checker layered over the agent, observing first and intercepting for high-risk topics. Today those prose cases are tracked as conversation-scenario checks (`NO_WEBSITE_REFERRAL`) rather than blocked.
