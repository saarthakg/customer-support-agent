# Sierra Outfitters Agent

A terminal customer-support agent for Sierra Outfitters, built on `gpt-4.1-mini` with a hand-rolled tool-calling loop (no agent frameworks).

> Work in progress: the full README (architecture, design decisions, transcripts) lands in Phase 4. Decisions are logged as they're made in [DECISIONS.md](DECISIONS.md).

## Quickstart

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # then set OPENAI_API_KEY
.venv/bin/python -m agent.main --debug
```

Tests (deterministic, no network): `.venv/bin/pytest`

## Data

`data/CustomerOrders.json` and `data/ProductCatalog.json` are transcribed from the PDF appendices by `scripts/extract_data.py`:

```bash
pdftotext -layout "Agent Building Prompt Appendices.pdf" appendices.txt
python3 scripts/extract_data.py appendices.txt data
```

The script fixes only PDF artifacts (a stray `None` line under each heading, and description strings wrapped across lines). Every value, typos included, is preserved exactly (DECISIONS D-01).
