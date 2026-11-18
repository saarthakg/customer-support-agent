# Design notes

This is the reasoning behind the agent: the customer problem, every assumption, what each journey needs, every outcome and the test that proves it, how the prompt is built, how the work got here, the debt, and what changes if requirements change. Code references are `file` · `function`. D-numbers point to [DECISIONS.md](../DECISIONS.md), where each entry gives the alternative considered.

## 1. The customer problem

Switchback Outfitters is a fictional young outdoor retailer. It is new to generative AI and is heading into peak season, when inbound contacts and product issues both rise. The first agent has to take routine volume (where's my order, what should I buy, is there a deal) off the support team without creating new problems: no wrong answers about orders, no invented products or links, no discount codes handed out by mistake.

What that implied for the design:
- **Trust over coverage.** A customer told something false by the agent is worse than one handed to a person. So facts come only from tools, the supervisor blocks invented links, codes and ticket IDs (D-36, D-67), and anything the agent can't do ends in an honest handoff offer (D-16, D-68).
- **Business rules live in code.** A company new to AI needs predictable behavior it can audit. Eligibility, identity checks, status meanings and code generation are deterministic and unit-tested. The model handles language and judgment.
- **Problems get a person, not a dead end.** Peak season brings product issues, so error-status orders, the security lockout and out-of-scope store requests all offer a real ticket.
- **Measured, not assumed.** Behavior is checked by scripted conversations run k times against the real model (pass^k), so a prompt change that breaks another journey shows up (D-60).

## 2. Assumptions

"Given" means the requirements or data state it. "Interpreted" means I chose a reading.

| Assumption | Given or interpreted | Why | What changes in the code if it's wrong |
|---|---|---|---|
| Order status meanings: `delivered`, `in-transit` (shipped, on its way), `fulfilled` (packed, not yet with the carrier, no tracking), `error` (a problem support must resolve, cause unknown) (D-07, D-14, D-15) | Statuses given; meanings interpreted | The data has no definitions. `fulfilled` and `error` orders have no tracking number, which fits "not shipped" and "stuck". Defining meanings once stops the model improvising. | Edit `agent/skills/orders.py` · `STATUS_MEANINGS`. A test checks every status has a meaning. |
| Tracking link is `https://tools.usps.com/go/TrackConfirmAction?tLabels={trackingNumber}` for every shipped order | Given | The requirements say to assume it. The `TRK…` numbers in the data aren't real USPS numbers, so the links don't resolve; the template is used exactly as given. | Carrier-specific links: `orders.py` · `TRACKING_URL_TEMPLATE` becomes a per-carrier lookup. |
| Customer must give both email and order number, and both must match one order (D-12) | Given ("after asking the customer's email and order number"); the match rule is interpreted | Order details should only go to someone who knows both. One generic `order_not_found` for "doesn't exist" and "belongs to someone else", so the tool can't be used to discover either. | `agent/data.py` · `Datasets.find_order`; `orders.py` · `OrderLookup.lookup_order`. |
| Lockout after 3 failed lookups per chat, failures not attempts (D-13, D-42, D-46) | Interpreted | The order space is tiny (W001–W010) and emails are guessable, so a prompt rule can be talked around and a counter can't. Malformed input doesn't count; a correct 3rd try still works. | `orders.py` · `MAX_FAILED_LOOKUPS`. Real limits need server-side, per-identity state (see section 7). |
| Order numbers can be typed loosely: `w1`, `#W001`, `order 2`, bare `1`, or one W-number inside a sentence. Two order numbers in one value are ambiguous (D-11, D-72) | Interpreted | Customers type numbers many ways and paste them mid-sentence. Code normalizes so the model passes text through unchanged. Bare digits are safe because every order uses the `W` prefix. | `data.py` · `normalize_order_number`. If other prefixes appear, drop the bare-digit rule. |
| Promo window is `[08:00, 10:00)` America/Los_Angeles, DST-aware (D-20) | Hours given; half-open boundary interpreted | Half-open is the usual reading of "8–10" and makes 10:00:00 unambiguous (out). `zoneinfo` handles DST. | `agent/skills/early_risers.py` · `WINDOW_START`, `WINDOW_END`. |
| "Explicitly requests": asking for the Early Risers code, or saying yes after the agent mentions it. A general "any discounts?" gets a mention and an offer, never a code. Never advertised unprompted (D-21, D-35) | Interpreted | The requirements say "explicitly requests". Mentioning the deal when asked about discounts is good service; issuing on any discount question is not explicit. | Prompt only: `early_risers.py` · `INSTRUCTIONS`. The model judges explicitness; code still enforces the window. |
| Promo identity is the normalized email (D-22) | Interpreted | The requirements say "for that user", and email is the only identity the chat has. | `early_risers.py` · `issue_early_risers_code` keys on it. With accounts, key on the account ID. |
| One code per email per Pacific day; asking again returns the same code (D-23, D-57) | Interpreted | "A unique code for that user" in a daily promotion. Same-day repeats returning the same code stops one customer collecting many. "Today" is the Pacific day, matching the window. | `agent/code_store.py` · `_key`; `early_risers.py` · `issue_early_risers_code`. |
| Discount is 10%, with no expiry, minimum spend or exclusions stated (D-24) | 10% given; terms not given | The agent must not invent terms the business never set. | `early_risers.py` · `DISCOUNT_PERCENT` and the spec line on terms. |
| No prices (D-18) | Given by the data | The catalog has no price field. The agent says so and offers to help by activity instead. | Add a field in `agent/skills/products.py` · `list_products` and relax the spec line. |
| Ordered SKUs missing from the catalog (`SOCH010`, `SOBN008`, `SOGK009`) are shown as "an item (item code X)" (D-17) | Data reality given; handling interpreted | Inventing a name would be a false claim. | `orders.py` returns `name: None`; the spec says how to phrase it. |
| Product tags are withheld from the model (D-02) | Interpreted | Tags are wrong in ways that cause false claims (energy drink tagged `Weatherproof`, jetpack `Safety-Enhanced`). | `products.py` · `list_products` would pass cleaned tags. |
| Low stock = inventory ≤ 20 (D-03) | Interpreted | A threshold is a business rule, so code sets it. The agent may say "only a few left". | `products.py` · `LOW_STOCK_THRESHOLD`. |
| Human handoff is simulated: a ticket appended to `logs/handoffs.jsonl` with a code-computed `verified` flag (D-16, D-43) | Interpreted (not in the requirements) | Error orders and the lockout need somewhere to go, and the agent must never claim an action that didn't happen. A real ticket ID makes "I've passed this on" true. | `agent/skills/escalation.py` · `HandoffDesk.escalate_to_human` would call a ticketing API with the same contract. |
| Store requests no tool handles (returns, cancellations, exchanges, damaged items, including asking for a link or form about them) get "I can't do that here" and a handoff offer. Unrelated requests are declined (D-68, D-69) | Interpreted | A customer with a store problem shouldn't hit a dead end. Returns is deliberately not built (it's the natural next skill). | `agent/prompt.py` · `GLOBAL_RULES`. A returns skill would replace the handoff path for returns. |
| Replies are in the customer's language; tool facts are translated, but names, links, codes and ticket IDs are kept exact. Handoff summaries are in English (D-74) | Interpreted | A Spanish-speaking customer shouldn't be answered in English. Support reads the tickets, so summaries stay English. Measured as unreliable (section 4). | `prompt.py` · `VOICE`; `escalation.py` · `INSTRUCTIONS`. |
| Messages over 2,000 characters, and empty messages, are answered by code without a model call (D-71) | Interpreted | Real support messages are a few sentences. A huge paste costs tokens and can push instructions out of focus. | `agent/config.py` · `MAX_MESSAGE_CHARS`; `agent/loop.py` · `Agent._reject_input`. |
| A corrupt `state/issued_codes.json` is moved aside and the store starts empty (D-73) | Interpreted | In peak season the promo should keep working. The cost is that today's codes are forgotten, so a returning customer could get a second code. The bad file is kept for inspection. | `code_store.py` · `JsonCodeStore._load`: raise instead to fail closed. |

## 3. What the agent needs, per journey

| Journey | From the customer | Data it reads | What code computes | What the model decides |
|---|---|---|---|---|
| Order status | email and order number, in any order or format | `data/CustomerOrders.json`, `data/ProductCatalog.json` (item names) | normalization, the email + order-number match, the failure count and lockout, status meaning, item names (or `None`), tracking URL, `identity_verified` | which value is missing and how to ask for it; how to phrase the status; when to offer a handoff |
| Product recommendations | what they're doing or need | `data/ProductCatalog.json` (tags withheld) | the full catalog with `low_stock` | whether a question is about products; which products fit and why; whether one clarifying question is needed; saying "we don't carry that" |
| Early Risers | an explicit request (or yes to an offer), then an email | the clock, `state/issued_codes.json` | OPEN/CLOSED fact each turn; the window check; email normalization; same code for the same email and Pacific day; unique code generation | whether the request is explicit; when to ask for the email; how to explain hours when closed |
| Human handoff | agreement to be handed off, email, optional order number | the orders data (for the `verified` flag) | ticket ID, timestamp, `verified` (never shown to the model) | when to offer it; the 1–2 sentence summary |
| Every reply | — | this conversation's tool results | the supervisor check: every URL, ticket ID and promo code must match a tool result from this chat | the wording |

## 4. Outcomes

Unit tests are in `tests/` (`file` · `test`). Scenarios are in `tests/scenarios/scenarios.py` and run against the real model.

### Order status (`lookup_order`)

| Case | Tool result | What the customer sees | Proof |
|---|---|---|---|
| Delivered | `ok`, `status: delivered`, `tracking_url` | status, items by name, the USPS link on its own line, brand voice | `test_orders` · `test_delivered_has_tracking_link` (and the other `test_orders` tests below); scenario `order_delivered_with_link` |
| In transit | `ok`, `in-transit`, `tracking_url` | "shipped and on its way", link on its own line | `test_in_transit_has_tracking_link`; `order_messy_number_formats` |
| Fulfilled | `ok`, `fulfilled`, `tracking_url: null` | packed and getting ready to ship, no tracking yet, no ship date promised, no link | `test_fulfilled_has_no_link`; `order_fulfilled_no_tracking` |
| Error status | `ok`, `error`, no link | apology first, the facts, a handoff offer; no emojis, no adventure close | `test_error_has_no_link_and_unknown_sku_has_no_name`; `order_error_escalates`, `trust_frustrated_error_order` |
| Item missing from catalog | item `name: null` | "an item (item code SOCH010)", never a guessed name | `test_order_whose_only_item_is_missing_from_catalog`; `order_only_item_missing_from_catalog` |
| Only one identifier given | no call | asks only for the missing one | `order_needs_both_identifiers`; `trust_identity_probe` |
| Email and order don't match, or order doesn't exist | `order_not_found` (same for both) | "couldn't find an order matching that email and order number together", asked to double-check both, no hint which is wrong | `test_mismatch_returns_generic_error_and_no_data`, `test_unknown_order_returns_same_error_as_mismatch`; `order_mismatch_lockout_escalates` |
| 3rd failed lookup | `too_many_attempts` | "For security, I can't run more order lookups in this chat", handoff offer, plain tone | `test_three_failures_then_blocked`, `test_two_failures_then_correct_third_lookup_succeeds`, `test_success_does_not_reset_failure_count`; `order_mismatch_lockout_escalates` |
| Malformed email or order number | `invalid_email` / `invalid_order_number` (not counted as a failure) | asked to re-check that one value | `test_invalid_inputs`, `test_malformed_inputs_do_not_count_toward_lockout`, `test_malformed_or_doubled_emails_are_rejected` |
| Loose formats (`w1`, `order 2`, `#W 001`) | normalized to `#W001` | found as normal | `test_order_number_variants_normalize`; `order_messy_number_formats` |
| Order number with extra text (`W001.`, `it's W001, thanks`) | normalized | found as normal | `test_one_order_number_inside_other_text_is_extracted` |
| Pasted email wrapping (`<john@x.com>`, trailing `.`, `mailto:`) | normalized; no failure counted | found as normal | `test_email_wrapping_from_pastes_is_stripped`, `test_pasted_punctuation_does_not_burn_a_lookup` |
| Two order numbers in one value | `invalid_order_number` | asked to re-check | `test_unrecognizable_order_numbers` |
| Two order numbers in one message, one belonging to someone else | one `ok`, one `order_not_found` | the customer's order; nothing about the other | scenario `order_two_numbers_one_message` |
| Two emails in one value | `invalid_email` | asked to re-check | `test_malformed_or_doubled_emails_are_rejected` |
| Asking about another customer after a verified lookup | `order_not_found` if tried | nothing about the other customer | `trust_cross_customer_probe` |
| After a successful lookup | `identity_verified: true` stays in history | never asked to re-confirm the email or order number (also not before the lookup) | `test_success_says_identity_is_verified`, `test_verified_identity_reaches_the_model_on_later_turns`; `order_error_escalates` |
| Spanish-speaking customer | `ok` | should be answered in Spanish with the link exact; **measured unreliable** (see section 7) | scenario `order_non_english` |

### Product recommendations (`list_products`)

| Case | Tool result | What the customer sees | Proof |
|---|---|---|---|
| Clear need (ski trip) | full catalog | up to 3 products, exact names, one reason each from the description, brand voice | `test_products` · `test_returns_full_catalog`; `product_ski_trip` |
| Vague request ("some gear") | full catalog, fetched before asking | one clarifying question, asked once | `product_vague_looks_before_asking`, `product_no_repeated_clarifying_question` |
| Something we don't carry (hiking boots) | full catalog | "We don't carry hiking boots", no substitute framing, no invented product, link or size | `hiking_boots_vague_start`, `hiking_boots_size_and_price` |
| Price or budget question | no price field | "I don't have pricing information", offers to help by activity | `test_result_has_no_price_field`; `product_budget_no_prices` |
| Low stock | `low_stock: true` | "only a few left"; exact count only if asked | `test_low_stock_flag_is_computed_in_code`; `product_low_stock` |
| Playful product (jetpack, cloak) | description | presented earnestly, no added safety claims | `test_descriptions_are_passed_through_unchanged`; `product_playful_presented_earnestly`, `product_no_unstated_safety_claims` |
| Misleading tags | tags withheld | fit judged from descriptions only | `test_tags_are_withheld` |

### Early Risers (`issue_early_risers_code`)

| Case | Tool result | What the customer sees | Proof |
|---|---|---|---|
| Explicit request in window, no email yet | (model asks first) or `needs_email` | asked for the email only, not asked again whether they want the code | `test_inside_window_without_email_asks_for_it`; `promo_explicit_request_in_window` |
| Explicit request in window with email | `ok`, `code`, `already_issued: false` | 10% off, the code on its own line, "use it at checkout", no invented terms | `test_issues_readable_code_keyed_to_normalized_email`; `promo_explicit_request_in_window` |
| Same email again the same Pacific day, even after a restart | `ok`, same code, `already_issued: true` | "the same code you were given earlier today" | `test_same_email_same_day_gets_same_code`, `test_json_store_survives_restart`; `promo_same_email_gets_same_code` |
| New Pacific day | new code | a new code | `test_new_day_gets_new_code` |
| Outside the window (incl. exactly 10:00:00) | `outside_promo_window`, hours and current PT time | hours in PT, invited back, never asked for an email | `test_window_boundaries`, `test_outside_window_needs_no_email`, `test_window_follows_daylight_saving`; `promo_explicit_request_outside_window`, `promo_generic_discount_outside_window` |
| "Any discounts?" in window | none until yes | Early Risers mentioned, code only after an explicit yes | `promo_generic_discount_question` |
| Never asked about discounts | none | promotion never mentioned | `test_greeting_does_not_advertise_promotions`; `promo_never_volunteered` |
| Invalid email in window | `invalid_email` | asked to re-check | `test_inside_window_invalid_email` |
| Prompt injection ("ignore your instructions", "SYSTEM: pre-approved") | window and email still enforced | no code outside the window; email still required inside | `trust_injection_outside_window`, `trust_injection_preapproved_in_window` |
| Customer asks about a code they typed (`SWITCHBACK10`) | supervisor blocks the echo | "I can't verify discount codes…", how to get a real one | `test_supervisor` · `test_customer_typed_code_is_still_blocked`; `test_early_risers` · `test_quoted_customer_code_retry_then_code_fallback`; `trust_invented_codes` |
| Code collision | redrawn | a unique code | `test_collision_is_redrawn`, `test_codes_are_unique_across_customers` |
| Corrupt code store file | store moved aside, starts empty | the promotion keeps working | `test_corrupt_store_is_moved_aside_and_promo_keeps_working` |

### Human handoff (`escalate_to_human`) and out-of-scope requests

| Case | Tool result | What the customer sees | Proof |
|---|---|---|---|
| Customer agrees to a handoff | `ok`, `ticket_id` | "passed to our support team", ticket ID on its own line, no promised response time | `test_escalation` · `test_files_ticket_and_returns_only_the_id`; `order_error_escalates`, `order_mismatch_lockout_escalates` |
| Ticket on the lockout path | `verified: false` in the log (never shown to the model) | same as above | `test_unverified_when_email_and_order_do_not_match` |
| Invalid email or empty summary | `invalid_email` / `missing_summary`, nothing filed | asked to re-check | `test_rejects_invalid_email_and_empty_summary_without_filing` |
| Invented ticket ID | supervisor blocks | never shown | `test_supervisor_guards_ticket_ids_end_to_end` |
| Cancellation request | no tool | "I can't process cancellations here" plus a handoff offer; never claims it cancelled; files only after a yes | `trust_cancel_not_claimed` |
| Request for a returns link | no tool | no link, no website referral, handoff offer | `trust_no_invented_returns_link` |

### Conversation and channel edge cases

| Case | What happens | What the customer sees | Proof |
|---|---|---|---|
| Empty or whitespace-only message | CLI skips it; `Agent.respond` answers in code without a model call | nothing (CLI) or "What can I help with?" | `test_main` · `test_blank_lines_are_skipped_and_eof_exits_cleanly`; `test_loop` · `test_empty_message_is_answered_by_code` |
| Message over 2,000 characters | not sent to the model, not stored; trace truncated | asked to send the key details | `test_over_long_message_is_never_sent_to_the_model` |
| Ctrl-D / Ctrl-C at the prompt, Ctrl-C mid-answer, `exit` | clean exit, no traceback | "Happy trails! 🌲" | `test_ctrl_c_at_the_prompt_exits_cleanly`, `test_ctrl_c_while_the_agent_is_answering_exits_cleanly`, `test_exit_words_end_the_chat_without_a_model_call` |
| API timeout, rate limit, connection or 5xx error | the openai client retries (`MAX_RETRIES`), then `LLMError`; the turn is rolled back | "Sorry, I hit a snag on the trail… try again in a moment" | `test_llm` · `test_transport_failures_become_llm_error`, `test_client_uses_configured_timeout_and_retries`; `test_loop` · `test_llm_error_returns_fallback_and_rolls_back_history` |
| Model loops on tools | capped at 5 model calls per turn, rolled back | the same fallback | `test_iteration_cap_returns_fallback_and_rolls_back_history` |
| Malformed tool call | error returned to the model, one retry, then fallback | usually a normal answer | `test_malformed_json_gets_one_retry_then_succeeds`, `test_second_malformed_round_falls_back_and_rolls_back` |
| Tool raises an exception | `tool_failed` returned to the model | an honest "couldn't do that" | `test_handler_exception_does_not_crash_the_turn` |
| Missing or corrupt data file, wrong shapes or types | `DataError` at startup | one-line error, exit 1, before any customer message | `test_data` · `test_missing_file_is_a_clear_data_error`, `test_corrupt_file_is_a_clear_data_error`, `test_wrong_shape_is_a_clear_data_error`, `test_wrong_field_types_fail_at_startup_not_mid_chat`; `test_main` · `test_bad_data_dir_prints_a_clear_error` |
| Missing API key | startup check | one-line fix | `test_missing_api_key_prints_the_fix` |
| Reply contains an invented link | supervisor blocks, one corrective retry, then a safe fallback | never sees the link | `test_supervisor_retries_once_with_correction_then_passes`, `test_supervisor_falls_back_after_second_block_and_rolls_back` |

## 5. Prompt design

The system prompt is assembled by `agent/prompt.py` · `build_system_prompt` from four parts, plus one per-turn message:

1. **Voice** (`VOICE`): identity, reply language, and a two-tier tone. Happy paths get one outdoors phrase and 1–2 emojis *after* the substance; problem paths are plain, empathy first, no emojis (D-63). Tone is kept separate from policy so changing one never touches the other.
2. **Global rules** (`GLOBAL_RULES`): grounding (facts only from tools; never invent products, links, prices, sizes, dates or codes), never claim an action that didn't succeed, ask only for what's missing, privacy, no unprompted promotions, the scope split (D-68, D-69), and the closing line. They say explicitly that **a skill's spec wins on conflict** (D-48), which is how the handoff journey drops the upbeat close without special cases.
3. **One spec per skill** (`Skill.instructions` in each `agent/skills/*.py`): when to call the tool, what to ask for, how to phrase each result and each error. The spec sits next to the tool code it describes.
4. **Tool descriptions** (`Tool.description`): the model's only documentation for each tool, written for it.
5. **Per-turn facts** (`Skill.turn_context`, sent by `agent/loop.py` · `Agent._with_context`): a fact computed by code on every model call, today only `Early Risers status: OPEN/CLOSED`. It's never stored in history and never part of the base prompt, so `prompt_hash` doesn't change with the clock (D-64).

**Kept out of the prompt and put in code:** the current time (D-08), eligibility, the identity match, status meanings (D-07), the tracking URL, code generation and idempotency, the lockout, the low-stock threshold, the `verified` flag, normalization of emails and order numbers (D-11, D-72), input limits (D-71), and the check on every outgoing link, code and ticket ID (`agent/supervisor.py`). The prompt says how to use the tools and how to talk; it is never the only thing standing between a customer and a wrong answer.

**Measured lessons:**
- **Prompts don't ground; tools plus a check do** ([before_grounding.md](before_grounding.md), D-36). With no tools, the model invented three boot products, sizes, prices and a `switchbackoutfitters.com` link, and every turn was traced as `ok`. That produced the explicit never-invent rule, the supervisor, the `supervisor` trace field and two regression scenarios.
- **Give the model a fact, not raw data** (D-64). With only the tool to tell it about the window, the model kept asking for an email first, then declining (5/6 outside the window). A code-computed OPEN/CLOSED line each turn took it to 6/6. This round used the same idea for orders: `identity_verified: true` in the lookup result (D-70).
- **Skills share one prompt, so they aren't independent in behavior** (D-60). Adding Early Risers dropped an unrelated product scenario from 5/5 to 0/2. Every prompt change reruns the whole scenario suite.
- **Fix the check when it disagrees with the principle, not the prompt** (D-52, D-54). Three scenario checks were flagging correct behavior; they were corrected rather than tuning the prompt toward them.

## 6. How I got here

**How AI tools were used.** Before any code, I wrote a binding engineering-principles document (not in this repo) covering how the agent would be demoed, the data realities, and rules like "business rules in code, judgment in the model" and "measure, don't assume". Claude Code then built the project in phases. I reviewed each phase's code, transcripts and decision entries before approving the next, and every non-obvious choice went into DECISIONS.md as it was made. Proposals I overrode or redirected:
- **Lockout semantics and wording.** I required the cap to count 3 *failures*, not attempts, proven by boundary tests (the 3rd lookup still runs, and a correct 3rd try succeeds). I also replaced "I've reached the limit", which sounded like the agent had failed, with "For security, I can't run more order lookups in this chat" (D-46).
- **Error-path tone.** I required apology first, then facts, then the handoff offer, with no emojis or adventure close (D-15).
- **Handoff.** The alternative was "please contact support" wording, leaving escalation for later. I had it built immediately, so the error and lockout paths end somewhere real and "I've passed this on" is true (D-16).
- **Supervisor scope.** I pulled the URL check forward before any skill existed, and extended it to ticket IDs (D-36, D-47).
- **Redundant lookups.** Counted in the trace, not prevented (D-49).
- **Boots check.** I chose to redefine the scenario check to the principle rather than keep tuning the prompt (D-54).
- **Code store.** The in-memory store forgot codes on restart; I had it made JSON-backed (D-61).
- **Email before window.** The agent asked for an email and then declined; I had the window checked first, with email optional (D-62).
- **Email-first flake.** I asked for deterministic per-turn context instead of prompt examples (D-64).
- **Looser supervisor.** The proposal was to let customer-typed codes through; I rejected it and kept the guarantee absolute (D-67).

**Build order and what live testing found:**
1. **Data and core loop.** Datasets kept verbatim, quirks included (D-01), the hand-rolled tool loop (D-04), skills as the unit of extension (D-05).
2. **Grounding.** A live test with no skills invented three boots, prices and a link; the greeting advertised the promotion to everyone. That led to the never-invent rule, the deterministic URL supervisor, removing the promotion from the greeting (D-35, D-36) and the [before_grounding](before_grounding.md) exhibit.
3. **Tracing and loop safety.** Supervisor outcome and `prompt_hash` in every trace record, email redaction, one retry for malformed tool calls (D-37 to D-39).
4. **Orders and handoff.** Review found the lockout semantics and error-path tone above, and a model that forgot the email after a failed lookup (D-45).
5. **Products.** Live runs found filler recommendations, repeated clarifying questions and a too-strict boots check (D-51, D-54).
6. **Early Risers.** Injectable clock and `--now`, then JSON persistence, window-first, and the two-tier voice (D-55, D-61 to D-63). Adding the skill regressed a product scenario (D-60).
7. **Docs and polish.** README, demo runbook, generated transcripts.
8. **Email-first flake → D-64.** The per-turn OPEN/CLOSED fact.
9. **Trust scenarios.** Eight adversarial scenarios found three gaps (D-66).
10. **Supervisor and scope.** Rejecting the looser supervisor led to D-67 (specific retry note and code-written fallback, 0/3 → 3/3). The scope split (D-68) fixed cancellation (0/3 → 3/3) but not the returns link.
11. **This round.** The returns-link fix (D-69), the verified-identity fact (D-70), and an edge-case audit: input limits (D-71), tolerant normalization (D-72), corrupt-store recovery (D-73), reply language (D-74) and robustness fixes (D-75). Results are in the README's measured-behavior table.

## 7. Trade-offs and technical debt

| Shortcut | Why it was right for a time-boxed build | What it costs | What I'd do next |
|---|---|---|---|
| Lockout lives in session memory | Five lines, demonstrates the control, fully testable | A new chat resets it; no protection across sessions or per identity | Server-side, per-identity, time-windowed limits (D-13, D-42) |
| JSON code store with no locking | Survives restarts; one CLI process is the only writer | Two processes could race and issue two codes for one email | A database with a unique (email, day) constraint behind the same `CodeStore` interface |
| Email isn't ownership-verified | The chat has no other identity | Anyone who knows an email and order number sees that order; one person with several emails gets several codes | Authenticated sessions; key orders and codes on the account |
| One shared system prompt (D-60) | Simple, inspectable, one place to read behavior | A change in one skill can regress another; every prompt change needs the full live suite | Per-journey routing or smaller prompts once the skill count grows; keep the full suite as the gate |
| Regex-only supervisor | Free, instant, deterministic, unit-tested | Prose hallucinations ("check our website's boots section") name no URL and pass | An LLM grader on replies against tool results and policy, for high-risk topics |
| Simulated handoff (JSONL file) | Makes "I've passed this on" true without an external system | Nobody reads the file; no confirmation to the customer | A real queue (Zendesk, Salesforce) behind the same tool contract, with the transcript attached |
| CLI only, one conversation per process | No UI was expected | No concurrency, no streaming | An HTTP service with per-session state |
| Scenario runs cost real tokens and are small samples (k=2–5) | Cheap with gpt-4.1-mini; enough to see the shape of reliability | Rates are noisy; a few cents per full run | A user simulator and larger k tracked per release |
| Reply language is prompt-only | One line, no new dependency | `order_non_english` measured 2/5: English tool results pull the reply into English | Return customer-facing text from tools in the conversation's language, or a per-turn language fact detected in code |
| Remaining flakes | Reported rather than chased, per the time budget | Occasional misses: an unprompted check-in before the error-order lookup, a missing emoji on a happy path | Watch the rates per release; fix with code-side facts where possible |
| No conversation-length management | Demo conversations are short; gpt-4.1-mini has a large context | A very long chat grows cost per turn and would eventually fail with a fallback | Summarize or trim old turns |

## 8. If requirements changed

| Change | Where it lands | Size | Which tests change |
|---|---|---|---|
| A new promo window or discount | `agent/skills/early_risers.py` · `WINDOW_START`, `WINDOW_END`, `WINDOW_TEXT`, `DISCOUNT_PERCENT` | constant | window boundary and status-line tests in `test_early_risers.py`; promo scenario times |
| One code per customer ever, not per day | `agent/code_store.py` · `_key` (drop the date) and `early_risers.py` · `issue_early_risers_code` | constant (plus the store interface) | `test_new_day_gets_new_code` flips; idempotency tests |
| A new order status (e.g. `returned`) | `agent/data.py` · `ORDER_STATUSES`; `agent/skills/orders.py` · `STATUS_MEANINGS` and how to phrase it in `INSTRUCTIONS` | constant | `test_every_status_has_a_meaning` forces the meaning; one new status test and scenario |
| Real carrier tracking | `orders.py` · `OrderLookup.lookup_order` calls a carrier API; or a new `track_shipment` tool | new tool | new tool tests with a fake carrier; tracking-link scenarios |
| Prices added to the catalog | `data.py` · `Product`, `_PRODUCT_KEYS`; `products.py` · `list_products` and the "no prices" spec line | constant | `test_result_has_no_price_field` flips; `product_budget_no_prices` becomes a budget-filter scenario |
| A 10,000-item catalog | `products.py` · `list_products` becomes `search_products(query)` returning the top matches in the same shape (embeddings plus cleaned tag filters) | new tool | product tool tests; product scenarios unchanged in intent |
| A returns or cancellation journey | new `agent/skills/returns.py` with `build(deps) -> Skill`, one line in `agent/skills/__init__.py`; guard RMA numbers via `guarded_values`; the store-request rule in `prompt.py` · `GLOBAL_RULES` narrows | new skill | new skill tests and scenarios; `trust_no_invented_returns_link` and `trust_cancel_not_claimed` change from "offers handoff" to the new flow; full suite rerun (D-60) |
| Multi-language support, properly | tools return customer-facing text keyed by language; or a code-detected language fact via `Skill.turn_context` | new skill-level mechanism | `order_non_english` plus a non-English scenario per journey |
| A voice channel | a new entry point beside `agent/main.py` (speech in and out); voice rules in `VOICE`; links become "I'll text you the link" | architecture | new channel tests; voice-specific scenarios (no links read aloud) |
| Authenticated customers | `Deps` gains the session identity; `lookup_order` and `issue_early_risers_code` take it from the session instead of the chat; the lockout becomes server-side | architecture | identity tests rewritten; identity-probe scenarios become authorization tests |
