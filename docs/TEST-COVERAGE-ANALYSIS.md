# Test coverage analysis — 2026-08-25

Measured against `v1.2.1` (`ad74a13`). Every figure below is reproducible with the recipe at
the end; every defect claimed is one I triggered, not one I inferred from reading.

## Baseline

`python scripts/run_tests.py` → **104/104 pass**, exit 0.

Line coverage of `skill/scripts/` while that suite runs, with subprocess tracking on (the
suite drives almost everything through `subprocess.run`, so without `COVERAGE_PROCESS_START`
the numbers are meaningless):

| script | stmts | missed | cover |
|---|---:|---:|---:|
| `live_eval_adapter.py` | 39 | 39 | **0%** |
| `render_rules.py` | 87 | 35 | **60%** |
| `validate_package.py` | 461 | 122 | **74%** |
| `eval_runner.py` | 170 | 38 | 78% |
| `eval_report.py` | 264 | 31 | 88% |
| `measure_tokens.py` | 313 | 32 | 90% |
| `cost_model.py` | 87 | 6 | 93% |
| `validate_report.py` | 66 | 3 | 95% |
| `run_tests.py` | 385 | 15 | 96% |
| **total** | **1872** | **321** | **83%** |

Separately: the four behavioral splits hold 54 rows and **0 of them execute** — by design,
they need a model and a grader. That is documented in `tests/README.md` and is not counted
as a gap here.

83% is a healthy number. The problem is not the size of the gap but its *shape*: the
uncovered third is almost entirely the branches that emit findings. The suite proves this
package's tools stay quiet when they should; it largely does not prove they speak up when
they should.

## The asymmetry, stated plainly

`run_tests.py` is heavily armored against **false positives** — FP-1 through FP-5, the depth
guard, the nested-root rules, the bilingual siblings. That armor is good and it was earned.
But of the nine areas below, seven are **false negatives**: a check that silently stops
firing keeps the suite at 104/104.

---

## 1. Nine of the ten release gates have no test that can fail them

`validate_package.py` defines gates C01–C10. The suite asserts:

- `validate_package passes on the candidate` — all ten green on a good package
- three mutation tests for G-11/G-12

I instrumented those three mutations: **all three trip `C02` and only `C02`.**

> `placeholder mutation trips: ['FAIL  C02 rule-schema  38 rules x 19 fields']`

So **C01, C03, C04, C05, C06, C07, C08, C09, C10 are asserted only in the positive
direction.** The coverage data agrees: of the 122 missed lines in this file, nearly every one
is a `violations.append(...)` — the schema errors, the split floors, the gate-boolean checks,
the holdout-overlap check, the profile checks, the secret findings, the pricing checks.

This is the failure mode the package names in its own comments — *"a gate nobody can fail is
decoration"* — applied to nine of its ten gates.

I verified they are not decoration *today* by mutating a copied package:

| mutation | result |
|---|---|
| plant a synthetic `AKIA` + 16 uppercase-alnum id in `references/leak.md` | `FAIL C08 secret-scan` ✅ |
| plant a synthetic `sk-` + 24 mixed-class chars | `FAIL C08 secret-scan` ✅ |
| delete `VERSION` | `FAIL C01 required-paths` ✅ |
| rename the `snapshot:` block | `FAIL C10 pricing-snapshot` ✅ |
| bump `VERSION` to `9.9.9` | **PASS — see §2** ❌ |

Each of those is a four-line addition to the `package_check()` helper that already exists in
`run_tests.py`. This is the highest value-per-line work available in the repo.

## 2. C09 version-consistency is structurally vacuous — and it is already hiding live drift

`check_version()` cross-checks `VERSION` against a version string in
`config/default-settings.yaml`. That file **declares no version**, so the `declared is None`
branch runs, `rep.note(...)` fires, and the gate reports:

> `C09 version-consistency  VERSION=1.2.1, no version declared in config (reported, not failed)`

C09 cannot fail on its actual subject. Its only reachable failure modes are a missing, empty,
or unreadable `VERSION` file — which C01 already catches. That is why `VERSION=9.9.9` above
passed.

What it does not look at is every other version-bearing file that *does* exist. Consequence,
live on `main` right now:

- `skill/VERSION` → `1.2.1`
- `CHANGELOG.md` (root) → latest heading `## 1.2.1`
- **`skill/CHANGELOG.md` → latest heading `## 1.1.4`**

The changelog **inside the shipped package** is two releases stale. It is missing 1.2.0 and
1.2.1 entirely. `validate_package.py` reports PASS.

**Proposal:** widen C09 to cross-check `skill/VERSION` against the root `VERSION` and against
the newest `## <semver>` heading in both changelogs; keep the `default-settings.yaml` check as
the optional one it is. Then fix the changelog. Add the `VERSION=9.9.9` mutation as the test.

## 3. The secret scanner is 0% covered

`shannon()` is **never called** in any test. `looks_like_real_credential()` never returns —
neither `True` nor `False` — in any test. The four `SECRET_RULES` regexes are never matched.
`check_secrets` walks the tree, finds nothing, and reports `87 text files scanned`.

The code carries this comment:

> *"Mutation testing found exactly that hole — a genuine AKIA id sailed through until the
> tests were scoped per rule."*

The fix landed. **The test did not.** The per-rule scoping that fix introduced — `envvar` and
`classes` deliberately off for the AWS rule — is exactly the kind of subtle configuration that
a future edit reverts without noticing.

**Proposal:** one table-driven test over ~10 rows. Each of the four rules gets a positive
(planted credential → C08 fails) and its guard half (the corresponding placeholder /
env-var-name / low-entropy string → C08 stays green). `PLACEHOLDER`, `ENVVAR_NAME`, and the
3.0-bit entropy floor each need one row of their own. Both directions matter equally here: a
scanner that fires on `your_api_key_here` gets switched off by the first person it annoys.

## 4. `measure_tokens.py`: five finding classes are never asserted to fire

90% covered, but the missed lines are the flags themselves — 446, 449, 472, 476, 479-480.
Nothing in the suite asserts these ever appear:

| flag | line |
|---|---|
| `CRITICAL: no frontmatter description - skill cannot trigger` | 446 |
| `description N chars > 1024 spec limit` | 449 |
| `body N lines > 500 - extract to references/` | 472 |
| `N code block(s) >15 lines in body - move to scripts/` | 476 |
| `a references/ pointer has no read-condition` | 479-480 |

The read-condition flag is *only* ever asserted **absent** — twice (`ZH: read-condition
detected` and `REGRESSION: generic path-convention prose is not a pointer` both assert
`not flagged(...)`). Delete the check outright and both tests go green.

Reachable and trivially testable — a throwaway package with a 546-line body, one 20-line code
block, and a bare `references/thing.md` mention produces:

```
- body 546 lines > 500 - extract to references/
- 1 code block(s) >15 lines in body - move to scripts/
- a references/ pointer has no read-condition ('read only when...')
```

**Proposal:** one `bad-skill` fixture asserting all five fire, paired with the existing
fixtures that assert they do not. That closes the false-negative side of the harness's own
headline output.

## 5. `render_rules.py`'s generation path is 0% covered — and its output has drifted

Only `--check-only` ever runs. Lines 116–175, the whole `rules.md` + evidence-matrix writer,
never execute. Two consequences, both live:

**a) `research/evidence-matrix.md` no longer matches `rules/rules.yaml`.** Regenerating and
diffing:

```
< | R-01 remove-exact-duplication | 1 | S-D09 · … <br>S-D10 · …
> | R-01 remove-exact-duplication | 1 | S-R05 · Same Task, More Tokens · peer-reviewed-conference
< | R-02 progressive-disclosure | 1 | …
> | R-02 progressive-disclosure | 2 | …
```

R-01's citations, R-02's tier, R-10, R-18 and the safety rules have all moved in the registry.
A checked-in generated file that documents the evidence base is stale, and no gate looks at
it. (`skill/references/rules.md` — the one the model actually reads — *is* in sync. Today.)

**b) The default `--out-matrix` escapes the repo.** `PROJ = SKILL.parent.parent` assumes
`skill/` sits one level deeper than it does here, so a bare `render_rules.py` writes to
`/home/user/output/research/evidence-matrix.md`. It prints `wrote …`, exits 0, and updates
nothing in the repository. That is precisely the kind of bug 0% coverage on a code path
protects.

**Proposal:** a drift test — render both artifacts to a temp dir, byte-compare against the
checked-in copies, fail on difference. It covers 35 lines, catches this class permanently, and
would have caught the path bug on the first run.

## 6. The eval harness's failure paths are untested

`echo_adapter.py` never raises, so nothing exercises:

- `eval_runner.py` 367–390 — adapter exception → `case_error` record, `errors` counter,
  `--fail-fast` early exit
- `eval_report.py` 161–162, 491 — reading and rendering `case_error` rows
- `eval_report.py` 210–215, 220–230, 495–498 — `incomplete_pairs` and `incomparable`

These are the paths that decide whether a paired A/B result is **honest when half the run
failed**. A report that quietly summarizes only the cells that succeeded, in a package whose
central claim is measurement honesty, is the worst available bug. Nothing currently proves it
does not do that.

**Proposal:** a second fixture adapter that raises on a named case id. Assert the run
completes, the log carries `case_error`, the report *names* the failure rather than dropping
it, and the pair count reflects the loss. Then the same adapter with `--fail-fast` for the
early-exit path.

## 7. `live_eval_adapter.py` — 39 statements, 0% covered

Never imported, never invoked. Two things a first test would catch immediately:

- it rewrites case ids as **positional integers** (`"id": i + 1`), discarding `case_id` —
  which `eval_report.py` pairs on, and which `run_tests.py` spends three assertions keeping
  globally unique
- its instructions point at `scripts/aggregate_benchmark.py`, which **does not exist** in the
  package

**Proposal:** low priority as coverage, but a ~10-line smoke test (run it over
`tests/cases.jsonl` into a temp dir, assert the `evals.json` shape and that every referenced
script exists) is cheap and would have caught the dead reference.

## 8. The token ladder only ever runs on its bottom rung

`measure_tokens.py` 172–180 (tiktoken) and 208–221 (API) are 0%. `tiktoken` is not installed,
and the requirements file marks it optional. So every token figure this project has ever
tested is a heuristic figure, and the two more accurate rungs — including the `api` rung that
makes a network call — have no coverage at all.

**Proposal:** install `tiktoken` in the dev path and add one test that the tiktoken rung
produces a count and labels itself as such; stub the API rung's transport rather than calling
out. Not urgent, but it is the product's central number.

## 9. Two smaller items

- **The schema assertion covers one split of four.** `t("required fields", ...)` iterates
  `cases` only. `safety`, `injection`, and `holdout` rows are never checked for `prompt` /
  `expected_behavior` / `expectations`. They all have them today — I checked — so this is a
  one-line change to keep it that way.
- **There is no CI.** No `.github/workflows` anywhere in the repo, while `tests/README.md`
  describes `validate_package.py .` as *"the ten release gates, as a CI check."* Both entry
  points are green and fast (~40s combined); a single workflow running `run_tests.py` and
  `validate_package.py` on push would make every gate above actually gate something.

---

## Priority

| # | area | why first |
|---|---|---|
| 1 | Negative tests for C01, C03–C10 (§1) | nine gates currently unfalsifiable; the helper already exists |
| 2 | C09 widening + the stale `skill/CHANGELOG.md` (§2) | a live defect shipping green right now |
| 3 | Secret-scanner tests (§3) | 0% on a security check, and its subtlest logic is uncommented-by-test |
| 4 | `measure_tokens` positive flag tests (§4) | the harness's own headline findings |
| 5 | Generated-artifact drift test (§5) | a live defect, plus 35 lines and a path bug |
| 6 | Eval-harness failure paths (§6) | honesty-of-measurement is the project's core claim |
| 7 | CI workflow (§9) | makes 1–6 permanent |
| 8 | §7, §8, §9a | cheap, low risk |

Items 1–5 are each an afternoon or less and together would move `validate_package.py` from
74% to roughly 90%, `render_rules.py` from 60% to ~95%, and — more to the point — convert
nine decorative gates into real ones.

## Reproducing the coverage numbers

The suite shells out to every script, so subprocess tracking is required:

```bash
pip install coverage
mkdir -p /tmp/covhook
echo 'import coverage; coverage.process_startup()' > /tmp/covhook/sitecustomize.py
cat > /tmp/coveragerc <<'EOF'
[run]
parallel = True
data_file = /tmp/.coverage
source = <repo>/skill/scripts
EOF

cd skill
PYTHONPATH=/tmp/covhook COVERAGE_PROCESS_START=/tmp/coveragerc \
  python -m coverage run --rcfile=/tmp/coveragerc scripts/run_tests.py
python -m coverage combine --rcfile=/tmp/coveragerc
python -m coverage report --rcfile=/tmp/coveragerc -m --sort=cover
```

Without `COVERAGE_PROCESS_START` the report shows `run_tests.py` alone and every other script
at 0% — which is why this had not been measured before.
