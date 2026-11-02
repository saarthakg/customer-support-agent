# Demo runbook

Run top to bottom. Every step lists what to type and what you should see. Total time is about 10 minutes, and each step stands alone, so skip freely.

## 0. Setup check (before the interview)

```bash
cd sierra-outfitters-agent        # the folder the submission zip extracts to (or your clone)
conda deactivate 2>/dev/null; source .venv/bin/activate   # prompt shows (.venv), not (base)
pytest -q                                                 # expect: 139 passed
rm -rf state/                                             # fresh promo-code store for the demo
python -m agent.main --help                               # shows --debug and --now
```

If something's off:

| Symptom | Fix |
|---|---|
| `Missing dependency 'dotenv' (is the virtualenv active?)` | `source .venv/bin/activate && pip install -r requirements.txt` |
| `OPENAI_API_KEY is not set` | `cp .env.example .env` and put the key in `.env` |
| Early Risers says "you already have a code" unexpectedly | an earlier rehearsal used the same date: `rm -rf state/` |

Have these open in an editor: `agent/loop.py`, `agent/skills/__init__.py`, `agent/skills/early_risers.py`, `docs/before_grounding.md`.

## 1. Orders: happy path, with tool calls visible

```bash
python -m agent.main --debug
```

Type: `Hi, where's my order? john.doe@example.com, W001`

Expect a dim `→ lookup_order({...})` and `← {... "status": "delivered" ...}`, then a reply that leads with "delivered", names both items, puts the USPS link **on its own line**, and closes with an outdoors phrase plus 1–2 emojis. The stats line shows `supervisor pass`.

*Talking point:* the model passed `"W001"` exactly as typed, and code normalized it to `#W001` and built the URL. The link in the reply was checked against the tool result before it was printed.

## 2. Orders: unhappy paths (same session, or restart)

**Error status, missing SKU, handoff.** Type: `can you check W004 for bob.brown@example.com` and then `yes please`

Expect an apology first, then the cloak plus "an item (item code SOCH010)" (never an invented name), then a handoff offer. After "yes": `→ escalate_to_human`, and a reply with a real `HT-XXXXXX` ticket ID. **No emojis** on this path. Show the ticket: `tail -1 logs/handoffs.jsonl`. Note `"verified": true`, computed by code.

**Mismatch and lockout** (restart first, since the cap is per session). Type: `check order W002, my email is john.doe@example.com`, then `try W003`, then `what about W004?`

Expect the same generic "couldn't find an order matching that email and order number together" twice, with no hint that W002 exists or whose it is. The third failure gets "For security, I can't run more order lookups in this chat" and a handoff offer.

## 3. Products

**Happy path.** Type: `I'm heading on a ski trip next month, what should I get?`
Expect `→ list_products({})` *before* any question, then Crain's Summit Pro X Skis with a reason from its description.

**Unhappy path: something we don't carry.** Type: `interested in hiking boots`, then `10.5 US`
Expect "We don't carry hiking boots", with no invented products, no link, no price, no substitute framing, and an honest "no size information" for 10.5.

*Talking point:* open `docs/before_grounding.md`. The same conversation, before grounding, invented three boots, a size, prices and a `sierraoutfitters.com` link. That exhibit drove the supervisor and two regression scenarios.

## 4. Early Risers, with a frozen clock

**Inside the window.**
```bash
python -m agent.main --debug --now 2026-11-03T08:30
```
The dim line `[clock frozen at 2026-11-03 08:30 AM Pacific]` confirms the override.
Type: `Can I get the Early Risers code?`
Expect a request for your email (no code yet). The `--debug` stats line shows `context: Early Risers status: OPEN until 10:00 AM PT`, a fact computed by code each turn; the model never sees the clock. Type `jane.smith@example.com` and expect the code `EARLYRISER-XXXXXX` on its own line with "10% off".

**Idempotency across a restart.** Type `quit`, then run the same command again (`--now 2026-11-03T08:30`).
Type: `Hi, I'd like the Early Risers code. My email is Jane.Smith@example.com`
Expect **the same code** and `"already_issued": true` in the tool result. The capitalized email normalizes to the same customer. The code lives in `state/issued_codes.json`.

**Outside the window: no email requested.**
```bash
python -m agent.main --debug --now 2026-11-03T14:20
```
Type: `Do you have any discounts right now?` and then `Can I get the code anyway? My email is jane.smith@example.com`
Expect a mention of Early Risers with its hours (only because they asked about discounts) and that it's closed right now, with **no request for an email**. The second message gets a friendly no (closed, runs 8–10 PT) and no code. The model was told `Early Risers status: CLOSED`, so it doesn't need to call the tool. If it did, the tool would refuse anyway: code enforces the window.

**Boundaries.** The same request at each time shows the half-open window:
```bash
for t in 07:59 08:00 09:59 10:00; do
  printf 'Can I get the Early Risers code? My email is hannah.lewis@example.com\nquit\n' |
    python -m agent.main --now 2026-11-03T$t | grep -E "Sierra:|EARLYRISER" | tail -2
done
```
Expect no code at 7:59, a code at 8:00 and 9:59, and no code at 10:00.

*Talking point:* the model is never told the time, only a code-computed fact (OPEN or CLOSED) each turn. Eligibility, the code and idempotency are all in `early_risers.py`, and its tests cover 7:59:59, 8:00, 9:59:59, 10:00 and DST.

## 5. Observability

```bash
tail -1 logs/trace.jsonl | python -m json.tool
```
Point out `supervisor`, `tool_calls`, `redundant_tool_calls`, `prompt_hash` (ties the reply to the exact prompt and tool contract), and masked emails (`j***@example.com`).

## 6. Reliability (optional, about 1–2 minutes)

```bash
python -m tests.scenarios.run_scenarios -k 2 --only promo
```
Expect a per-scenario `PASS 2/2` and a `pass^2` summary. Reliability is reported as a distribution, not one lucky run.

## 7. Where the live extension goes

Open `agent/skills/__init__.py`: the enabled-skill list. A new feature (returns, order cancellation, store hours) is one new module in `agent/skills/` plus one line here, plus a scenario. `loop.py` and `prompt.py` don't change.
