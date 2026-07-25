# Benchmark — <target> before vs after (<date>)

Header: token rung <same for both sides>; pricing snapshot <date>; profile <name>.

## Evidence
- exact local/supporting data: <path>
- target claim: `evidence: report.json#/claims/<claim-id>`

## Exact local structure
<bytes/lines and deterministic structure deltas; label as not model usage>

## Measured runtime usage
<completed observed-usage claims only; every line carries its own JSON pointer>

## Estimated
<provider/local estimates or derived cost; every quantitative line carries its own JSON pointer>

## Projected
<non-quantitative hypotheses, or claim-specific JSON evidence for target quantities>

## Per-rule attribution (ablation)
| Rule | Applications | Token delta [label] | Status |
|---|---:|---:|---|

## What didn't work
<rules with negligible benefit; rollbacks with reason; skipped findings with reason>

## Gates
<release-gate pass/fail table; any fail = not shipped>
