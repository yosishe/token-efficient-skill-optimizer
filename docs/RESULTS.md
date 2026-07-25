# Results

What was measured, what was estimated, and what is still unproven. Numbers here carry
labels because the tool enforces labels — including on its own reports.

---

## The honest headline

**There is no validated claim that this tool makes your skills better.** The strongest
supported statement is narrower and is stated in full below: it finds real problems in
real skill packages, it refuses to fabricate the numbers it reports, and the evaluation
that would establish a quality improvement was run and came back **inconclusive**.

If you are looking for a percentage to quote, this page will disappoint you. That is
deliberate.

---

## What was measured

### On real third-party skill packages

Run against a portfolio of 29 installed skills. The first version produced **105 flags**,
of which **66% were false positives** — traced to English-only heuristics, counting
demo/build artifacts as model context, and treating conventional directory names as
proof of reachability. After seven fixes, **36 flags** remained on the same portfolio.

The finding worth publishing is the failure, not the fix: a tool that cries wolf on two
of three findings gets uninstalled, and correctly so. The current false-positive rate on
third-party packages **has not been re-measured** since.

### On the tool's own package

Pointed at itself, the harness emitted five reachability flags — **every one a false
positive**. All were fixture files inside self-contained mini-skill packages carrying
their own `SKILL.md`, so their references resolve against that file, not the outer one.
A 100% false-positive rate on the first action a new user is likely to take.

Fixed by the general rule — a subdirectory containing its own `SKILL.md` is a nested
package root — rather than by special-casing the fixture path. Post-fix: **0 flags**
`[measured]`. An independent probe planting an unreferenced file in the outer package
confirmed it is still flagged, so the fix removed noise and not the check.

### Deterministic gates

| gate | result |
|---|---|
| Test suite | 74/74 |
| Mutation verification | 23 mutations, 23 caught, 0 missed |
| Package validator | 10/10 checks, 0 violations |
| Citation cross-check | 27 rules, all evidence ids resolve |
| Clean standalone install, no parent project | all of the above pass |

### A real defect this process caught

The citation gate — the check that stops a rule citing a source that does not exist —
**crashed with `FileNotFoundError` in every installed copy**. It resolved a
project-relative path that exists only in the development tree, so the gate was
decorative exactly where the tool actually runs. Found by contrast with an independent
implementation, fixed by shipping the source index inside the package, and verified by
running the gate from an orphaned copy with no parent directory.

---

## What was estimated

Token figures come from a tokenizer proxy with a disclosed Claude adjustment
(×1.15–1.25). Cross-rung comparisons are invalid and the protocol forbids them.

Comparing the two most recent versions of this skill package:

| tier | previous | current | delta |
|---|---|---|---|
| **trigger path** (billed on every invocation) | 2,095–2,278 | 2,189–2,380 | **+4.5%** |
| conditional (read only when pointed at) | 39,433–42,865 | 44,712–48,605 | +5,279 |
| script (executed, never read into context) | 15,379–16,713 | 42,186–45,853 | +26,807 |

**The current version is larger in every tier.** It bought a defect fix and mechanical
gate enforcement, and it cost 4.5% `[estimated]` on the only tier billed every time.
Published as a
cost, because a tool that hides its own regressions has no standing to audit yours.

---

## The evaluation that came back inconclusive

A paired A/B evaluation of the two versions: 12 cases, 2 trials per side, 24 blinded
packets, one grader who saw only `Output 1` / `Output 2` with the sides randomized per
packet and no version information.

**What passed cleanly:**

| | previous | current |
|---|---|---|
| Critical cases (safety, refusal, injection) | **16/16 pass** | **16/16 pass** |

No embedded directive was followed on either side, in any run. Both injection payloads
were quoted verbatim as findings rather than obeyed. No safety span was weakened. Every
refusal came with a constructive alternative.

**What the new instructions actually changed:**

| behavior | previous | current |
|---|---|---|
| Used a label marking a saving contingent on a cache hit or an assumed path `[measured]` | 0 of 24 | **13 of 24** |
| Enumerated the target's obligations as numbered contract items before editing | 0 of 24 | **2 of 24** |

The label vocabulary works. The contract-ID procedure **largely did not take** — 2 of 24
is close to noise. It ships as procedure, explicitly not as a demonstrated capability,
and this round is evidence against it.

**Why the quality comparison yields nothing.** Mean rubric scores were 3.83 and 3.67 on a
0–4 scale, and three cases regressed past the pre-declared 1.0 threshold. Reading the
underlying responses, the recurring difference was that one arm reconstructed a stand-in
target from the case description and completed the run against it, while the other
declined to reconstruct and stopped after fully specifying the change — *"which blocks
are sub-flow-only is a content judgment, not a structural one, and I will not guess it."*

Nothing in the version under test instructs a model to stop and ask for a file. The
divergence traces to guidance issued **mid-run**, unevenly, telling runners not to
fabricate synthetic targets in order to manufacture a `[measured]` number. That guidance
was right; issuing it partway through contaminated the arm assignment.

So there is no change to roll back and no quality claim to make. A tempting alternative
reading — that stopping is *better* because refusing to guess is more honest — is equally
unsupported by this data and is not asserted. Both readings fit. That is what
inconclusive means.

**A clean re-run** needs identical guidance issued to every runner before any case is
attempted, and fixtures supplied as real files so "reconstruct or refuse" never becomes a
live choice. It has not been run.

---

## The pilot, reported at its actual value

One whole-scenario optimization measured **−0.7%** — effectively nothing. It is published
at that number rather than replaced with a more flattering slice of the same run. Skills
that trigger rarely save little no matter how well they are optimized, and the tool will
tell you that instead of producing a number.

An ablation on naive full-package loading came out **74%–158% worse** than the baseline it
was meant to improve. Progressive disclosure only pays when the files genuinely stay off
the normal path.

---

## Limitations, in one place

- 24 paired observations, 12 cases, one grader, on cases authored alongside the thing
  under test. Detects blunt regressions; cannot resolve small quality differences.
- Static token counts are structure, never proof that a target still works.
- Savings are workload-dependent — a rarely-triggered skill saves little.
- The honesty gate over-flags: its keyword list cannot tell domain nouns from ordinary
  English, and roughly ten lines across this project's reports needed an explicit
  exemption comment. Over-flagging is the right direction for the trade, but it is noise.
- Pricing snapshots go stale. Cost figures carry their snapshot date and the model
  refuses to cost a date outside a rate's effective window.
- **Reachability is over-permissive by construction.** A file counts as discoverable if
  its name appears anywhere in any bundled script — so a filename mentioned in a comment,
  a test string, or a docstring marks it reachable even when no instruction points at it.
  This surfaced concretely during development: a fix's own code comment happened to name
  two fixture files, which silently made them "reachable" and caused a mutation test to
  pass when it should have failed. The comment was rewritten without real filenames and
  the mutation was then caught. The underlying looseness is unchanged and is disclosed
  here rather than quietly narrowed — tightening it risks false *negatives*, which are
  worse than the noise, and that trade needs an evaluation rather than a guess.
- The sealed holdout has not been spent.

---

## Reproducing any of this

```bash
python scripts/run_tests.py            # the suite
python scripts/validate_package.py .   # the ten release gates
python scripts/measure_tokens.py .     # point it at itself
```

Every number above traces to a file in this repository or is labeled as unreproducible
and why. Where a `[measured]` label appears, a data pointer follows it — that rule is
enforced mechanically by `scripts/validate_report.py`, which blocked drafts of this very
page until each claim was either labeled or dropped.

## Harness data

Counts in the evaluation tables are tallied from the blinded grading record
`docs/data/grading-record-2026-07-25.json`, published with this repository.
