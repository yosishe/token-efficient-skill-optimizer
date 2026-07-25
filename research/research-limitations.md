# Research Limitations — token-efficient-skill-optimizer

The original sweep was collected 2026-07-24 with live web access; the targeted
v1.3 extension and round-two publication catalog were verified on 2026-07-25.
Any later use should re-run Refresh Evidence mode.

1. **Abstract-level verification for most papers.** Records were verified
   against primary pages (title/authors/abstract); only a minority were read in
   full text. Records whose abstracts state directional findings without numbers
   are flagged in-file ("do not cite percentages without full-text read"):
   S-D01, S-D02, S-D04.
2. **Sampled orchestrator re-verification.** The orchestrator independently
   re-fetched 4 of the original 42 records (one per cluster: S-A06, S-B06, S-C07, S-D05) —
   4/4 exact title+first-author matches. The remaining records rely on the
   collecting agent's fetch log plus structural integrity checks (unique ids,
   verified-primary status, URLs present on all 42). The nine v1.3 additions
   and five refreshed load-bearing records have primary-page verification
   metadata plus a SHA-256 of the exact decompressed response bytes observed on
   2026-07-25. The academic pages were byte-stable across two immediate
   retrievals. Anthropic's living HTML changed between immediate retrievals, so
   those hashes are explicitly point-in-time observations, not immutable page
   identities; CI validates the stored metadata without refetching.
   All 31 round-two primary publication pages were independently re-fetched and
   similarly bound to the decompressed response bytes observed on 2026-07-25.
   Their historical provenance strings point to an upstream dossier that was not
   shipped. The registry discloses that gap; rule-specific support is asserted
   only through `rules.yaml:source_claims`, and eight uncited records are marked
   catalog-only.
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
   here was replicated by us; quantitative source results are `[reported]` with
   a source id and locator. Any proposed transfer to a target is projected until
   evaluated there, and neither category is `[measured]` usage.
7. **Generalization.** Most academic results were measured on models older than
   the current generation; effect sizes may differ on 2026-era models even where
   directions hold. Records carry a per-source generalizes_across_models field.
