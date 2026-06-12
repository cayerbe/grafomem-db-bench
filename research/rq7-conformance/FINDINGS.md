# RQ7 Findings — Engine 1: pgvector (control)

**Run:** 2026-06-12, fingerprint `macOS-15.4-arm64-arm-64bit / 10 cores / k=10 / seeds 1729/4104`, corpus n=4000, dim=64, 8 interleaved tenants, pgvector HNSW (M=16, ef_construction=64), ef_search ∈ {16, 40, 64, 128}, postures 7a (engine-correct) and 7b (engine-as-deployed). Raw rows: `commercial_ledger.csv` / `.json` in this folder. All numbers below are [OBSERVED] unless tagged otherwise.

pgvector is the *control* engine (already the GRAFOMEM Cloud backend); these results calibrate the instrument before less-examined targets run.

---

## F-PG-1 — Isolation: 7a holds, 7b leaks totally. [OBSERVED]

At every ef: 7a tenant-scoped recall **1.00**, leak **0.00** (PASS); 7b recall **0.14**, leak **0.85–0.86** (LEAKS). The 7b figures match the `LeakyTenant` foil exactly — with the tenant predicate dropped, the engine returns the global top-k, of which ~1/8 are in-tenant by chance (8 interleaved tenants).

**Interpretation:** pgvector's tenant isolation is a `WHERE` clause — real and correct when applied, silently and totally absent when the calling layer omits it. This is **not** claims-but-leaks (pgvector makes no self-enforcement claim; 7a passes). It is the *logical-tenancy deployment risk* (H3) in measured form: the guarantee is opt-in per query and defeatable by a one-line omission, with no error, no warning, and full-looking results (7b unfiltered recall is normal). Structurally impossible cross-tenant reads (RQ2) this is not.

## F-PG-2 — Deletion: honest. A commercial engine PASSES W6. [OBSERVED]

Every 7a run: deleted ids unrankable at the **first** post-delete read (`gone@1`), leak 0.00, post-delete recall 1.00 against the post-delete oracle. MVCC row visibility excises on the read path immediately; no "deleted but still rankable" window at this scale.

**Interpretation:** the claims-but-leaks failure mode does **not** reproduce on pgvector under this probe. Per the charter (§6), a pass is a calibration of the critique and a credibility deposit — recorded as such. The structural suspicion shifts to engines with mark-deleted ANN segments and deferred reclamation (Qdrant is next for exactly this reason). Note the W6 *cost* shape: deletion is honest-on-read, but storage reclaim is deferred to VACUUM (not measured this run; the adapter's `compact()` hook exists for it).

(The 7b `delete.honest` rows show recall 0.00 with leak 0.00 — this is the documented cross-scenario contamination flag: the in-tenant oracle never lists the cross-tenant ids 7b returns. Deletion itself is adjudicated by the leak column and `gone@`; the isolation failure is adjudicated by the W5 row.)

## F-PG-3 — Recall/latency frontier exists and is monotone; not yet a verdict. [OBSERVED, scope-limited]

Unfiltered recall@10 climbs 0.67 → 0.89 → 0.96 → 0.99 across ef 16 → 40 → 64 → 128. Clean frontier; the instrument traces it. Two caveats gate any comparative reading:

- **Scale.** At n=4000 the exact in-process anchor dominates (recall 1.00 @ 0.78 ms vs pgvector 0.99 @ ~0.95 ms). ANN indexes exist for large N; their reason to exist is invisible at this corpus size. The N-sweep (1e5–1e6, RQ6) is required before any "X is faster/slower" claim.
- **Transport confound.** pgvector latency includes psycopg2/TCP round-trip to a container; the anchor is in-process numpy. **Latency is not currently a fair cross-engine column.** Recall, leak, `gone@`, and storage are. Fix: server-side timing (`EXPLAIN ANALYZE`) or scale where index cost dominates transport.

## F-PG-4 — Filtered-ANN was (almost certainly) never exercised. [OBSERVED fingerprint; INFERRED cause]

7a tenant-scoped recall is a flat **1.00 at every ef**, including ef16 — while unfiltered recall at ef16 is 0.67. Recall that does not move with ef is the fingerprint of the HNSW index not being used for that query: at 1/8 selectivity over 4000 rows, the Postgres planner plausibly preferred filter-then-exact-sort over the ~500-row tenant subset.

**Consequence:** this run says **nothing** about H1/RQ5 (filtered-HNSW under-retrieval / graph starvation under selective filters). The regime that triggers it — large N, selective filter, index actually chosen, low ef — was never entered. The flat-recall observation is [OBSERVED]; the planner-bypass explanation is [HYPOTHESIS] until confirmed with `EXPLAIN ANALYZE` on the scoped query. Action: add a forced-index / high-selectivity probe (and the N-sweep) before any H1 claim in either direction.

## F-PG-5 — Storage amplification ≈ 3.7×. [OBSERVED]

`pg_total_relation_size` ≈ **3,792,896 bytes** vs 1,024,000 bytes of raw vectors (the anchor's exact figure): ~3.7× for heap row overhead + HNSW graph + btree tenant index, at n=4000/dim=64. This is a true measured figure (unlike estimate-class numbers from engines that don't expose on-disk size). The single 3,809,280 reading (ef64/7a) is one–two 8 KB pages of autovacuum jitter — within noise. Amplification factor will shift with N and dim; re-measure in the N-sweep.

## as_of (H4/RQ4) — direction confirmed, unstressed. [OBSERVED, weak probe]

Temporal filtering via metadata predicates: leak 0.00, recall tracking the unfiltered frontier (0.67→0.99). Consistent with "timestamps as filterable metadata, no native bi-temporality" (H4's expected answer) — but the probe's temporal selectivity is low (~10% closed intervals), so this is direction, not stress. A high-supersession corpus is needed before the as_of *cost* claim in RQ4 is made.

---

## Status updates fed back to the charter

- **H3:** logical-tenancy deployment risk now [OBSERVED] on a real engine (F-PG-1). "Structurally impossible vs filtered by convention" (RQ2): pgvector is firmly *by convention*.
- **H5/W6:** first commercial PASS recorded (F-PG-2). Claims-but-leaks remains unobserved on commercial engines — next probe targets the mark-deleted/deferred-reclaim architecture class.
- **H1/RQ5:** explicitly **not tested** by this run (F-PG-4). No update in either direction.
- **H4:** direction consistent with expectation; unstressed (above).
- **RQ9:** frontier + storage pairing works end-to-end on a real engine; latency column needs the transport fix before cross-engine use (F-PG-3).

## Open actions

1. Qdrant run (same harness, hnsw_ef sweep, 7a/7b) — primary claims-but-leaks candidate (mark-deleted + optimizer reclaim).
2. `EXPLAIN ANALYZE` confirmation of F-PG-4's planner-bypass hypothesis; forced-index/high-selectivity probe.
3. N-sweep (1e5–1e6) for frontier, storage amplification, and the RQ6 "architectural corner".
4. Server-side timing to de-confound the latency column.

---

# Run 2 addendum (pgvector rerun + Qdrant first contact)

**Run:** same fingerprint family (macOS arm64, 10 cores, k=10, seeds 1729/4104, n=4000), now with qdrant-client 1.18.0 against `qdrant/qdrant:latest`, pgvector rerun in the same sweep.

## F-PG-6 — H1 filtered-ANN under-retrieval: OBSERVED on a real engine. [OBSERVED; mechanism HYPOTHESIS pending Q1/Q2]

Run 2's `ef16/7a` tenant-scoped row: recall **0.21**, leak 0.00 (PARTIAL). The post-filter starvation model predicts exactly this: HNSW at ef16 yields ≤16 global candidates; the tenant predicate is applied *after* the index scan; ~1/8 survive → ~2 of the needed 10 → recall ≈ 0.2. Observed 0.21. This is H1's filtered-HNSW under-retrieval — the charter's "technically interesting thread" — caught in the wild for the first time in this project. It also explains the same instance's `delete.honest` recall 0.00/leak 0.00: the post-delete scoped read starved; deletion remained honest (`gone@1`).

Mechanism confirmation is one script away: `diagnose_pgvector_h1.py` Q1 (EXPLAIN: is it an Index Scan with "Rows Removed by Filter"?) and Q2 (forced-index recall vs ef against the `min(1, ef·selectivity/k)` prediction, with and without pgvector's `hnsw.iterative_scan` mitigation).

## F-PG-7 — Run-to-run planner instability: same query, same data, different verdicts. [OBSERVED across runs 1–2; cause HYPOTHESIS]

Run 1: scoped recall 1.00 flat at all ef (plan bypassed the index — F-PG-4). Run 2: 0.21 at ef16, 1.00 at ef40+. `ef_search` does not influence plan choice, so the *plan itself flipped between fresh instances* — most plausibly on ANALYZE/autovacuum timing against newly loaded tables. Lesson encoded into the harness: the adapter now runs `ANALYZE` after load (pins planner statistics) and exposes `force_index` (deterministic ANN path) — without these, W5-cost rows are not reproducible. Methodological note for the eventual report: **a conformance/cost verdict on a planner-mediated engine is a verdict on (engine + statistics state), not the engine alone.**

## F-QD-1 — Qdrant rows in run 2 measured PLAIN search, not HNSW. [OBSERVED fingerprint; cause near-certain, auto-confirmed next run]

Qdrant recall is 1.00, perfectly flat, at every ef including 16 — the fingerprint of `hnsw_ef` being a no-op. Documented cause: Qdrant builds the vector index only above `indexing_threshold` (default 20,000 KB); this corpus is ~1,000 KB, so segments stayed on exact full-scan. Consequences:
- The run-2 Qdrant W5/W6/as_of verdicts are *real but about the plain-search path*. They must not be cited as HNSW behaviour.
- **The W6 claims-but-leaks probe has not yet touched its target architecture** (mark-deleted points inside an HNSW graph) — no graph existed to mark-delete from. H5/W6 on Qdrant remains open.
- Fix shipped: collection now created with `indexing_threshold=10` (KB); `flush()` waits for optimizer status green and records `indexed_vectors_count` into every row's cfg. **`indexed=0` on a row = plain search; `indexed=N` = ANN.** Which code path ran is now observed per row, not inferred from recall shape.

## F-QD-2 — Qdrant 7a/7b and deletion on the plain-search path. [OBSERVED, scope-limited to plain search]

Same isolation shape as pgvector: 7a PASS (1.00/0.00), 7b LEAKS (0.14/0.86) — payload-filter tenancy is also by-convention, defeatable by omission. Deletion `gone@1`, leak 0.00 with `wait=true`. Both verdicts to be re-established on the indexed path before entering the report.

## Revised open actions

1. **Rerun `run_commercial.py`** with the patched adapters: Qdrant rows must show `indexed=4000`; pgvector rows are now ANALYZE-pinned. This supersedes run 2's Qdrant section and stabilises pgvector W5.
2. **`diagnose_pgvector_h1.py`** — resolves F-PG-6/F-PG-7 mechanisms (EXPLAIN + forced-index probe + iterative_scan mitigation).
3. Qdrant W6 on the *indexed* path is the claims-but-leaks test proper; watch `gone@` once `indexed=4000`.
4. N-sweep and server-side timing as before.

---

# Run 3 addendum (diagnostic + ANALYZE-pinned rerun)

## F-PG-6 upgraded: H1 mechanism CONFIRMED. [OBSERVED]

Three independent instruments now agree on pgvector's filtered-ANN behaviour:
1. **Plan text:** `EXPLAIN ANALYZE` at ef16 shows `Index Scan ... actual rows=1, Rows Removed by Filter: 15` — 16 HNSW candidates fetched, 15 discarded by the tenant predicate. Post-filtering, narrated by the engine.
2. **Forced-index probe:** scoped recall 0.25 / 0.54 at ef 16 / 40 vs the post-filter model's 0.20 / 0.50. (At ef64 observed 1.00 vs predicted 0.80 — the crude model saturates early for this geometry; tagged as model limitation, not anomaly.)
3. **Ledger (run 3, ANALYZE-pinned):** scoped 7a recall 0.23 / 0.50 / 1.00 / 1.00, matching the EXPLAIN plan boundary (Index Scan at ef16/40, Sort/exact at ef64/128) cell for cell.

**Mitigation measured:** `hnsw.iterative_scan = relaxed_order` recovers ef16 scoped recall 0.25 → **0.94**. pgvector's own H1 fix works; its latency price is not yet in the ledger (open action).

## F-PG-8 — Plan choice varies with ef and is now deterministic given stats. [OBSERVED; cost-model mechanism HYPOTHESIS]

The plan flips from HNSW index scan (ef16/40) to the exact Sort path (ef64/128) within one instance — and after ANALYZE pinning, run 3's ledger reproduces the diagnostic's plan boundary exactly. F-PG-7's instability is resolved instrumentally (verdicts are reproducible); *why* the cost estimate shifts with ef remains unconfirmed. Report-level sentence stands: a verdict on a planner-mediated engine is a verdict on engine + statistics state.

## F-QD — run 3 verdict PENDING one cell, two branches pre-registered.

Qdrant recall remains flat 1.00 at all ef. The discriminator — `indexed_vectors_count`, recorded per row since the threshold fix — was captured in the JSON but omitted from the CSV/console by a harness reporting bug (now fixed: CSV carries `index_config`; console tags rows `/ann` or `/PLAIN`). Branches, registered before looking:
- **indexed=4000:** rows are real ANN. Headline: Qdrant filterable-HNSW holds scoped recall 1.00 at ef16 where pgvector post-filter starves to 0.23 — the H1 architectural contrast (filter-aware traversal vs post-filter) observed across two engines on identical data. W6 `gone@1` then also stands on the target architecture.
- **indexed=0:** threshold fix ineffective; rows still plain-search; F-QD-1 stays open and the optimizer config needs investigation.
Circumstantial lean (not evidence): scoped queries ran *faster* than unfiltered (~1.3 vs ~2.2 ms), the signature of a filtered scan over fewer points. The JSON cell decides.

---

# Run 3 resolution: Qdrant branch (a) — ANN rows confirmed

`index_config` on all eight Qdrant configs: `indexed=4000, status=green`. The threshold fix took; the graph was built and live for every row. (The circumstantial "plain-search" lean from the latency pattern was wrong — recorded as a reminder that smells don't decide, cells do.)

## F-QD-3 — H1 outcome contrast across engines. [OBSERVED outcome; mechanism HYPOTHESIS]

On identical data, sweep, and k: Qdrant scoped recall **1.00 at every ef including 16**, where pgvector post-filter starves to **0.23**. The user-facing answer to "does the engine under-retrieve under selective filters" differs by engine — H1's cross-engine result.

Mechanism caveat: `indexed=4000` proves the index *exists*, not that the scoped query *traversed* it. Qdrant's filtered search performs per-query strategy selection (cardinality-estimated choice between filtered graph traversal and exact rescoring over payload-matched points); at 500-of-4000 selectivity it may have routed to the exact path — which would also explain scoped queries running faster than unfiltered. Durable framing: **pgvector exposes the filtered-ANN starvation problem to the user** (post-filter; mitigation is an opt-in GUC); **Qdrant absorbs it as an engine-internal planning problem.** Distinguishing Qdrant's internal strategies requires the N-sweep at selectivities that force traversal.

## F-QD-4 — W6 honest deletion on the target architecture. [OBSERVED, probe-scoped]

With the HNSW graph confirmed live, deletes (`wait=true`) were unrankable at the first read (`gone@1`, leak 0.00): mark-deleted points are excluded by the read path before physical reclaim. **Claims-but-leaks did not reproduce on its likeliest commercial candidate** under this probe. Untested windows that keep H5 partially open: optimizer mid-merge, large multi-segment indexes, and the W10 durability boundary (snapshot/restore reviving committed deletes).

## Standing assessment after three runs (the sentence the charter requires)

Two commercial engines tested; both PASS W6; both PASS W5 when driven as documented. **The evidence to date weighs toward RQ8 outcome (e), not the build case.** Surviving differentiators: the 7b deployment risk (observed on both engines — guarantees are by-convention and silently defeatable), absence of native bi-temporality (H4 direction, unstressed), attestation/receipts (H8, untested), and all scale-gated questions (RQ6 corner, frontier at real N, Qdrant mechanism, iterative_scan price). The decision gate stays open; the burden of proof currently sits on the gap, not on the engines.

## Critical path forward

Everything still unresolved is scale-gated. Next instrument: the N-sweep (1e5 → 1e6, higher tenant counts for forced selectivity), which simultaneously addresses the Qdrant mechanism question, the real recall/latency frontier, iterative_scan's price, storage amplification trends, and RQ6's claimed architectural corner.

---

# N-sweep findings (run_scale.py, N = 20,000 / 100,000)

**Setup:** dim=64, 64 tenants (selectivity 1/64), ef ∈ {16,64,256}, k=10, four variants (pgvector, pgvector+iterative_scan, qdrant default planner, qdrant full_scan_threshold=10). Canonical rows: `../rq9-cost-ledger/results/scale_ledger.{csv,json}`. All [OBSERVED] unless tagged.

## F-S-0 — Pre-registered prediction FAILED; model refined. [prediction adjudicated; refined model HYPOTHESIS]

Registered before the 100k rows existed: "default-qdrant unfiltered drops below 1.00 at 100k (26 MB > 10 MB threshold)." Observed: 1.00 flat at every ef. The collection-level threshold model is wrong. Refined model fitting all rows at both N: **full_scan_threshold is evaluated per segment** — 100k points split across ~8 segments of ~3 MB each, all below the 10 MB default, so even unfiltered queries took the exact path per segment; the forced variant (10 KB) tips every segment over and the graph engages (unfiltered 0.43 at ef16, classic HNSW shape). Confirmation cell: `indexed≈100000` on default rows (graph built but unused). New registered prediction for 1e6: segments ≈32 MB > default threshold → default unfiltered finally drops below 1.00 and varies with ef; scoped (cardinality ≈4 MB) stays exact at 1.00.

## F-S-1 — H1 at scale: starvation deepens and the planner escape-hatch closes. [OBSERVED]

pgvector scoped recall at 100k: 0.04 / 0.10 / 0.31 at ef 16/64/256 (model: 0.025/0.10/0.40). At 20k the planner rescued ef256 by flipping to the exact path over 312 tenant rows (scoped 1.00 @ 0.6 ms); at 100k (1,562 rows/tenant) it stops flipping and the engine-as-shipped tops out at **0.31 recall at its highest swept ef**. Post-filtering under selective filters is not degraded at scale — it is broken, and the small-N behaviour that masked it is itself scale-dependent.

## F-S-2 — The mitigation's price and ceiling. [OBSERVED; cap mechanism HYPOTHESIS]

iterative_scan at 100k: scoped recall 0.78–0.83, **plateaued across ef**, at p50 ~8 ms vs ~0.8–2.7 ms plain (≈7–10×). Recovery is partial at scale (vs ~0.99 at 20k) and the ef-independent plateau is the signature of a binding cap (plausibly hnsw.max_scan_tuples, default 20k tuples, and/or relaxed-order quality — untested). Ledger sentence: correct scoping on pgvector at 1/64 selectivity costs either ~10× latency for ~0.8 recall, or the recall itself.

## F-S-3 — Cross-engine H1 contrast holds at scale. [OBSERVED]

Identical data/ef/selectivity, ef16 @ 100k: qdrant forced graph traversal scoped recall **0.91** vs pgvector post-filter **0.04**. Filter-aware traversal also shows the telling inversion: forced-scoped (0.91) ≫ forced-unfiltered (0.43) — the filter shrinks the effective search problem rather than starving it. Post-filter vs filter-aware is now a measured architectural axis (RQ5), observed across two engines and two N.

## F-S-4 — RQ6 inputs: storage, build, and the missing reason-to-exist. [OBSERVED]

- Storage amplification pgvector: 94.1 MB / 25.6 MB raw = **3.67×** at 100k — matching 3.7× at n=4k; N-stable at this dim. (qdrant bytes remain estimate-class [REPORTED-self].)
- Build: pgvector ≈8.2k vec/s (12.2 s @ 100k, shm_size=1g required — Docker's 64 MB /dev/shm default cannot host a 512 MB parallel HNSW build); qdrant ≈16–20k vec/s.
- **oracle-exact at 100k: p50 1.14 ms** — in-process brute force still matches or beats every ANN configuration measured. At dim=64, N ≤ 1e5, ANN's latency advantage has not yet appeared; RQ6's "architectural corner" cannot be evaluated below ~1e6 on this corpus.

## F-S-5 — W6 honest at scale. [OBSERVED]

gone@1, leak 0.00, both engines, indexes 25–250× larger than runs 1–3. Claims-but-leaks remains unreproduced on every commercial configuration tested to date.

## Standing assessment (updated)

The guarantee side keeps feeding RQ8 outcome (e): isolation and deletion hold wherever the engines are driven as documented. What the N-sweep adds is that the live differentiator is **cost-shaped, not guarantee-shaped**: the price of *correct scoping* diverges enormously by architecture (0.04-or-10× on post-filter vs 0.91-at-par on filter-aware), and pgvector — the parent platform's own backend — sits on the expensive side of that axis. That is an RQ5/RQ8 input of direct consequence to GRAFOMEM Cloud regardless of the build decision. Remaining open: the 1e6 point (registered prediction above; RQ6 corner; ANN's latency case), H4 temporal stress, H8 attestation sweep.

---

# 1e6 addendum (N-sweep completion)

**Run:** N=1,000,000, same fingerprint family/seeds, builds 752 s (pgvector) / 64 s (qdrant). Slot **[1e6]** is filled.

## F-S-0 CLOSED — registered prediction CONFIRMED, both halves. [OBSERVED]

Predicted before the run: default-qdrant unfiltered drops below 1.00 and varies with ef at 1e6 (segments ~32 MB > 10 MB threshold); scoped (~4 MB cardinality) stays exact at 1.00. Observed: unfiltered 0.14/0.37/0.69, ef-monotone; scoped 1.00 flat. The per-segment full_scan_threshold model now carries a confirmed out-of-sample prediction (failed prediction → refined model → registered forecast → confirmed).

## F-S-6 — The mitigation does not scale; planning is the architecture. [OBSERVED]

iterative_scan across N at 1/64 selectivity: recall ceiling 0.99 → 0.81 → **0.43**; price 5 → 8 → **30 ms**. Recovery degrades as cost grows. The benchmark of shame: the correct answer at 1e6 is a ~15.6k-row exact tenant scan (~1 ms, recall 1.00). Qdrant's cardinality-aware fallback delivers exactly that (scoped **1.00 @ 1.7–1.8 ms, flat**); pgvector's planner no longer finds it (scoped 0.20 @ 11.4 ms at ef256). Mature statement of the axis: the engine that treats filtered search as a *planning* problem delivers exactness cheaply; the engine that bolts ANN onto a general planner delivers neither recall nor speed at this scale/selectivity.

## F-S-7 — pgvector at 1e6/dim64 is dominated by exact search. [OBSERVED; latency transport-caveated, recall not]

Unfiltered ef256: recall 0.47 @ 14.3 ms vs oracle-exact 1.00 @ 10.7 ms. Graph-quality gap at identical nominal params (M=16, efc=64): qdrant 0.69 vs pgvector 0.47 at ef256.

## F-S-8 — Build cliff; storage constant. [OBSERVED]

Build: pgvector 8.2k → **1.33k vec/s** from 1e5→1e6 (12.5 min); qdrant 19.7k → 15.6k. Storage amplification pgvector: **3.66×** at 1e6 — vs 3.70× (4k) and 3.67× (1e5): stable across three orders of magnitude.

## F-S-9 — Falsifier adjudication: no guarantee collapse at scale. [OBSERVED]

gone@1, leak 0.00, both engines, million-vector indexes. Per the RQ8 skeleton's pre-stated falsifiers: **[1e6] does not reopen outcome (a) via G6.** The RQ6 corner exists but is cost-shaped (build cliff, scoped collapse, mitigation decay) and one tested engine already stands outside it. Dim-conditioning caveat: at production dims (768–3072) the exact baseline grows ~12–48× and ANN's case strengthens; corner statements are conditioned on dim=64.

---

# H4-stress findings (run_h4_stress.py; slot [H4-STRESS] FILLED)

**Setup:** 20k chains × D ∈ {1,4,16} versions (20k/80k/320k physical), near-duplicate version vectors (drift 0.15), as_of mid-history + open-interval ("now") probes, four variants, ef ∈ {16,64,256}. Canonical: `../rq9-cost-ledger/results/h4_ledger.{csv,json}`.

## Prediction adjudication

- **P4 CONFIRMED:** leak 0.00 on every row — temporal predicates enforce validity wherever applied. The cost, not the violation, is the finding (as registered).
- **P1 CONFIRMED qualitatively, REFINED:** the bi-temporal tax of version-as-row is **twofold**. At D=4, pgvector as_of recall (0.20/0.44/0.82) ≈ its *unfiltered* curve at the same physical N — N-inflation degrades the graph before filter starvation binds; at D=16 both channels compound (0.04/0.12/0.31). The pure `ef/(D·k)` model under-predicts damage. iter ceiling again: 0.29–0.40 flat.
- **P2 HALF-FAILED (owned):** default-Qdrant 1.00 flat ✓ (fallback exactness); but forced filtered-HNSW is **not graceful — it collapses**: worse than pgvector at D=4 (0.06/0.21/0.52), and **0.00 flat / OVER_RESTRICTS at D=16, every ef**. Mechanism [HYPOTHESIS]: validity scattered one-per-tight-cluster at 1/16 selectivity disconnects the filtered subgraph; traversal cannot reach valid points. This is RQ5's structural filtered-ANN failure regime reached empirically — and it reframes the planner: **Qdrant's cardinality fallback is load-bearing, not cosmetic.** Exposing the collapse required forcing a non-default configuration.
- **P3:** storage linearity in the ledger file (printer shows build rate); verify the cell.

## F-H4-3 — Nobody delivers cheap, correct as_of: G3 gains observed teeth. [OBSERVED]

The price of Qdrant's exactness grows ~linearly with D: p50 10.5 → 24.9 → **65.1 ms** (mid); the open-interval "now" probe costs more still (83–84 ms at D=16 — sentinel range-scan overhead, H2-adjacent). The D=16 field: pgvector 0.04 recall @ ~1 ms (fast, wrong); Qdrant 1.00 @ 65 ms (right, paying for the bloat linearly); the ideal — index only what is valid, supersession first-class — would be ~1.00 @ ~1 ms. **First observed evidence in the project that strengthens the (a)/(b) case via G3.** Required honesty: an untested adapter-layer candidate exists — epoch partitioning / partial indexes (current-only partial index on the sentinel; epoch-partitioned collections). G3's next falsifiable question: does adapter-level partitioning recover the ideal? Yes → G3 closes like every prior gap; no → the build case has its first load-bearing, engine-native-shaped gap.

## Standing assessment (updated post-H4)

Guarantee side: unchanged — still feeds (e); leak 0.00 throughout, claims-but-leaks never reproduced anywhere in the project. Cost side: the asymmetry now has a *temporal* axis sharper than the tenancy axis — emulated bi-temporality costs either correctness (post-filter), linear-in-D latency (exact fallback), or hits a structural traversal collapse (forced graph). G3 is the one gap trending toward engine-native; it carries one untested adapter-layer mitigation before that conclusion is permitted.

---

# G3 probe results (run_g3_probe.py) — THE GATE FIRED TOWARD (c)

**Adjudication against the registered gate (GP1–GP3):**
- **GP1 PASS:** D=16 as_of recall 0.42/0.75/0.97 (mid) ≈ the D=1 baseline 0.41/0.74/0.98 — D-independent, vs monolithic 0.04/0.12/0.31 on the identical corpus. Every query sees a ~20k-row index regardless of history depth.
- **GP2 PASS:** D=16 p50 0.6–1.8 ms, flat in D, vs Qdrant's 64–84 ms exactness-via-fallback. Leak 0.00 on every row — the in-query predicate held with routing active.
- **GP3 SPLIT (owned):** storage tax tracks +1/D as predicted (D=4 +~25%, D=16 +~6%); the build half FAILED — 59.6 s vs 25.2 s monolithic (~2.4×, per-table index overhead). Bounded and predictable, but the prediction was wrong.

**Decisive line (D=16, ef256, one fingerprint):** monolithic pgvector 0.31 @ 2.4 ms · iter 0.39 @ 2.2 ms · qdrant fallback 1.00 @ 64 ms · **pg-partitioned 0.97 @ 1.8 ms**. The ideal F-H4-3 attributed to native bi-temporality was reached by an adapter, a sentinel partial structure, and a routing function. **G3 closes at the adapter layer; native bi-temporality is an optimization, not a requirement; RQ8 outcome (c).** Carried caveats: epoch-aligned corpus (favorable case; ~2× placement bound for arbitrary chain-shaped intervals); build 2.4×.

Decision document: `../rq8-decision/RQ8_MEMO.md`.

---

# Q2 probe results (run_g3_qdrant.py) — verdict + a correction to our own record

## F-Q2-0 — CONFOUND in F-H4-3, owned. [OBSERVED]

`qdrant-rangeidx` (monolithic + integer payload indexes on valid_from/valid_until) at D=16: **1.00 recall @ 1.5–3.4 ms** vs H4's 64–84 ms. The H4 Qdrant adapter never indexed the validity fields; ~95% of the reported "linear-in-D price of exactness" was an unindexed-range-filter artifact of our instrument, not engine cost. **All H4 qdrant latency rows hereby carry a CONFOUND flag.** F-H4-3's claim narrows to: *pgvector's* emulated as_of pays the twofold tax (those recall measurements were confound-free); a properly-indexed planning engine delivers exact as_of at ~2 ms flat. Finding the confound via a registered probe is the discipline functioning on its own authors.

## F-Q2-1 — Partitioning is moot on Qdrant. [OBSERVED]

`qdrant-partitioned`: 1.00 @ 1.5–2.6 ms (QP1/QP2 pass as registered) — but adds nothing over rangeidx while costing 3.5× build (63.7 s vs 18.2 s) and +6% storage. The cheapest adapter-layer fix per engine differs: pgvector needs partitioning; Qdrant needs a payload index. Rangeidx also generalizes better (no epoch-alignment dependence).

## F-Q2-2 — Backend verdict (flow-back A resolved). [OBSERVED]

D=16 final table, one fingerprint family: pgvector monolithic 0.31 @ 2.4 ms · pg-partitioned 0.97 @ 1.8 ms · **qdrant-rangeidx 1.00 @ ~2 ms**. Qdrant + correct payload indexing wins every measured axis (tenancy, scale, build, temporal). **Recommendation: adopt Qdrant as the GRAFOMEM Cloud vector backend**, retaining the pg-partitioned pattern as documented fallback for Postgres-colocated deployments. Scope condition: exactness rides on per-segment valid-sets under the full-scan threshold; re-verify at production scale where valid-sets exceed it (planner routes to HNSW, recall may dip).

## Memo erratum

RQ8_MEMO.md §2/G3's decisive line cited "qdrant fallback 1.00 @ 64 ms" — corrected by F-Q2-0 to ~2 ms when properly indexed. The correction *strengthens* outcome (c): the only gap that ever pointed at build/extend closes even more cheaply than the gate assumed. Recommendation unchanged.
