# Scope-and-State Guide (workshop version) + Journal Rerun Spec

## A. Workshop version: scope-and-state, operationalized

The rule: every number belongs to one of two claim classes, and the class
determines the language around it.

**Class P (portable — state plainly):** recall@k, leak rate, verdicts,
ops_until_gone, prediction adjudications, plan text, model fits, and ratios
within one fingerprint (storage amplification ×, relative build rate,
engine-vs-engine latency in the same run). These reproduce from the seeds.

**Class F (fingerprint-bound — always conditioned):** absolute ms, absolute
throughput, the exact-vs-ANN crossover point. Never state without a scope
clause.

Sentence patterns to use verbatim (already embedded in DRAFT.md):
- "…at p50 X ms *within this fingerprint* (client-observed,
  transport-inclusive; §3.6)."
- "…*conditioned on dim=64*; at production dimensions (768–3,072) the exact
  baseline inflates roughly with the dimension ratio and ANN's case
  strengthens."
- "Absolute figures are not production estimates."
- Forced configs: "under a deliberately non-default configuration
  (full_scan_threshold=10 KB); no shipped default exhibited this."

Placement checklist (do all four):
- [ ] §3.6 "Scope of claims" subsection (done in draft)
- [ ] §8 Limitations (done in draft)
- [ ] EVERY table/figure caption carrying ms: append "(fingerprint:
      macOS arm64/10-core; transport-inclusive; dim=64)"
- [ ] Abstract: one clause — "on a single workstation fingerprint at dim=64"

Vendor-fairness pass (one read-through, checklist):
- [ ] architecture-class language ("post-filter architectures", never
      "pgvector is broken")
- [ ] every forced/non-default config labeled at point of use
- [ ] confound-flagged rows visibly flagged in published ledgers + §6
- [ ] no "first/only" without the H8-verified survey sentence

## B. Journal extension: the rerun spec (write once, run later)

Purpose: convert Class-F claims to portable ones and test dim-robustness of
the direction claims.

1. **Dims:** rerun cost/scale/h4/g3q drivers at dim ∈ {768, 1536}, same
   seeds (1729/4104), same ef sweeps. Feasibility on the current machine:
   raw vectors at 1e6×768×4 ≈ 3.1 GB → pgvector ≈ 11 GB at 3.66× (fits;
   slow build expected — the 12.5-min cliff will deepen; that IS a result).
   At dim=1536 cap N at 1e5 unless disk allows.
2. **Server-side timing:** pgvector via EXPLAIN ANALYZE total time (and/or
   pg_stat_statements) recorded beside client time; Qdrant via the API's
   reported time field where exposed. Report both columns; the delta IS the
   transport term, measured instead of caveated.
3. **Interval geometry:** add a non-epoch-aligned supersession corpus
   (random interval boundaries) to test the partitioning ~2× placement
   bound and confirm the payload-index fix's geometry-independence.
4. **Windows:** the two named probes — restore-then-W6 (snapshot/restore
   durability) and delete-under-optimizer-merge.
5. **Expected outcome classes (register before running):** direction claims
   (starvation model, planner model, twofold tax, adapter closures) hold;
   crossover and absolute costs shift in ANN's favor with dim; if any
   direction claim flips with dim, that supersedes the workshop paper and
   is the journal headline.

Until B runs, the workshop paper makes zero claims that depend on it. That
is the whole design.
