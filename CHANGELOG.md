# Changelog — token-efficient-skill-optimizer

## 1.0.0 — 2026-07-24

Initial release.

- 27-rule evidence-backed registry (Tiers 1/2/3 + safety meta-rules), every rule
  cited to a 42-source verified-primary research base (DEEP tier, collected
  2026-07-24).
- Measurement harness: measure_tokens.py (3-rung token ladder + tier model +
  duplicate detection, deterministic), cost_model.py (range-based, dated pricing
  snapshot 2026-07-24 for Anthropic + OpenAI), validate_report.py (mechanical
  measured/estimated/projected label enforcement).
- 8 operating modes; 3 profiles; 10 release gates.
- Test suite: 30 behavioral cases + 8 independently-authored holdout cases +
  deterministic runner (run_tests.py).
- Pilot benchmark: ARS deep-research skill (frozen copy), Apply/Balanced —
  results in the project repo's output/benchmarks/.

## 1.0.1 — 2026-07-24

Harness accuracy pass, driven by the first run against a real 29-skill portfolio.
66% of v1 flags were false positives; all seven causes fixed.

- Multilingual heuristics (EN/ZH/HE) for trigger phrasing, negative boundaries,
  and read-conditions. A Chinese skill was mis-flagged for both.
- New `artifact` tier: text that is not model context (demos/, dist/, package*.json,
  README*, LICENSE, CHANGELOG, PROVENANCE.md). Excluded from the context surface
  and from reachability flags.
- Executables (.py/.js/.mjs/.sh/.ts) are script tier in any directory.
- Bilingual sibling files (X-en.md vs X.md) reported separately from duplication.
- Duplicate detection scoped to context tiers only.
- Reachability now also satisfied by a bundled script naming the file, or by a
  sub-directory pointer; flag reworded as a heuristic requiring verification.
- validate_report.py: latency units only count next to a digit; data-pointer
  paths no longer swallow the opening backtick.

## 1.0.2 — 2026-07-24

Test hardening, found by running the optimizer on itself. The v1.0.1 harness
fixes had shipped with no coverage: the suite was schema-only and would have
stayed green if any of them regressed.

- Suite 18 -> 44 tests. Five behavioral fixtures (zh-skill, he-skill,
  artifact-skill, bilingual-skill, script-reach-skill) pin each harness
  behavior; added validator edge cases and a cost_model smoke test.
- The two regression assertions that caught the v1.0.1 near-miss (an
  over-correction that silently suppressed every reachability finding) are
  now permanent tests instead of ad-hoc shell checks.
- Verified by mutation testing, not by passing: 16/16 deliberate breakages
  are caught. Four rounds of mutation found four tests that proved nothing.
- Harness fix: NON_CONTEXT_DIRS now matches at any depth, so a nested
  `.../demos/` is an artifact rather than context.

## 1.1.0 — 2026-07-25

First public release. Merges the strongest ideas from an independently-built
second implementation of this same skill, commissioned from the same brief.
Six adoptions, seven documented rejections. Several changes ADD tokens; that is
the correct trade under the stated priority order and is published as a cost.

**Defect fix — the reason this release exists.** `render_rules.py` defaulted
`--sources` to a project-relative path, so in an installed copy the citation
cross-check died with `FileNotFoundError`. Gate G-09 "no fabricated sources"
was decorative in every installed copy — precisely where the skill runs. The
package now ships `rules/sources-index.yaml` and the gate resolves standalone.
Verified from an orphan copy with no parent project.

- `validate_package.py`: the ten release gates are now mechanically enforced
  (required paths, rule schema, citation integrity, test hygiene, hardcoded
  gate booleans, safety tier present in every profile, secret scan, version
  consistency, dated pricing). 10/10, mutation-verified.
- Paired A/B evaluation harness: `eval_runner.py` + `eval_report.py` — seeded
  randomized schedule, provenance hashing, optional metrics defaulting to
  `None` never `0`, bootstrap CI that returns null below 5 paired observations,
  and `higher_token_cases` as a first-class output.
- Savings taxonomy widened from three labels to five, adding
  `[cache-dependent]` and `[behavior-dependent]`. A saving that exists only on
  a cache hit is a billing effect, not a token reduction.
- Effective-dated pricing: rows carry `effective_start` / `effective_end`, and
  the cost model refuses an out-of-window row by name instead of silently
  costing with a superseded rate.
- Tests split four ways — 20 development, 8 safety, 12 injection (each with a
  named vector), 8 sealed holdout. Safety and injection rows are all
  `critical: true`, so "zero critical failures" is computable. Suite 44 -> 68,
  23 mutations, 23 caught.
- Apply now enumerates the target's behavioral contract as `C-01`, `C-02`, …
  before planning edits. **Shipped unproven** — observed in only 2 of 24
  evaluated outputs.
- Harness fix: a subdirectory containing its own `SKILL.md` is treated as a
  nested package root, so its references resolve against that file. Pointed at
  its own package the harness previously emitted five reachability flags, all
  false positives; now zero, with genuinely unreachable files still flagged.
- `requirements.txt` added; tiktoken marked optional with its absence explained.

**Not established.** The paired evaluation returned no quality verdict — one
arm reconstructed stand-in targets while the other declined to, a divergence
caused by guidance issued mid-run rather than by any change under test. Both
versions passed 16/16 critical cases. See `docs/RESULTS.md`.
