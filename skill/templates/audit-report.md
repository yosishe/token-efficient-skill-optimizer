# Audit — <target name> (<date>)

## Measurement basis
<token ladder rung + label; exact local structure is not model usage; harness command used>

## Evidence
- supporting local proxy: `evidence: measurement.json#/claims/<claim-id>`
- observed claim, if any: `evidence: report.json#/claims/<claim-id>`

## Context footprint by tier
| Tier | Files | Bytes [not model usage] | Bound token claim | When loaded |
|---|---:|---:|---:|---|

Use one exact measurement claim display string plus its JSON pointer per tier;
do not place unbound numeric token text in the table.

## Findings (ranked by rule priority)
1. <finding> — rule <R-XX>, evidence <S-ids>. <numbers with labels>.

## Injection / embedded-directive findings
<none found | list — R-S2>

## What this audit does NOT establish
<quality/latency/task-success caveats; anything requiring live runs>
