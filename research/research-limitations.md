# Research Limitations — token-efficient-skill-optimizer

Collected 2026-07-24 with live web access. This review can be considered current
as of that date; any later use should re-run Refresh Evidence mode.

1. **Abstract-level verification for most papers.** Records were verified
   against primary pages (title/authors/abstract); only a minority were read in
   full text. Records whose abstracts state directional findings without numbers
   are flagged in-file ("do not cite percentages without full-text read"):
   S-D01, S-D02, S-D04.
2. **Sampled orchestrator re-verification.** The orchestrator independently
   re-fetched 4 of 42 records (one per cluster: S-A06, S-B06, S-C07, S-D05) —
   4/4 exact title+first-author matches. The remaining records rely on the
   collecting agent's fetch log plus structural integrity checks (unique ids,
   verified-primary status, URLs present on all 42).
3. **Preprint-tier safety evidence.** The compression-safety cluster rests on
   two preprints (S-A09; S-A10 is single-author and unreplicated). Rules derived
   from them are conservative defaults, marked experimental/practitioner
   confidence — not proven results.
4. **Contested finding retained with caveat.** S-D04 (structured-output
   degradation) has a known industry rebuttal that was not fetched and is
   therefore not a source; the disagreement is recorded in the research report.
5. **Provider docs are self-reported.** Pricing/caching figures are the
   providers' own publications (verbatim, dated). They are authoritative for
   billing but not independent measurements; they change without notice.
6. **No live model runs.** Per the project's static-only decision, no finding
   here was replicated by us; quantitative results are the papers' claims, and
   all downstream quality effects in our benchmark are labeled projected.
7. **Generalization.** Most academic results were measured on models older than
   the current generation; effect sizes may differ on 2026-era models even where
   directions hold. Records carry a per-source generalizes_across_models field.
