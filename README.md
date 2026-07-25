# token-efficient-skill-optimizer

A skill that audits and optimizes **other** AI skills, system prompts, and agent
instruction sets for token and cost efficiency — under hard constraints: no material
task-success loss, no safety weakening, no ambiguity introduced to save tokens, and
honest measurement throughout.

It is built for the case where the obvious approach fails: asking a model to "shorten
this prompt" reliably produces something shorter, and gives you no way to know what it
quietly broke.

## What makes this different from asking a model to shorten a prompt

- **It can tell you not to.** Several rules exist only to *stop* an optimization —
  keep a repetition that looks redundant but is load-bearing, keep a verbose instruction
  carrying a safety obligation, keep a longer prompt when the shorter one costs more in
  retries. "Already efficient, no meaningful savings" is a successful outcome.
- **Every rule cites its evidence, and the citation is machine-checked.** 27 rules over
  42 sources verified against their primary pages. A rule citing an id that does not
  resolve fails the build.
- **Numbers carry enforced labels.** `[measured]`, `[estimated]`, `[projected]`,
  `[cache-dependent]`, `[behavior-dependent]`. A `[measured]` claim without a pointer to
  its data file is rejected mechanically — including in this repository's own reports.
- **Token count, billed cost, and latency are never conflated.** A change that cuts
  tokens can raise cost (cache-write premium) or raise latency (more round-trips).
- **Safety sits outside the scoring system.** Safety rules are pinned at maximum priority
  and cannot be disabled by any profile or config key; the package validator fails the
  build if a profile omits one.

## What it does not do

Author new skills from scratch. Guarantee a savings percentage in advance. Run live model
evaluations without your explicit budget approval. Optimize harmful targets.

## Results, honestly

**There is no validated claim that this tool improves your skills.** The evaluation that
would establish it was run, and came back **inconclusive** — the full reason, including
the protocol defect that caused it, is in [`docs/RESULTS.md`](docs/RESULTS.md).

What *is* supported:

| | |
|---|---|
| Critical cases — safety, refusal, prompt injection | **16/16 pass**, zero failures, across both versions tested |
| Test suite | **74/74**, with every test mutation-verified — deliberately broken to confirm it fails |
| Package release gates | **10/10** |
| False positives on a real 29-skill portfolio | **105 flags → 36** after fixing seven causes |

The most useful thing it did was **find a real defect in itself**: the check that stops a
rule from citing a nonexistent source crashed with `FileNotFoundError` in every
*installed* copy, because it resolved a path that exists only in a development tree. The
gate was decorative exactly where the tool runs. That is the class of problem this
approach is for.

**And a result that is not flattering:** a whole-scenario pilot optimization measured
**−0.7%** — effectively nothing. It is published at that value. Skills that trigger
rarely save little no matter how well they are optimized.

## Quick start

```bash
git clone https://github.com/yosishe/token-efficient-skill-optimizer.git
cd token-efficient-skill-optimizer
python3 -m venv .venv && .venv/bin/pip install -r skill/requirements.txt
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
efficiency", "optimize it, balanced profile", "is this vendor's 70% saving real?".  <!-- no-claim -->

Verify the package for yourself:

```bash
.venv/bin/python skill/scripts/run_tests.py
.venv/bin/python skill/scripts/validate_package.py skill/
```

Without `tiktoken` the harness degrades to a heuristic rung with wider bounds, still
honestly labeled. With `ANTHROPIC_API_KEY` set, counts upgrade to the measured rung.

## Why you can check the reasoning

The point of this repository is not to be believed. Every rule traces to sources you can
open, and every design decision states what it rejected and why.

| | |
|---|---|
| [`docs/RESULTS.md`](docs/RESULTS.md) | What was measured, what was estimated, what is unproven — with limitations beside the numbers, not in a footnote |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | 11 design decisions, each with its reasoning and what was rejected |
| [`docs/EVIDENCE.md`](docs/EVIDENCE.md) | All 42 sources, and which rule each one supports |
| [`docs/RULES.md`](docs/RULES.md) | The registry, with per-rule risk scores |
| [`research/`](research/) | The raw corpus — full records, the synthesis, and what the research could **not** establish |
| [`examples/before-after/`](examples/before-after/) | A worked optimization, including the change that was correctly skipped |

Six sources and a dated price table from a second implementation could not be
corroborated against a primary page. None was carried in, and no rule cites them.

## Known limitations

- The paired evaluation is 24 observations over 12 cases with one grader. It detects
  blunt regressions; it cannot resolve small quality differences.
- Static token counts are structure, never proof that a target still works.
- The honesty gate over-flags — its keyword list cannot separate domain nouns from
  ordinary English. Over-flagging is the right direction for this trade, but it is noise.
- Pricing snapshots go stale. Figures carry their snapshot date, and the cost model
  refuses to price a date outside a rate's effective window rather than silently using a
  superseded one.
- One design change shipped in the current version — enumerating a target's obligations
  as numbered contract items — appeared in only 2 of 24 outputs. It ships as procedure,
  not as a demonstrated capability.

## License

MIT — see [LICENSE](LICENSE).
