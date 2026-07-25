# Research Report — Token-Efficiency Evidence Base

Project: token-efficient-skill-optimizer · Tier: **DEEP** (42 verified-primary
sources; target was 25–35) · Collected: 2026-07-24 · Full records:
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
structural integrity checks over all 42 records (unique ids, verification
status, URLs) and independently re-fetched a 4-record sample (1 per cluster) —
4/4 exact title+author matches. Nothing is cited from memory.

## 2. Synthesis by theme

### 2.1 Prompt & context compression (cluster A)

Moderate, extractive compression is well supported; extreme compression is not.
LLMLingua-family methods reach large ratios (up to 20x claimed, S-A01), but the
practical sweet spot across studies is ~2–5x with ~10x as the empirical
minimal-degradation ceiling (S-A03, S-A07). Query-aware compression can even
*improve* accuracy by densifying relevant content and countering position bias
(+21.4% on NaturalQuestions at ~4x fewer tokens — S-A02/S-B07, same work). The
ceiling is quantified: at 6x–480x soft compression only 62–73% of capability is
retained (S-A05). SOTA compressors silently lose entities and grounding
(S-A08) — compression must be validated for information preservation, not just
task accuracy.

**Safety under compression** rests on preprint-tier evidence but is directionally
consistent: compression can drop safety guardrails (adversarial pre-compression
perturbation raised attack success 0.71 vs 0.21 baseline — S-A09, preprint), and
constraint violations peak at *medium* compression with instruction-dropping
dominating semantic loss (S-A10, unreplicated single-author preprint, low
confidence). Consequence adopted in the rulebook: safety/constraint text is
exempt from compression budgets by default.

### 2.2 Long context, pruning & RAG (cluster B)

Context length is a first-class cost even when retrieval is perfect: accuracy
drops of 13.9–85% attributable to length alone (S-B04); degradation without
lexical overlap starts well before nominal limits (11/13 models below 50% of
their short-context baseline by 32K — S-B02); the mid-context position penalty
can push performance *below closed-book* (S-B01). Multi-turn accumulation costs
~39% vs single-turn on the same tasks (S-B05). Practical levers: query-aware
compression/reordering (S-B07), compressing retrieved docs to as low as ~6% of
tokens with minimal loss and returning *empty* context when retrieval is
uninformative (S-B08). Cautions: query-blind pruning measurably hurts
faithfulness (S-B06); semantically-similar-but-irrelevant context is the real
hazard, not junk volume (S-B09); semantic chunking does not consistently beat
fixed-size chunking (S-B10).

### 2.3 Caching, routing, pricing (cluster C)

Prompt caching is the highest-leverage, lowest-risk cost mechanism on current
providers: Anthropic bills cache reads at 0.1x input, writes at 1.25x (5-min
TTL) or 2x (1-h TTL); 5-min caching breaks even after one read (S-C01, S-C02).
OpenAI caches ≥1024-token prefixes automatically with cached input at ~10% of
input price (S-C03, S-C04). The mechanism constrains design: caching is a
prefix match, so stable content must precede volatile content, and skills/tools
must serialize deterministically — a byte-level change invalidates everything
after it (S-C01). Systems results (KV/prefix reuse: 8–60x TTFT gains S-C07; up
to 6.4x throughput S-C08) explain *why* providers price it this way. Routing and
cascades offer large but workload-dependent savings (up to 98% cost reduction
best-case cascade S-C05; >2x cheaper routing that transfers across model pairs
S-C06; >50% via self-verification escalation S-C10) at quality risk that
requires a calibration/quality gate. Semantic response caching (S-C09) is the
only tier that also saves *output* tokens but carries false-positive-hit risk.

### 2.4 Output control, agent loops, structure, injection (cluster D)

Output-side control is high-value because output tokens are 3–6x the price of
input tokens on snapshot pricing (see `provider-cost-profiles.yaml`): prompted
length limits preserve accuracy while cutting verbosity (S-D01); per-problem
token budgets compress chain-of-thought with slight loss (S-D02); draft-style
reasoning can match CoT accuracy at as little as ~7.6% of the tokens (S-D03);
and on agentic tasks *less* overthinking gave ~30% better performance at 43%
lower compute (S-D05). Structured output is not free: stricter format
constraints measurably degrade reasoning on some tasks (S-D04 — magnitude
contested; see limitations). Tool-call planning/batching beats reactive loops
(up to 3.7x faster, 6.7x cheaper, ~9% more accurate — S-D06). Multi-agent
architectures cost ~15x chat tokens and token spend explains ~80% of eval
variance — they pay off only on parallelizable tasks (S-D07); simplicity-first
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

- **High-ratio compression loss:** "minimal loss up to 20x" (S-A01) vs measured
  27–38% capability loss at extreme ratios (S-A05); we adopt the conservative
  reading (≤5x default, ~10x ceiling).
- **Structured-output penalty magnitude:** S-D04's degradation findings are
  contested by an unfetched industry rebuttal (recorded as a caveat, not a
  source); rule uses it only to demand A/B validation, not to ban schemas.
- **Irrelevant-context effects:** random padding sometimes helps while
  similar-but-irrelevant text hurts (S-B09) — setting-dependent; rules treat
  "similar but irrelevant" as the hazard class.
- **Safety-under-compression:** preprint-only (S-A09, S-A10); adopted as a
  defense-in-depth default (never compress safety text), explicitly labeled
  practitioner/experimental confidence.

## 5. Open questions

- No study directly measures Claude-skill (SKILL.md-format) optimization
  end-to-end; skill-tier evidence is provider practitioner guidance (S-D09,
  S-D10) plus transfer from prompt-level studies.
- Compression interactions with prompt caching (compressed-but-unstable prefix
  vs longer-but-cached prefix) are unstudied; the rulebook orders caching above
  compression when the two conflict.
- Long-horizon effects of history summarization on multi-session agents remain
  under-quantified beyond S-B05's multi-turn result.
