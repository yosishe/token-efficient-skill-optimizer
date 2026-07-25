# Archived v1.1 case studies — non-qualifying under v2

Run against real skills that hundreds of thousands of people have installed, at pinned
upstream commits.

> **Evidence status:** this is a historical v1.1 archive. Its numeric token,
> score, read-rate, and modeled-cost values predate schema v2 and do not have
> claim-specific `report.json#/claims/<claim-id>` records. They therefore do not
> qualify as `[measured]`, `[estimated]`, `[projected]`, or current savings
> evidence. They are retained here only to explain the decisions that were made
> at the time. Re-run the cases under v2 before quoting a number.

**These are good skills built by capable teams.** Nothing here is a criticism of them. The
question being asked is narrow: how much of each package is paid on *every* invocation, and
how much of that is genuinely needed every time.

## The tier that matters

A skill package has tiers, and they are not billed alike:

| tier | when it loads |
|---|---|
| **metadata** (frontmatter) | every session |
| **body** (`SKILL.md`) | **every trigger** |
| conditional (`references/`, `rules/`) | when the runtime/model reads it; direct pointers guide discovery |
| script | source may stay outside context when executed; invocation/output still enter context |
| artifact (`LICENSE`, `README`, lockfiles) | outside the ordinary trigger path; consumes context whenever explicitly read |

`metadata + body` is the **trigger path**. It is the number that recurs. A 5 MB package with
a lean body can be cheaper per invocation than a 30 KB package that inlines everything.

## Historical results

| skill | author | installs at capture | legacy trigger-path proxy before | after | historical change | verdict |
|---|---|---|---|---|---|---|
| `improve-codebase-architecture` | Matt Pocock | 538,600 | 1,540–1,673 | 1,247–1,356 | **−19.0%** | kept |
| `react-best-practices` | Vercel | 578,100 | 2,026–2,202 | 1,888–2,052 | **−6.8%** | kept |
| `frontend-design` | Anthropic | 702,100 | 1,887–2,051 | 1,563–1,700 | −17.2% | **reverted — see below** |

Two of the three shipped. **The third was reverted by its own evaluation**, and that is the
most useful result in this document.

Token figures below are **legacy v1.1 proxy outputs** retained as historical
case-study artifacts. Their former fixed Claude adjustment is unsupported and
v1.3 bars these ranges from provider-token or measured-usage claims. Byte counts
are exact scans of the archived files, but they are structural facts, not proof
of runtime context use or preserved behavior.

| skill | body bytes | moved to conditional |
|---|---|---|
| `improve-codebase-architecture` | 5,824 → 4,733 (−1,091) | +780 B |
| `frontend-design` | 7,972 → 6,542 (−1,430) | +1,602 B |
| `react-best-practices` | 6,806 → 6,382 (−424) | +1,452 B |

**No prose was compressed, shortened, or reworded anywhere.** Every change is a verbatim move
or a delete-with-citation. The reductions are entirely structural, which is why they can be
audited line by line.

---

## What was actually done, per skill

### `improve-codebase-architecture` — −19.0%

The body specified the HTML report format — card fields, the Tailwind/Mermaid stack, the
top-recommendation section — while `HTML-REPORT.md` **already specified the same things**, and
the body already linked to it. That is a body paying, on every invocation, to restate its own
reference file.

The passive pointer ("See HTML-REPORT.md for…") became an imperative read-condition naming the
file and the moment to read it. One paragraph was deleted rather than moved, because every
clause already existed in the reference file — cited line by line rather than assumed.

**The strongest evidence this is real duplication and not accounting:** even if
`HTML-REPORT.md` is read on *every single run*, the legacy proxy was still lower.
The body was genuinely repeating the file; the archived numeric range does not
qualify under v2.

**A latent defect surfaced in the process.** The body called a card field **Benefits**; the
reference file called the same field **Wins**. A naive deferral would have left "Wins" with no
binding to the instruction. The two names are now explicitly reconciled. This is a real bug in
the upstream skill, found only because something tried to move the text.

**What was refused:** stage 3 of the process was left in the body. Its content is opportunistic
("as decisions crystallize", "right there") — a model that has not read it cannot recognize the
moment to act on it, and there is no discrete "before you do X" instant to hang a read-condition
on. That is precisely what separates genuinely conditional material from merely later material.

### `frontend-design` — −17.2%

One change: the closing `## More on writing in design` section — self-contained copywriting
guidance — moved verbatim to `references/writing-in-design.md`. The author already treated it as
a sub-topic, pointing at it from the body rather than inlining it in context.

**The honest accounting, which matters more than the headline.** The break-even was computed,
not assumed: the move pays as long as the writing guidance is needed in **fewer than 74%** of
runs. The estimate is 50–65% — below the line, but an *estimate*, and the author wrote "often,"
not "sometimes."

So the historical trigger-path reduction was not a total saving. A run that does write interface copy
pays the new trigger path *plus* the referenced file *plus* a read round-trip — slightly more
than baseline. The old mixed-workload estimate is retained in the table only as
non-qualifying history. Quoting it as a current overall saving would inflate it.

**What was refused:** the AI-defaults calibration paragraph (the single most
tempting target) stays. It is consumed during both brainstorming and critique — that is, every
run. Moving it buys a round-trip and no saving.

### `react-best-practices` — −6.8%

The `## Quick Reference` block — all 70 rule stems with one-line descriptions — is **74% of the
trigger path** in the exact local scan. It was considered and **deliberately left in the body**.

The reasoning: its honest read-condition would be "read when writing, reviewing, or refactoring
React code," which is verbatim the skill's own trigger condition. **When a block's read-condition
equals the skill's trigger condition, it belongs in the body.** The catalog also works
*passively* — a model that has read "Don't define components inside components" does not need to
open the file. Moving it would trade a known token cost for an unmeasured capability loss across
578,100 installs.

The counter-argument, stated at full strength: that reasoning is mechanistic, not experimental.
If an evaluation showed no quality delta from moving it, the decision would be
wrong and the block would consume context per invocation for nothing.

What did change: two blocks fully duplicated elsewhere (a priority table restated by the Quick
Reference headings, and an applicability list that maps 1:1 onto the frontmatter description)
moved to `rules/_index.md`, plus a read-condition added to the `AGENTS.md`
pointer. That reference was much larger than the trigger path and was previously
advertised with no size signal and no condition. Whether the guard pays for
itself remains workload-dependent.

**All 70 rule stems verified still reachable**, and the documented `rules/<stem>.md` access
convention — the smartest thing in the package — was preserved untouched.

---

## Two skills were checked and left alone

`web-design-guidelines` (1,231 B) and `grill-with-docs` (390 B), both top-10 installed, were
sized and found **already efficient**. No changes proposed.

This is reported because a tool that finds something wrong with everything is not a measuring
instrument. Roughly the same applies to the three above: of ~149 raw findings the harness
initially produced across them, only about **2 were genuinely actionable** — the rest were
false positives in the tool, since fixed. That work is documented in the repository history.

---

## The evaluation, and what it changed

A blinded paired A/B: 12 tasks, 2 trials per side, **24 paired observations**. One grader saw
only `Output 1` / `Output 2`, sides randomized per packet, no version information. Thresholds
were frozen before the run.

**No quality regression.**

| | original | optimized |
|---|---|---|
| mean quality (0–4) | 3.875 | 3.833 |
| head-to-head | 3 wins | **4 wins**, 17 ties |

The −0.04 difference is well inside the pre-declared −0.25 non-inferiority threshold, and the
optimized side won marginally more head-to-head comparisons. Per skill:

- **`improve-codebase-architecture` — 4.00 vs 4.00, and every one of its eight paired deltas
  was exactly zero.** All seven report card fields — Files, Problem, Solution, Wins,
  Before/After diagram, Recommendation strength, Top recommendation — appeared in both arms.
  The relocated specification survived intact.
- **`react-best-practices` — 3.75 vs 3.75, mean delta 0.00.** The per-case deltas were
  `[−1, 0, 0, +1, 0, 0, +1, −1]`: symmetric noise that cancels exactly.

**Reachability, checked from the runners' own file-access records:**

- The relocated report spec was read in **both arms** on the case that needed it.
- On a case that did *not* need it, the **original** opened the reference file unnecessarily and
  the **optimized** version correctly skipped it — the explicit read-condition prevented a read
  the original was making anyway.
- `react-best-practices` never opened the relocated index, because its condition was never met,
  and cited a comparable number of rule files in both arms. No capability was lost.

## Why `frontend-design` was reverted

The relocated writing guidance was reachable — read in **8 of 8** design runs. That is exactly
the problem.

The break-even had been computed in advance: the move pays only if that guidance is needed in
**fewer than 74%** of runs. The estimate going in was 50–65%. The observed
fixture-run rate was **100%**.

| read-rate | net per run |
|---|---|
| **100% (archived fixture rate)** | **legacy model predicts an increase** |
| 74% (historical break-even) | legacy model predicts a decrease |
| 50% (historical scenario) | legacy model predicts a larger decrease |

At the observed rate the optimization makes the skill **more expensive**, before even counting
the read round-trip. So `−17.2%` was an exact local scan of the trigger path and
a misleading description of anything that matters.

The frozen protocol said revert rather than explain, so it is reverted. Note what did *not*
happen: the quality data would have let it through — the design arm's only real regression was
a single case that scored `−2` in one trial and `+1` in the other on the identical task, which
is variance, and it had no causal link to the relocated copywriting material (every design
output in both arms wrote real interface copy). **It was killed by economics, not by quality.**

This is the case worth reading twice. `−17.2%` is precisely the kind of number
that gets published: correctly calculated for one narrow tier, honestly
derived, and wrong about the thing a reader would conclude from it.

## What this still does not establish

24 paired observations, 12 tasks, one grader, on tasks written by the same person who
commissioned the optimizations. It detects blunt regressions and lost reachability. It cannot
establish that quality is identical, and it does not generalize to workloads unlike these.

Two case-design flaws, disclosed: `C-12` referenced an ADR file absent from the fixture tree,
and the design cases skew toward tasks requiring interface copy. Both applied identically to
both arms, so the comparison holds, but the second is why the 100% read-rate should be read as
"on a copy-heavy workload" rather than as a universal figure.

## Source revisions and re-evaluation

Upstream packages are pinned by commit SHA:

| skill | repo | SHA |
|---|---|---|
| `frontend-design` | `anthropics/skills` | `2235be7c60b5` |
| `react-best-practices` | `vercel-labs/agent-skills` | `dc8367e6f91c` |
| `improve-codebase-architecture` | `mattpocock/skills` | `697d4ce9742d` |

Fetch a skill at its pinned revision and point the current harness at it:

```bash
python skill/scripts/measure_tokens.py path/to/skill
```

The current harness emits schema-v2 local proxy estimates. It will not reproduce
the retired cross-tokenizer adjustment, and its result must not be compared
numerically with the archived v1.1 output as though the methods were equivalent.

No upstream content is redistributed here. `anthropics/skills` and `vercel-labs/agent-skills`
carry **no license** — their measurements and the changes made are reported as fact, but their
text is not copied into this repository. `mattpocock/skills` is MIT.
