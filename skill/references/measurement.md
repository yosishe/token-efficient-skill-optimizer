# Measurement Reference (tier semantics + token ladder)

## Contents

- [Context tiers](#context-tiers-what-loads-when)
- [Measurement classes](#measurement-classes-always-disclosed)
- [Cost model](#cost-model)
- [Duplicate detection](#duplicate-detection)
- [Reachability](#reachability-the-undiscoverable-flag)
- [What is outside the modeled context](#what-is-outside-the-modeled-context)
- [Trigger surface](#trigger-surface)
- [Suppressions](#suppressions-are-always-stated)
- [What is not measurable statically](#what-is-not-measurable-statically)

## Context tiers (what loads when)
| Tier | Content | Billed |
|---|---|---|
| metadata | frontmatter name+description | every session, always |
| body | SKILL.md body | on every trigger (incl. false-positives) |
| conditional | references/ templates/ examples/ agents/ | only when read; needs read-conditions to be selective |
| script | scripts/ | source can stay outside context when executed; invocation/output still enter context |
| asset | binaries | outside the static text scan; tool/rendered content may still enter context |

Optimization is tier-aware: a token moved from body to conditional is not
deleted — it stops entering context on triggers that do not read it. Moving code
into a script avoids source loading only when the runtime executes it without
reading it; invocation and bounded output still count.

## Measurement classes (always disclosed)
1. **local proxy** — `auto`, `tiktoken`, or heuristic static package scan.
   Always offline and labeled `local_proxy_estimate`; no universal conversion to
   Claude tokens is applied.
2. **provider preflight** — explicit `--method anthropic-api --allow-network
   --request-json REQUEST.json`. Counts the complete structured request once for
   an exact model and labels the input result `provider_preflight_estimate`.
   It records provider, model, API surface/revision, measurement date, and the
   request SHA-256 without logging the request body. Its semantics are
   `preflight_input_only`: output, total run usage, cache segmentation, and cost
   remain typed unavailable.
3. **observed usage** — comes only from a completed adapter/runtime result under
   the v2 usage schema. The current offline runner remains
   `runtime_unverified`, so a hard-coded adapter result is not sufficient for a
   human `[measured]` claim.

Rung comparisons are invalid across rungs (see benchmark-protocol.md).

Both measurement modes emit claim-specific records under `/claims`. A local
scan binds the exact target snapshot and is recomputed by
`validate_report.py`; provider preflight binds the exact request SHA-256 while
persisting no request body. Use the claim's exact `display_bindings` text, then
append `evidence: measurement.json#/claims/<claim-id>`. This prevents an
unrelated measurement file or an altered displayed number from satisfying the
report gate.

## Cost model
`cost_model.py` has separate observed and modeled contracts. Observed mode
prices disjoint uncached/read/write/output buckets from a completed run.
Scenario mode additionally requires stable-prefix size, exact model minimum,
TTL, cold writes, hits, misses, dynamic suffix, and output assumptions. Missing
or mixed semantics return `unavailable`; no whole-request cache multiplier is
applied. Cost and context-window occupancy are reported separately.
The paired evaluator rejects adapter-provided cost and emits no cost claims;
cost must be recomputed through this model. When `cost_model.py --json` returns
an available result, it emits `/claims/cost.total_usd`; the validator reloads
the hash-bound input and effective-dated pricing profile and reruns decimal
arithmetic before accepting its exact `[estimated]` display binding.

## Duplicate detection
Cross-file shared word-8-grams (exact local scan; never `[measured]` usage). High
overlap is a lead, not a verdict — semantic review decides whether the
duplication is load-bearing (R-01 vs R-10 vs deliberate variants).

Two kinds of overlap are separated out and reported as information, not findings:
- `bilingual_sibling_pairs` — `X-en.md` vs `X.md`, intentional translations.
- `compiled_bundle_pairs` — a file the body itself declares to be the all-in-one
  rendering ("For the complete guide with all rules expanded: `AGENTS.md`").
  Its overlap with each constituent is the reason it ships. Declaration needs
  BOTH the filename and a bundle marker in the same markdown section, and the
  bundle must be the larger side of the pair; an undeclared near-copy is still a
  finding.

## Reachability (the "undiscoverable" flag)
A conditional-tier file is reachable when the **owning** SKILL.md body (a nested
package root governs its own subtree) names it, names a sub-directory of depth ≥ 2
containing it, a bundled script opens it by name, or — **by documented
convention** — the body lists its stem AND shows a concrete `<dir>/<name>.<ext>`
path for that directory. Listing 70 rule stems plus one path example is cheaper
than 70 literal paths; flagging all 70 penalised the better design.
Both guards still bite: a bare `references/` mention is not a pointer (depth
guard), and a stem the body never lists is still flagged.

## What is outside the modeled context
`artifact` tier: build metadata, human docs, rendered demos, and **runtime
config** — `metadata.json`, plus config-format files under `agents/`, which are
another runtime's manifest. The static scan excludes these unless explicitly
read; it does not claim they can never enter a future model context. Markdown
under `agents/` is a sub-agent prompt and stays in a context tier.

## Trigger surface
Trigger phrasing counts from a literal marker (`use when`, 触发词, `השתמש`) **or**
a semantic construction — `when <gerund>`, `when you/your`, `for <gerund>`. A bare
"when" is ordinary prose and is not accepted. When frontmatter sets
`disable-model-invocation: true` the skill never auto-triggers, so the
trigger-phrasing and negative-boundary checks are suppressed and the reason is
stated in the report's `informational` list.

## Suppressions are always stated
Every check the harness declines to apply appears in `informational` with its
reason. A suppressed finding is never silently dropped — that is how a
false-positive fix is told apart from a blind spot.

## What is NOT measurable statically
Task success · retry counts · instruction adherence · injection resistance ·
latency · reasoning-token spend. These require live runs (live_eval_adapter.py
path) or remain `projected` with cited evidence.
