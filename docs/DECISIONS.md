# Design decisions and why

This file exists because "it works" is not a reason to trust a tool. Each decision
below states what was chosen, what was rejected, and what evidence or observation
drove it. Where a decision rests on judgment rather than evidence, it says so.

Evidence ids resolve in [EVIDENCE.md](EVIDENCE.md).

---

## 1. Safety is outside the scoring system, not high in it

**Decision.** Safety rules (Tier S) are pinned at priority 999, active in every
profile, and cannot be disabled by any config key. `validate_package.py` fails the
build if a profile omits one.

**Why.** The obvious design is to score safety rules highly and let the ranking
sort it out. But a rule that competes for priority is a rule that can lose — to a
higher-scoring compression rule, on a target where the numbers happen to line up.
The scoring formula exists to rank *candidates*, and a safety obligation is not a
candidate.

**Corroboration.** A second, independently-built implementation of this same skill
(a GPT/Codex version, commissioned from the same brief) arrived at the same
structure by a different encoding — its safety rule scores 7.0 yet carries a
mandatory-invariant override that lifts it out of the ranking. Two independent
implementations converging on "safety must sit outside the score" is the strongest
design signal in this project.

## 2. Five labels for savings, not three  <!-- no-claim -->

**Decision.** `[measured]` · `[estimated]` · `[projected]` · `[cache-dependent]` ·
`[behavior-dependent]`. Composition is preferred where it applies:
`[estimated, cache-dependent]`.

**Why.** The first three describe *how confident* a number is. They cannot express
*what a number is contingent on*. A 90% reduction that only materializes on a  <!-- no-claim -->
prompt-cache hit is not a token reduction at all — it is a billing effect that
disappears on a cold prefix, and summing it with a real token saving produces a
figure that is simply false. Likewise a saving that only exists if the model takes
the assumed branch.

Prompt caching charges a write premium and discounts reads (S-C01, S-C02, S-C05);
the saving is therefore a function of hit rate, which is a property of your traffic,
not of the optimization. Labeling it `estimated` would have said "we are unsure of
the size" when the honest statement is "this is zero on a miss."

**Cost of the decision.** One added line in the skill body and a wider validator
regex. Adopted from the GPT/Codex implementation — a case where the reference was
straightforwardly better.

## 3. Token count, billed cost, and latency are three different things  <!-- no-claim -->

**Decision.** They are never conflated, never summed, and never presented as
interchangeable. A change that cuts tokens can raise cost (cache-write premium) or
raise latency (more round-trips), and the reverse is equally possible.

**Why.** This is the most common error in prompt-optimization writing, and it is
what makes most published "we cut costs 40%" claims unverifiable. Cost depends on  <!-- no-claim -->
per-model rates that change on announced dates — which is why the pricing model
carries `effective_start` / `effective_end` per row and **refuses** to cost a date
outside a row's window rather than silently using a superseded price.

## 4. The honesty gate is mechanical, and it blocks this project's own reports

**Decision.** `validate_report.py` fails any report containing a quantitative claim
without a label, or a `[measured]` claim without a pointer to the data file that
produced it.

**Why.** A convention that lives in documentation gets followed until it is
inconvenient. The gate has blocked the reports in *this* repository repeatedly —
including during the merge evaluation, where it caught derived figures that had
drifted toward a `[measured]` label they had not earned.

**Known cost, published rather than hidden.** The gate over-flags. Its keyword list
cannot distinguish domain nouns from ordinary English — the package's own name
contains "token", and "calls" matches both *model calls* and the ordinary verb.
Roughly ten lines across the project's reports needed an explicit `<!-- no-claim -->`
exemption for this reason. Over-flagging is the correct direction for this trade,
but narrowing the keywords risks letting a real claim through, and that change needs
an evaluation rather than a guess. It is recorded as a limitation, not patched under
time pressure.

**A fourth false-positive class, found by evaluation.** Quoting an injection payload
verbatim — the point of reporting one — trips the gate, because the payload itself
contains a digit and a cost keyword. The fix is to fence the quote (fences are
already exempt), never to paraphrase it: paraphrasing destroys the evidence the
finding exists for.

## 5. A test that has never failed proves nothing

**Decision.** Every behavior claimed by this skill has a test, and every test is
mutation-verified: the behavior is deliberately broken and the test must fail.

**Why.** This project's suite was 18 tests and green, and a review found that all
seven fixes in the preceding release had **zero** real coverage — the tests were
validating data shapes, not behavior. Four rounds of mutation testing then found
four more tests that proved nothing, including one whose fixture accidentally
supplied the very thing it was meant to detect the absence of, and a claimed
three-language capability with no test in the third language at all.

**The near-miss this discipline caught.** An intermediate version of the
reachability check accepted any directory mention as proof a file was discoverable.
Because `references/` appears in nearly every skill body, this silently suppressed
*every* reachability finding — including one already known to be true. The flag
count dropped from 105 to 29 and the result looked like an improvement. It was
caught only because a known-true finding had been pinned as a regression assertion
first. **An optimizer that makes its own numbers look better is the exact failure
mode this tool exists to detect**, and it nearly shipped that bug itself.

## 6. Not everything in a package is context

**Decision.** Files are classified into tiers — metadata, body, conditional, script,
**artifact**, asset — and only some are billed on a trigger. Demo directories,
`package.json`, READMEs, and lockfiles are artifacts: text that ships but never
enters the model's context.

**Why.** Auditing real third-party skills showed the naive "count all the bytes"
approach inflating findings by roughly two-thirds. Of 105 flags raised on a real
skill portfolio, 66% were false positives traceable to this and to English-only
heuristics. After the tier model and multilingual detection landed, 36 remained.
**A tool that cries wolf on two out of three findings will be uninstalled**, and
correctly so.

## 7. Progressive disclosure only pays if the files stay off the path

**Decision.** Moving text out of the body into `references/` counts as a saving only
when the file is genuinely conditional — reachable, but not read on a normal run.

**Why.** Measured ablation: loading a full package naively is **74%–158% worse**
than the baseline it was meant to improve. Splitting a body into files that get read
anyway does not save anything; it adds indirection and a second read. The rule that
tells you to split has a companion rule that tells you when not to.

This is also why unreachable files are reported as a *defect*: a reference no
instruction ever points at is not a saving, it is a capability the model cannot use.

## 8. Some rules exist to stop an optimization

**Decision.** The registry contains rules whose output is "leave this alone":
keep a repetition that looks redundant but is load-bearing, keep a verbose
instruction carrying a safety obligation, keep a longer prompt when the shorter one
costs more in retries.

**Why.** Compression research reports meaningful ratios with small quality loss
(S-A01, S-A02, S-A03) — but "small" is measured on benchmark tasks, not on a payment
confirmation step. The eval cases that matter most in this repository are the ones
where **the correct answer is not to compress**, and they are graded pass/fail, never
averaged into a score. A tool that can only say "shorter" is a compressor, not an
optimizer.

## 9. Rejected: measuring against a fatter "before"

**Decision.** The baseline for a savings claim is the deployed artifact, never the
brief or spec that produced it.

**Why.** The GPT/Codex reference headlines a −47% improvement measured from its own
915-line commissioning brief to the resulting skill. That is authoring, not
optimizing. The methodology is rejected outright: adopting it would let this tool
manufacture any savings figure it liked by choosing a more verbose starting point.
No number from that comparison is carried into this repository.

## 10. Rejected: unverifiable sources, including from the reference implementation

**Decision.** Six sources and one dated provider price table from the reference
implementation could not be corroborated against a primary page. **None** was carried
into the registry or the pricing model, and no rule cites them.

**Why.** The alternative is a citation that looks like evidence and is not — which is
worse than no citation, because it survives review. Every one of the 42 sources in
[EVIDENCE.md](EVIDENCE.md) was checked against its primary page (arXiv abstract, DOI,
or official provider documentation) before being recorded.

## 11. What this project has not established

Stated here rather than in a footnote, because the omissions bound every claim above:

- **Live behavioral validation is narrow.** The evaluation covers 12 cases with a
  blinded grader. It can detect a blunt regression and show whether a new behavior
  appears at all. It cannot establish small quality differences and does not
  generalize beyond these case types.
- **Static token counts are not evidence of preserved quality.** They are reported
  as structure, never as proof that a target still works.
- **The pilot result was small and is reported as measured.** One whole-scenario
  measurement came out at **−0.7%** — effectively nothing. It is published at that
  value rather than replaced with a more flattering slice.
- **Savings are workload-dependent.** A skill that triggers rarely saves little no
  matter how well it is optimized, and this tool will tell you that rather than
  produce a number.
