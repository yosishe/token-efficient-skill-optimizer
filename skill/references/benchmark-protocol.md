# Benchmark Protocol v2 (Benchmark + Validate modes)

## Contents

1. Compare equivalent requests
2. Canonical v2 runtime envelope
3. Pair integrity and safety
4. Claim-specific evidence
5. Static and live layers
6. Acceptance

## 1. Compare equivalent requests

Use the same file/request boundary, exact model, provider API surface, usage
semantics, trial schedule, and effective-dated pricing profile on both arms.
Never compare a provider preflight estimate with observed usage or a local
proxy from a different tokenizer. Record all dimensions in the run header.

Static skill scans are `local_proxy_estimate`. A provider count endpoint is a
`provider_preflight_estimate`; it is not completed usage. Only a completed
runtime response with provider/model provenance is `observed_usage`.

## 2. Canonical v2 runtime envelope

Adapters return one closed metric class:

```text
provider_preflight_estimate  local_proxy_estimate  replayed_fixture
observed_usage               derived_cost          unavailable
```

Completed observations and replayed fixtures use
`usage_semantics: canonical_v2`. A provider count endpoint uses
`usage_semantics: preflight_input_only` and must bind the exact provider,
model, API surface/revision, measurement date, and request SHA-256. It exposes
only `estimated_input_tokens`; output/cache/iteration fields are rejected.

For Anthropic observations, report these mutually-exclusive buckets per
iteration:

```text
uncached_input_tokens
cache_read_input_tokens
cache_creation_5m_input_tokens
cache_creation_1h_input_tokens
output_tokens
```

`output_tokens` is inclusive. `thinking_tokens`, `retrieved_tokens`, and
`tool_result_tokens` are diagnostic subsets and are never added again. When
iteration rows exist, their sums are authoritative; conflicting duplicate
top-level values yield `unavailable(iteration_total_mismatch)`.

Valid v1 rows containing only aggregate input/output remain
`legacy_aggregate`. Numeric optional token fields without declared inclusion
relationships—or unknown token-like field names, including a numeric zero—
yield `legacy_ambiguous` and no normalized total. Undeclared or headerless
legacy usage defaults to `unavailable`, not observed usage.

The evaluator rejects adapter-supplied `cost_usd`, including zero. Cost is a
separate calculation contract: pass normalized disjoint usage to
`cost_model.py` with an effective-dated pricing profile. Rate-table arithmetic
is `derived_cost`; the paired evaluator does not emit cost claims. The cost
calculator's JSON does emit `/claims/cost.total_usd`, bound to the exact input
and pricing-profile hashes and recomputed by `validate_report.py`.

## 3. Pair integrity and safety

Pair only by stable `case_id + trial`. Each key must have exactly one baseline
and one candidate row. Duplicate cells, unexpected variants, and orphan pairs
reject the pair-integrity gate; they are never overwritten or silently
dropped.

The run header binds the exact case/trial/variant schedule with
`schedule_sha256`. The reporter re-reads the hash-bound case files and checks
their ordered IDs against the header, so removing both arms or substituting a
different complete pair cannot hide behind an unchanged row count. Old logs
without this exact v2 schedule manifest remain compatible for inspection but
their release gate is unresolved.

Report the full critical-failure and task-success transition matrices:

```text
pass→fail  regression
fail→pass  recovery
fail→fail  unresolved
pass→pass  pass
```

Any critical `pass→fail` fails the safety gate even when another failure was
recovered. A noncritical task-success `pass→fail` requires a quality
non-inferiority review. Aggregate counts cannot cancel pair-level regressions.

## 4. Claim-specific evidence

Every target-specific quantitative line—`[measured]`, `[estimated]`,
`[projected]`, `[cache-dependent]`, `[behavior-dependent]`, or numeric
`[not measured]`/`[not modeled]`—must point to its own machine-readable claim:

```text
evidence: report.json#/claims/<claim-id>
```

The claim binds metric/calculation version, value, unit, denominator, evidence
class/domain, usage semantics/date, provider/model/API metadata, raw-log and
canonical-run SHA-256, adapter/config/case-manifest hashes, producer commit,
and exact renderer display bindings. `raw_log_sha256` covers exact stored
bytes. The versioned canonical hash excludes timestamps, wall-clock values,
and absolute paths before sorting records and serializing JSON.

`scripts/validate_report.py` resolves the JSON pointer, recomputes the complete
claim from the hash-bound source log, and rejects any changed value,
denominator, displayed slot, class, provider/model, or producer commit. A
generic existing harness file is not claim evidence. Fixture output is
`replayed_fixture` and cannot substantiate a live-model `[measured]` claim.
`[reported]` is the exception: it traces a third party's figure to an external
source ID and locator instead of presenting it as target evidence.

## 5. Static and live layers

The static layer is always available:

1. Run `measure_tokens.py` on both arms with identical offline flags.
2. Report exact local structural byte counts as `local_proxy_estimate`, never
   with the human `[measured]` label; tokenizer proxies are estimated too.
3. Run `cost_model.py` with one dated scenario; keep cache-price effects
   separate from context occupancy.
4. Attribute changes to rule IDs and disclose skipped/rolled-back changes.

The live layer is optional and requires explicit budget approval.
`live_eval_adapter.py` only emits an eval-case file plus a hash-bound manifest
that preserves source case IDs, criticality, and split while labeling the
export `runtime_unverified`. After the approved runtime executes, a separate
adapter must normalize actual responses through `eval_runner.py`. Adapters may
declare usage-only `EVIDENCE_CLASS` plus separate
`QUALITY_EVIDENCE_CLASS`/`SAFETY_EVIDENCE_CLASS`; missing domain declarations
remain unavailable. The runner rejects a usage-class mismatch and never lets
an adapter name, location, provider string, or producer environment variable
establish live verification.
Then run:

```bash
python scripts/eval_report.py RUN.jsonl --json report.json
```

Do not call an export, fixture, skipped test, or provider preflight a live run.
The current runner deliberately emits `runtime_unverified`; it cannot produce
a valid `[measured]` claim. A future live path needs a post-run attestation
binding the raw log, schedule, variants, adapter/config/cases, exact
provider/model, producer commit, and eligible evidence domains.
Semantic evaluator fixtures for commitment retention, temporal supersession,
provenance, and abstention live in
`tests/fixtures/eval-v2/retention-scorer-cases.json`. They test scorer behavior
only; they do not implement context mutation.

## 6. Acceptance

An optimization succeeds only when its honestly classified footprint or cost
improves by a practical amount, pair integrity passes, there are no
candidate-only critical failures, quality passes the selected non-inferiority
review, and the Markdown passes `validate_report.py`. “No meaningful savings
available” remains a valid result.
