# Case studies — three heavily-installed public skills

Run against real skills that hundreds of thousands of people have installed, at pinned
upstream commits. Every number below is reproducible from those exact revisions.

**These are good skills built by capable teams.** Nothing here is a criticism of them. The
question being asked is narrow: how much of each package is paid on *every* invocation, and
how much of that is genuinely needed every time.

## The tier that matters

A skill package has tiers, and they are not billed alike:

| tier | when it loads |
|---|---|
| **metadata** (frontmatter) | every session |
| **body** (`SKILL.md`) | **every trigger** |
| conditional (`references/`, `rules/`) | only when an instruction points at it |
| script | executed — never read into context |
| artifact (`LICENSE`, `README`, lockfiles) | never loaded at all |

`metadata + body` is the **trigger path**. It is the number that recurs. A 5 MB package with
a lean body can be cheaper per invocation than a 30 KB package that inlines everything.

## Results

| skill | author | installs | trigger path before | after | change |
|---|---|---|---|---|---|
| `improve-codebase-architecture` | Matt Pocock | 538,600 | 1,540–1,673 | 1,247–1,356 | **−19.0%** |
| `frontend-design` | Anthropic | 702,100 | 1,887–2,051 | 1,563–1,700 | **−17.2%** |
| `react-best-practices` | Vercel | 578,100 | 2,026–2,202 | 1,888–2,052 | **−6.8%** |

Token figures are `[estimated]` — a tokenizer proxy with a disclosed Claude adjustment
(×1.15–1.25). Byte counts are `[measured]`. Both arms measured with the same harness build.

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
`HTML-REPORT.md` is read on *every single run*, the total is still **74–80 tokens lower** `[estimated]`. The
body was genuinely repeating the file.

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

So **−17.2% `[estimated]` is the trigger path, not the total saving.** A run that does write interface copy
pays the new trigger path *plus* the referenced file *plus* a read round-trip — slightly more
than baseline. Expected value across a mixed workload is roughly **6–9%** `[estimated]`.
Quoting that figure as the overall saving would inflate it.

**What was refused:** the AI-defaults calibration paragraph (~180 tokens `[estimated]`, the single most
tempting target) stays. It is consumed during both brainstorming and critique — that is, every
run. Moving it buys a round-trip and no saving.

### `react-best-practices` — −6.8%

The `## Quick Reference` block — all 70 rule stems with one-line descriptions — is **74% of the
trigger path**. It was measured, considered, and **deliberately left in the body**.

The reasoning: its honest read-condition would be "read when writing, reviewing, or refactoring
React code," which is verbatim the skill's own trigger condition. **When a block's read-condition
equals the skill's trigger condition, it belongs in the body.** The catalog also works
*passively* — a model that has read "Don't define components inside components" does not need to
open the file. Moving it would trade a known token cost for an unmeasured capability loss across
578,100 installs.

The counter-argument, stated at full strength: that reasoning is mechanistic, not experimental.
If an evaluation showed no quality delta from moving it, the decision is wrong and it costs
~1,580 tokens `[estimated]` per invocation for nothing.

What did change: two blocks fully duplicated elsewhere (a priority table restated by the Quick
Reference headings, and an applicability list that maps 1:1 onto the frontmatter description)
moved to `rules/_index.md`, plus a read-condition added to the `AGENTS.md` pointer — that file
is ~30,000 tokens `[estimated]`, about 15x the entire trigger path, and was previously advertised with no size
signal and no condition. That guard pays for itself if it prevents **1 read in 594**.

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

## What is NOT established

**Quality preservation has not yet been verified.** A blinded paired A/B evaluation is running —
12 tasks across the three skills, 2 trials per side, one grader who sees only `Output 1` /
`Output 2` — with three cases chosen specifically to fail if the relocated material became
unreachable. **Until it completes, no claim is made that these optimizations preserve behavior.**

The evaluation protocol was frozen before any run, and its blocking threshold is stated in
advance: if a case shows the optimized version failing to reach relocated content, the change is
**reverted**, not explained.

Static token counts are structure. They are not evidence that a skill still works.

## Reproducing

Upstream packages are pinned by commit SHA:

| skill | repo | SHA |
|---|---|---|
| `frontend-design` | `anthropics/skills` | `2235be7c60b5` |
| `react-best-practices` | `vercel-labs/agent-skills` | `dc8367e6f91c` |
| `improve-codebase-architecture` | `mattpocock/skills` | `697d4ce9742d` |

Fetch a skill at its pinned revision and point the harness at it:

```bash
python skill/scripts/measure_tokens.py path/to/skill
```

No upstream content is redistributed here. `anthropics/skills` and `vercel-labs/agent-skills`
carry **no license** — their measurements and the changes made are reported as fact, but their
text is not copied into this repository. `mattpocock/skills` is MIT.
