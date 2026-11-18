# Exhibit: before grounding

Two live sessions from early development (`logs/trace.jsonl`, 2026-11-02), exported verbatim apart from the store name, which was changed later. The agent had **no tools enabled**, so it had no catalog at all, only the voice and rules prompt. The catalog has no boots.

They're kept as an exhibit because they show why grounding and supervision live in code: a fluent model with nothing to ground on confidently makes things up, and the trace marked every one of these turns `outcome: "ok"`.

## Session 9cd1151d: invented URL

**Customer:** yeah can you help me find some gear

**Agent:** Absolutely! What kind of gear are you looking for—backpacks, tents, hiking boots, or something else? 🥾🌲

**Customer:** boots

**Agent:** Great choice! Are you looking for hiking boots, trail running shoes, or something else for your outdoor adventures? 🥾

**Customer:** hiking boots

**Agent:** Got it! Do you have a preferred brand, size, or any specific features like waterproofing or ankle support for your hiking boots? 🥾🌄

**Customer:** no

**Agent:** No worries! Here’s a solid pick for versatile hiking boots that handle a variety of trails and weather. Would you like me to share a link to some top-rated options? 🥾

**Customer:** yes

**Agent:** Here’s a link to our hiking boots collection where you can explore different styles and find your perfect fit:  
https://www.switchbackoutfitters.com/hiking-boots  
Onward into the unknown! Let me know if you want help narrowing down choices.

**What went wrong**
- Four turns of clarifying questions (category, type, brand/size/features) before any answer.
- Turn 4 claims "a solid pick" that doesn't exist.
- Turn 5 invents `https://www.switchbackoutfitters.com/hiking-boots`. No tool returned it, and the domain isn't ours to promise.

## Session 009a475d: invented products

**Customer:** interested in hiking boots

**Agent:** Great choice! 🥾 Hiking boots are essential for hitting the trails with confidence. Do you want recommendations for men’s, women’s, or kids’ boots? Or are you looking for a specific feature like waterproofing or lightweight design?

**Customer:** men's waterproof ones

**Agent:** For men’s waterproof hiking boots, we have several rugged options built to keep your feet dry on wet trails. Would you like me to list some top picks or check availability for a specific size?

**Customer:** yes please

**Agent:** Could you please tell me your shoe size? That way I can find the best waterproof hiking boots ready for your next trek! 🥾

**Customer:** 10.5 US

**Agent:** Thanks! Here are some men’s waterproof hiking boots available in size 10.5 US:  
- Switchback Trail Waterproof Boots  
- Mountain Ridge GTX Boots  
- Cascade Peak Waterproof Hikers  
Would you like details or prices on any of these? Onward into the unknown! 🌲

**What went wrong**
- Three invented products: "Switchback Trail Waterproof Boots", "Mountain Ridge GTX Boots", "Cascade Peak Waterproof Hikers".
- It claims stock "in size 10.5 US". The catalog has no sizes.
- It offers prices. The catalog has no prices.
- Three clarifying questions before an (invented) answer.

## What changed because of this

| Failure | Fix | Where |
|---|---|---|
| Invented products, prices, sizes, availability | Explicit rule: if no tool provides a fact, say you can't help with that here | `agent/prompt.py` GLOBAL_RULES |
| Invented URL reaching the customer | Deterministic supervisor check: every URL in a reply must have come from a tool result in this conversation; one corrective retry, then a safe fallback | `agent/supervisor.py`, `agent/loop.py` (D-09, D-36) |
| Trace said `"ok"` | Per-record `supervisor` field | `agent/trace.py` (D-37) |
| Questions before answers | Products journey spec: call `list_products` first, ask at most one clarifying question | `agent/skills/products.py` |
| Regression | Both sessions are conversation scenarios: `hiking_boots_*` | `tests/scenarios/scenarios.py` |
