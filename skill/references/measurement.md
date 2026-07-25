# Measurement Reference (tier semantics + token ladder)

## Context tiers (what loads when)
| Tier | Content | Billed |
|---|---|---|
| metadata | frontmatter name+description | every session, always |
| body | SKILL.md body | on every trigger (incl. false-positives) |
| conditional | references/ templates/ examples/ agents/ | only when read; needs read-conditions to be selective |
| script | scripts/ | ~zero context; executes instead of loading |
| asset | binaries | not context |

Optimization is tier-aware: a token moved from body to conditional is not
deleted — it stops being billed on triggers that don't need it. A token moved
into a script stops being billed at all.

## Token ladder (auto-selected by measure_tokens.py, always disclosed)
1. **api** — Anthropic `count_tokens` endpoint (needs ANTHROPIC_API_KEY).
   Exact for the named Claude model → label `measured`.
2. **tiktoken** — o200k_base. NOT Claude's tokenizer; Anthropic guidance says it
   undercounts Claude tokens ~15–20% on typical text (more on code/non-English).
   The harness reports raw + a Claude-adjusted range (×1.15–×1.25) → label
   `estimated`. Never present the raw tiktoken number as a Claude count.
3. **heuristic** — chars/3.5 cross-checked with words×1.3, wide interval →
   label `estimated (wide bounds)`.

Rung comparisons are invalid across rungs (see benchmark-protocol.md).

## Cost model
`cost_model.py` = input-side context cost only, per scenario (sessions ×
trigger-rate × ref-read-rate), as a RANGE per named model from the dated
pricing snapshot. It does not model output generation, retries, or latency —
those need live runs or stay projected. Cache columns assume the provider's
published multipliers and a stable prefix ≥ the model's cacheable minimum.

## Duplicate detection
Cross-file shared word-8-grams (exact set arithmetic → `measured`). High
overlap is a lead, not a verdict — semantic review decides whether the
duplication is load-bearing (R-01 vs R-10 vs deliberate variants).

## What is NOT measurable statically
Task success · retry counts · instruction adherence · injection resistance ·
latency · reasoning-token spend. These require live runs (live_eval_adapter.py
path) or remain `projected` with cited evidence.
