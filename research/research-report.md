# Research Report — Token-Efficiency Evidence Base

Project: token-efficient-skill-optimizer · Tier: **DEEP** (82 source
records; original sweep 2026-07-24, extensions 2026-07-25) · Full records:
`sources.yaml` (this directory). Cite by `S-*` id only; every id resolves to a
record with url, access method, and verification status.

## 1. Methodology

Four parallel research agents swept ten topic clusters (prompt/instruction
compression; compression-induced safety/quality degradation; context pruning &
long-context degradation; RAG efficiency; prompt/KV caching; model routing &
cascades; provider pricing; output-length control & structured-output economics;
agent-loop efficiency; skill design/progressive disclosure; prompt injection via
content). Selection criteria: peer-reviewed venues and recognized-group preprints
first; official provider documentation as primary source for pricing/caching;
engineering reports admitted as practitioner-tier evidence and labeled as such.
Verification: each record's primary page (arXiv abs / official docs) was fetched
and title+authors confirmed before recording; the orchestrator then ran
structural integrity checks over the original 42 records (unique ids,
verification status, URLs) and independently re-fetched a 4-record sample
(1 per cluster) — 4/4 exact title+author matches. The nine-record v1.3
extension was reviewed against primary academic pages and official Anthropic
documentation. A further 31 round-two publication pages were independently
re-fetched on 2026-07-25 and bound to the exact decompressed response bytes.
Across the catalog, all 82 records include version/snapshot
scope, section locators, lifecycle metadata, and retrieval hashes; living
Anthropic HTML is explicitly classified as a dynamic point-in-time snapshot.
The historical round-two dossier path was not shipped, so detailed support is
claimed only where a rule records a locator in `rules.yaml:source_claims`.

## 2. Synthesis by theme

### 2.1 Prompt & context compression (cluster A)

Moderate, extractive compression is supported in several tested workloads;
extreme compression is not a safe default.
LLMLingua-family methods reach large ratios (up to 20x), while related studies
report useful operating points around 2–5x and sometimes higher.
`[reported] S-A01 abstract; S-A03 abstract; S-A07 abstract.` Those are
experimental results rather than a transferable safe ratio. Query-aware
compression improved NaturalQuestions accuracy by 21.4% at roughly 4x fewer
tokens. `[reported] S-A02/S-B07 abstract and Table 2; same work.` At
6x–480x soft compression, the study reports 62–73% capability retention.
`[reported] S-A05 §4 Results.` SOTA compressors silently lose entities and grounding
(S-A08) — compression must be validated for information preservation, not just
task accuracy.

**Safety under compression** rests on preprint-tier evidence but is directionally
consistent: compression can drop safety guardrails (adversarial pre-compression
perturbation raised attack success from 0.21 to 0.71.
`[reported] S-A09 §4 Results; preprint.` Separately,
constraint violations peak at *medium* compression with instruction-dropping
dominating semantic loss (S-A10, unreplicated single-author preprint, low
confidence). Consequence adopted in the rulebook: safety/constraint text is
exempt from compression budgets by default.

### 2.2 Long context, pruning & RAG (cluster B)

Context length is a first-class cost even when retrieval is perfect: accuracy
reported drops of 13.9–85% attributable to length alone.
`[reported] S-B04 abstract and §4 Results.` Degradation without lexical overlap
starts well before nominal limits: 11 of 13 models fell below 50% of their
short-context baseline by 32K. `[reported] S-B02 §4 Results.` The mid-context position penalty
can push performance *below closed-book* (S-B01). Multi-turn accumulation costs
roughly 39% versus single-turn on the same tasks.
`[reported] S-B05 abstract and §3 Results.` Practical levers: query-aware
compression/reordering (S-B07), compressing retrieved documents to roughly 6%
of their original token count with minimal loss, and returning *empty* context
when retrieval is uninformative. `[reported] S-B08 abstract and §4 Results.`
Cautions: query-blind pruning measurably hurts
faithfulness (S-B06); semantically-similar-but-irrelevant context is the real
hazard, not junk volume (S-B09); semantic chunking does not consistently beat
fixed-size chunking (S-B10).

### 2.3 Caching, routing, pricing (cluster C)

Prompt caching can reduce price and latency when the exact model, prefix, TTL,
minimum size, and observed hit behavior qualify. It does not reduce context
occupancy. Anthropic documents cache reads at 0.1x input, writes at 1.25x for
the five-minute TTL or 2x for the one-hour TTL.
`[reported] S-C01 “Cache storage and refreshes”; S-C02 pricing table.`
OpenAI documents automatic caching from a stated minimum prefix and a discounted
cached-input rate. `[reported] S-C03 “Prompt caching availability”; S-C04 pricing table.`
The mechanism constrains design: caching is a
prefix match, so stable content must precede volatile content, and skills/tools
must serialize deterministically — a prefix divergence can invalidate
downstream reuse (S-C01, S-C12). Systems work reports substantial TTFT and
throughput gains from KV/prefix reuse.
`[reported] S-C07 §5 Evaluation; S-C08 §5 Evaluation.` Routing and cascades
also report large but workload-dependent cost reductions.
`[reported] S-C05 §4 Experiments; S-C06 §5 Results; S-C10 §4 Results.` Those
results carry quality risk that
requires a calibration/quality gate. Semantic response caching (S-C09) can
avoid a new output generation on a valid hit but carries false-positive and
staleness risk.

### 2.4 Output control, agent loops, structure, injection (cluster D)

Output-side control can be high-value because provider pricing tables assign
different input and output rates. `[reported] S-C02 pricing table; S-C04 pricing table.`
Prompted
length limits preserve accuracy while cutting verbosity (S-D01); per-problem
token budgets compress chain-of-thought with slight loss (S-D02); draft-style
reasoning matched CoT accuracy using roughly 7.6% of its tokens.
`[reported] S-D03 abstract and §4 Results.` On agentic tasks, post-hoc selection
of lower-overthinking solutions reported better performance and lower compute.
`[reported] S-D05 abstract and §4 Results.` Structured output is not free: stricter format
constraints measurably degrade reasoning on some tasks (S-D04 — magnitude
contested; see limitations). Tool-call planning/batching beats reactive loops
with substantial speed, cost, and accuracy gains in the paper's workloads.
`[reported] S-D06 abstract and §5 Evaluation.` Anthropic reports that its
multi-agent research architecture consumed far more tokens than chat and that
token use explained much of evaluation variance.
`[reported] S-D07 “Multi-agent systems excel at breadth-first queries”.`
Such architectures pay off only on parallelizable tasks; simplicity-first
is the provider's own design guidance (S-D08). Progressive disclosure
(metadata → body → bundled files) and scripts-over-generation are the canonical
skill-side mechanisms (S-D09, S-D10). Prompt injection via retrieved/ingested
content is demonstrated on real systems (S-D11) with structural defenses
carrying utility tradeoffs (S-D12) — the evidence base for treating optimization
targets as untrusted data.

## 3. Areas of agreement

- Moderate extractive compression, progressive disclosure, output-length
  control, stable-prefix caching, and tool-result filtering are consistently
  supported across independent groups and the provider's own engineering docs.
- Context length itself degrades quality — trimming irrelevant context is a
  quality intervention, not only a cost one (S-B01–S-B05 vs S-A02/S-B07).
- Token spend and capability are tightly coupled in agents (S-D05, S-D07):
  efficiency work must measure end-to-end success, not prompt size.

## 4. Areas of disagreement / contested findings

- **High-ratio compression loss:** one paper reports minimal loss at high
  compression while another reports 27–38% capability loss at extreme ratios.
  `[reported] S-A01 abstract; S-A05 §4 Results.` No universal safe ratio is
  adopted: ratios are experimental variables gated by obligation/entity/state
  retention and paired task non-inferiority (S-A08, S-A11).
- **Structured-output penalty magnitude:** S-D04's degradation findings are
  contested by an unfetched industry rebuttal (recorded as a caveat, not a
  source); rule uses it only to demand A/B validation, not to ban schemas.
- **Irrelevant-context effects:** random padding sometimes helps while
  similar-but-irrelevant text hurts (S-B09) — setting-dependent; rules treat
  "similar but irrelevant" as the hazard class.
- **Safety-under-compression:** preprint-only (S-A09, S-A10); adopted as a
  conservative constraint (never compress safety text), explicitly labeled
  practitioner/experimental confidence. The sources do not establish that
  redundant safety wording is inherently protective.

## 5. Open questions

- No study directly measures Claude-skill (SKILL.md-format) optimization
  end-to-end; skill-tier evidence is provider practitioner guidance (S-D09,
  S-D10) plus transfer from prompt-level studies.
- Compression interactions with prompt caching (compressed-but-unstable prefix
  vs longer-but-cached prefix) are unstudied; the rulebook orders caching above
  compression when the two conflict.
- Long-horizon effects of history summarization on multi-session agents remain
  under-quantified beyond S-B05's multi-turn result.
