# token-efficient-skill-optimizer

[![deterministic validation](https://github.com/yosishe/token-efficient-skill-optimizer/actions/workflows/ci.yml/badge.svg)](https://github.com/yosishe/token-efficient-skill-optimizer/actions/workflows/ci.yml)

A skill that audits and optimizes **other** AI skills, system prompts, and agent
instruction sets for token and cost efficiency — under hard constraints: no material
task-success loss, no safety weakening, no ambiguity introduced to save tokens, and
honest measurement throughout.

It is built for the case where the obvious approach fails: asking a model to "shorten
this prompt" reliably produces something shorter, and gives you no way to know what it
quietly broke.

## What you get from one run

Point it at a skill directory and it answers three questions you probably cannot answer
today:

**1. What does this actually cost?** Not "how big is the folder." A package has tiers, and
only some are expected when the skill fires: the description is discovery metadata, the
body loads on a trigger, references are intended for task-specific reads, and script source
can stay outside context when executed. Invocations and script output still consume
context, and any file consumes context if the model reads it. The harness keeps those
cases separate and reports static routing as an estimate, not proof of runtime reads.

**2. What is silently broken?** The most common real finding is not waste — it is a
`references/` file that nothing points at. That is not dead weight you can delete for a
saving; it is a capability with no direct route from the skill body. Static analysis
cannot rule out dynamic access, so the finding is a discoverability risk, not proof that
the model can never reach it. A historical multi-file pilot found several such risks.

**3. What is safe to change?** Every proposed edit carries its rule, its evidence, its
risk scores, and its rollback. Safety spans are refused outright rather than compressed.

And when the answer is "this is already fine," it says so and stops. The historical
pilot below did exactly that.

## What makes this different from asking a model to shorten a prompt

- **It can tell you not to.** Several rules exist only to *stop* an optimization —
  keep a repetition that looks redundant but is load-bearing, keep a verbose instruction
  carrying a safety obligation, keep a longer prompt when the shorter one costs more in
  retries. "Already efficient, no meaningful savings" is a successful outcome.
- **Empirical rules cite evidence, and citations are machine-checked.** The
  38-rule registry resolves citations against 82 source records; declared
  constraint rules remain explicitly non-empirical. A cited id that does not
  resolve fails the build.
- **Numbers carry enforced labels.** `[measured]`, `[estimated]`, `[projected]`,
  `[cache-dependent]`, `[behavior-dependent]`, `[reported]`. A `[measured]` claim without a pointer to
  its data file is rejected mechanically — including in this repository's own reports.
  Version 1.2 has no live-attestation verifier, so it fails every `[measured]`
  claim closed rather than trusting a hand-authored runtime flag.
- **Token count, billed cost, and latency are never conflated.** A change that cuts
  tokens can raise cost (cache-write premium) or raise latency (more round-trips).
- **Safety sits outside the scoring system.** Safety rules are pinned at maximum priority
  and cannot be disabled by any profile or config key; the package validator fails the
  build if a profile omits one.

## What it does not do

Author new skills from scratch. Guarantee a savings percentage in advance. Run live model
evaluations without your explicit budget approval. Optimize harmful targets.

## What is proven

| | |
|---|---|
| **It finds real bugs.** It caught one in its own package: the check that stops a rule citing a nonexistent source crashed in every *installed* copy, because it resolved a path that only exists in a development tree — so the gate was decorative exactly where the tool runs. | verified from an orphaned copy |
| **It has an auditable historical safety record.** The published v1.1 grading record shows no candidate-only critical regression in that run. It predates schema v2 and is not live-model evidence for this release. | [archived grading record](docs/data/grading-record-2026-07-25.json) |
| **It treats false positives as defects.** A historical portfolio audit exposed several heuristic failure modes; the fixes and the fact that the current rate has not been re-measured are disclosed together. | [`docs/RESULTS.md`](docs/RESULTS.md) |
| **Its checks are continuously enforced.** The workflow reports exact executed, passed, failed, skipped, and package-gate counts for each commit; it fails when mandatory tests disappear. | [deterministic CI](https://github.com/yosishe/token-efficient-skill-optimizer/actions/workflows/ci.yml) |

## What is not proven

**That its optimizations measurably improve quality.** The paired A/B evaluation that
would have established this was run, and returned **inconclusive** — one arm reconstructed
stand-in targets while the other declined to, a divergence caused by guidance issued
mid-run rather than by anything under test. The full account, including the protocol
defect that caused it, is in [`docs/RESULTS.md`](docs/RESULTS.md).

One shipped change — enumerating a target's obligations before editing — appeared too
rarely in the archived evaluation to support a capability claim. It ships as procedure,
not as a demonstrated capability.

And a whole-scenario pilot optimization produced no meaningful reduction under
the historical v1.1 proxy. That proxy used an unsupported cross-tokenizer adjustment,
so its numeric output is retained only in the explicitly non-qualifying archive rather
than promoted here. Skills that
trigger rarely save little no matter how well they are optimized — which is exactly the
answer you want before spending a week on one.

## Tried on real skills

The historical pilot covered `improve-codebase-architecture`,
`react-best-practices`, and `frontend-design` at pinned commits. No prose was
compressed or reworded: each candidate was a verbatim move or a
delete-with-citation, so the semantic diff remained reviewable.

**Quality was evaluated, not assumed.** The archived blinded paired comparison
found no clear quality regression in the two retained changes, but it predates the
schema-v2 evidence contract and cannot substantiate a current `[measured]` claim.

**The third one was reverted by its own evaluation, and it is the most useful result here.**
The relocated material was read on every relevant archived fixture run. Under that
workload, moving it out of the body increased modeled context use rather than
reducing it. The quality data would have let it through; the economics killed it.
This is why a smaller static trigger path is not itself a savings claim.

Full detail, including what was refused and why: [`docs/CASE-STUDIES.md`](docs/CASE-STUDIES.md).

## Quick start

```bash
git clone https://github.com/yosishe/token-efficient-skill-optimizer.git
cd token-efficient-skill-optimizer
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r skill/requirements-lock.txt
```

Point the harness at any skill package — including this one:

```bash
.venv/bin/python skill/scripts/measure_tokens.py skill/
```

To install it as a Claude skill:

```bash
cp -R skill ~/.claude/skills/token-efficient-skill-optimizer
```

Then ask for what you want in plain language — "audit `path/to/skill` for token
efficiency", "optimize it, balanced profile", "is this vendor's savings claim real?".

Verify the package for yourself:

```bash
.venv/bin/python skill/scripts/run_tests.py
.venv/bin/python skill/scripts/validate_package.py skill/
```

Without `tiktoken` the harness degrades to a heuristic proxy with wider bounds, still
honestly labeled. Network access is never automatic. An Anthropic preflight estimate
requires a complete structured request and explicit consent:

```bash
.venv/bin/python skill/scripts/measure_tokens.py skill/ \
  --method anthropic-api --allow-network --request-json request.json
```

The result estimates input tokens for the named model; it is not completed-run usage,
cache accounting, output usage, or an exact billed total.

## Why you can check the reasoning

The point of this repository is not to be believed. Every rule traces to sources you can
open, and every design decision states what it rejected and why.

| | |
|---|---|
| [`docs/CASE-STUDIES.md`](docs/CASE-STUDIES.md) | Archived v1.1 runs against three public skills — what changed, what was refused, and why their numbers no longer qualify under v2 |
| [`docs/RESULTS.md`](docs/RESULTS.md) | The archived v1.1 record, its non-qualifying evidence status under v2, and the limitations that bound it |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | 11 design decisions, each with its reasoning and what was rejected |
| [`docs/RESEARCH-BASIS.md`](docs/RESEARCH-BASIS.md) | Eight papers in depth — what each found, in what setting, the consideration taken from it, and what it explicitly does **not** license |
| [`docs/EVIDENCE.md`](docs/EVIDENCE.md) | The evidence register and which rule each source supports |
| [`docs/RULES.md`](docs/RULES.md) | The registry, with per-rule risk scores |
| [`research/`](research/) | The raw corpus — full records, the synthesis, and what the research could **not** establish |
| [`examples/before-after/`](examples/before-after/) | A worked optimization, including the change that was correctly skipped |

Six sources and a dated price table from a second implementation could not be
corroborated against a primary page. None was carried in, and no rule cites them.

## Known limitations

- The archived paired evaluation used a small case set and one grader. It can
  expose blunt regressions; it cannot resolve small quality differences or
  substantiate a v2 measured claim.
- Version 1.2 deliberately implements no live-runtime attestation verifier.
  Observed-usage-shaped adapter output remains `runtime_unverified` and cannot
  become `[measured]`; a future live tier needs a separately reviewed,
  recomputable attestation and sanitized smoke test.
- Static token counts are structure, never proof that a target still works.
- The honesty gate over-flags — its keyword list cannot separate domain nouns from
  ordinary English. Over-flagging is the right direction for this trade, but it is noise.
- Pricing snapshots go stale. Figures carry their snapshot date, and the cost model
  refuses to price a date outside a rate's effective window rather than silently using a
  superseded one.
- One design change shipped in the current version — enumerating a target's obligations
  as numbered contract items — appeared too rarely in the archived evaluation to count
  as a demonstrated capability. It ships as procedure.

## License

MIT — see [LICENSE](LICENSE).
