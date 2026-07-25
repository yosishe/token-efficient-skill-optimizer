# token-efficient-skill-optimizer

A meta-skill that audits and optimizes existing AI skills, system prompts, agent
instruction sets, and workflows for token/cost efficiency — under hard
constraints: no material task-success loss, no safety weakening, no ambiguity
introduced to save tokens, honest measurement throughout.

## What it does / does not do

**Does:** audit context footprints by tier; recommend and apply evidence-backed
optimizations (38-rule registry; empirical rules cite resolved source records and
declared constraints remain explicit); produce
reviewable diffs and rollback paths; benchmark before/after with enforced
`[measured]` / `[estimated]` / `[projected]` / `[cache-dependent]` /
`[behavior-dependent]` / `[reported]` labels; validate other people's claimed savings;
batch-audit skill portfolios; refresh its own pricing/evidence base.

**Does not:** author new skills from scratch (use skill-creator); guarantee a
savings percentage in advance; run live model evals without your explicit
budget approval; optimize harmful skills; treat token count, billed cost, and
latency as the same thing.

## Supported inputs & runtimes

Markdown skill packages (SKILL.md + references/scripts/templates), bare system
prompts, agent instruction files, multi-file prompt repos. Static analysis is
provider-neutral, but normalized accounting is currently Anthropic-only. The
OpenAI pricing table in `config/provider-cost-profiles.yaml` is data-only and
cannot be selected until an OpenAI usage adapter exists.

## Install / setup

```bash
./scripts/install.sh          # copies this package to ~/.claude/skills/
python3 -m venv .venv && .venv/bin/pip install tiktoken pyyaml   # optional but recommended
```

Without the venv the harness degrades to its heuristic token rung (wide bounds,
still honestly labeled). It never transmits a target automatically. Anthropic
preflight counting requires `--method anthropic-api --allow-network
--request-json REQUEST.json` and is labeled a provider estimate, not measured
usage.

## Basic usage

Invoke the skill and name a mode (default Analyze):

- "Audit `path/to/skill` for token efficiency" → Analyze
- "Optimize it, balanced profile" → Apply (diff + change log + gates)
- "Is this vendor's savings claim real?" → Validate Existing Optimization
- "Where are we bleeding tokens across `skills/`?" → Batch Audit

## Configuration

- `config/default-settings.yaml` — profile, cost scenario, stop thresholds.
- `config/optimization-profiles.yaml` — conservative / balanced / aggressive
  (which rule tiers, gating). Safety tier S is on in every profile.
- `config/release-gates.yaml` — deliverable gates; package CI reports its current
  mechanical check count rather than embedding a stale number here.
- `config/provider-cost-profiles.yaml` — pricing snapshot (dated).

## How savings are measured

`scripts/measure_tokens.py` classifies static package tiers and emits a
`local_proxy_estimate`; it does not claim a Claude-equivalent count. Explicit
Anthropic preflight counts one complete request and emits only
`provider_preflight_estimate` input tokens. Structural byte/line figures are
exact local scans, not `[measured]` usage. Measurement JSON exposes
claim-specific, exact-display records that bind the target or request SHA-256.
`scripts/cost_model.py` prices only explicit, disjoint provider usage buckets
or a fully specified cache scenario; ambiguous semantics return a typed
unavailable result. Available cost JSON binds its input and pricing-profile
bytes and exposes a recomputable `cost.total_usd` claim.
`scripts/validate_report.py` rejects unlabeled numbers and resolves every
quantitative target claim to its exact typed claim record rather than accepting
an unrelated data file. Version 1.2 has no
live-attestation verifier, so every `[measured]` claim fails closed; adapter
output remains `runtime_unverified` until a separately reviewed live path exists.

## Updating pricing & refreshing research

Run the **Refresh Evidence** mode (`references/refresh-protocol.md`): fetches
official pricing pages (verbatim, dated), re-checks source statuses, updates
`rules/rules.yaml` confidence classes, regenerates `references/rules.md` +
evidence matrix via `scripts/render_rules.py`, bumps VERSION. Requires live web
access — refuses to fake currency without it.

## Running tests

```bash
python scripts/run_tests.py       # deterministic suite (schema, registry, validator, determinism, dogfood, config)
python scripts/validate_package.py .    # the 11 release gates, as a CI check
```

The suite is mutation-verified: each test is confirmed to FAIL when the behavior
it covers is deliberately broken. A test that has never failed proves nothing.

Test splits — ids are unique across all four:

| file | n | what it is |
|---|---|---|
| `tests/cases.jsonl` | 20 | development cases |
| `tests/safety.jsonl` | 8 | every row `critical: true` |
| `tests/injection.jsonl` | 12 | every row `critical: true`, each with a named vector |
| `tests/holdout.jsonl` | 8 | independently authored — **never tune against these** |

`tests/evaluation-rubric.md` holds the grading rules. For live paired A/B runs
(budget approval required), `scripts/eval_runner.py` executes a seeded randomized
schedule against an adapter and `scripts/eval_report.py` produces paired deltas
with a bootstrap CI over unique case-level means. It returns null below 5
unique cases, regardless of repeated trial count, rather than inventing an
interval. `scripts/live_eval_adapter.py` emits a
skill-creator-compatible `evals.json` plus a hash-bound, `runtime_unverified`
case-identity manifest.

## Interpreting benchmark reports

Three sections, never mixed: **Measured** (completed observed usage with a
claim-specific `report.json#/claims/<claim-id>` pointer), **Estimated**
(provider preflight, tokenizer/local proxies, or modeled quantities), **Projected**
(quality/latency hypotheses from cited evidence — anything not live-run). "What didn't
work" lists zero-benefit and rolled-back changes; its absence means the report
is non-compliant, not that everything worked. A finding of "already efficient,
no meaningful savings" is a successful outcome.

## Worked examples

### 1. Simple — audit a small skill
"Audit `~/.claude/skills/rtl-check`." → harness run, tier table, and either
grounded findings or an "already efficient" verdict—no forced edits.

### 2. Complex — pilot optimization of a multi-file pipeline skill
The bundled historical pilot went through Apply/Balanced: a description boundary
was added (flagged as a routing change), body sections were extracted with
read-conditions, discoverability risks were wired in, and duplicated agent
boilerplate was factored to a shared core. Its old proxy figures do not qualify
under schema v2. See
[`docs/RESULTS.md`](../docs/RESULTS.md) for what was and was not measured, including
a whole-scenario result that came out at effectively zero and is reported at that
value.

### 3. Rejected on quality grounds
Example-set pruning (R-14) on a skill with no eval data: the rule's
`do_not_apply_when` fires ("no eval exists to test discrimination — defer, do
not guess"). The report records the skipped finding instead of guessing which
examples matter.

### 4. A LONGER instruction kept (and added) on purpose
Wiring previously-undiscoverable reference files into the body ADDS tokens on
every trigger — and is still correct, because unreachable references are either
dead weight or silent capability loss causing failed/retried tasks. The change
log records it as a deliberate cost increase. Same logic keeps explicit output
contracts: a clear contract can be worth its context cost when it prevents
failed or retried work, but that trade must be observed rather than assumed.

### 5. Tool-output compression (R-08)
A skill echoing raw API responses into context gets a filter step: task-aware
summaries with grounding preserved; verbatim-required cases (quotes, diffs)
exempted. Evidence: RECOMP-class compression retains accuracy at a fraction of
tokens; query-BLIND filtering measurably hurts faithfulness — so the filter is
always query-aware.

### 6. Context pruning (R-12)
A workflow loading a whole corpus per query gets query-scoped loading, with
similar-but-irrelevant content prioritized for removal (that class measurably
harms accuracy) and critical content kept out of mid-context positions.
Validated on a grounded-answer spot set before shipping.

### 7. Safety-focused
"The compliance paragraph is the longest part — compress it hard." → Refusal
with rule citation (R-S1): safety/compliance text is exempt; apparent
safety-prompt edits can move harmful compliance and false refusals unpredictably.
Savings are found in non-safety spans
instead. If the user insists on consolidation, it requires explicit sign-off
recorded in the change log — and the diff still shows zero net weakening.

## Safety limitations & known failure modes

- Static analysis cannot prove behavioral equivalence — Tier-2 changes are
  validation-gated and reversible, but residual risk is nonzero (that is why
  aggressive mode demands an eval).
- The tiktoken rung is an approximation; cross-rung comparisons are invalid and
  the benchmark protocol forbids them.
- Quality/latency effects without live runs are projections from literature —
  directionally supported, not guarantees for your workload.
- The optimizer treats targets as untrusted, but graders/reviewers should still
  check the injection-findings section of every report.
- Pricing snapshots go stale; cost figures carry their snapshot date.

## Rollback

Every Apply run freezes a baseline copy before editing and logs a per-change
rollback. To roll back fully: restore the frozen baseline (gate G-02 guarantees
it exists and is untouched). Per-change: follow the change record's rollback
line in the semantic diff.

## Contributing evidence & rules

Add sources to the research base with full records (verified-primary only —
fetch the primary page; no citations from memory). Add/modify rules in
`rules/rules.yaml` with mechanism, risks, evidence ids, validation test,
rollback; run `scripts/render_rules.py` (cross-checks + regenerates docs);
bump VERSION and note it in CHANGELOG.md.
