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
