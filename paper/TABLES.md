# Camera-ready tables (v0.1) — with scoped captions

Source ledgers: `research/rq9-cost-ledger/results/{cost,scale,h4,g3,g3q}_ledger.csv`
and `research/rq7-conformance/commercial_ledger.csv`. Every cell verifiable via
`harness/rq9/audit_numbers.py`. Shared fingerprint family: macOS arm64,
10 physical cores, dim=64, k=10, seeds 1729/4104; all latencies client-observed,
transport-inclusive; engines containerized on loopback.

---

## Table 1 — Two-sided conformance, both postures (§4)

n=4,000 · 8 interleaved tenants · per-engine best swept configuration.

| engine | posture | W5 scoped recall | W5 leak | W5 verdict | W6 leak | W6 gone@ | W6 verdict |
|---|---|---|---|---|---|---|---|
| pgvector | 7a engine-correct | 1.00 | 0.00 | PASS | 0.00 | 1 | PASS |
| pgvector | 7b as-deployed | 0.14 | 0.85–0.86 | **LEAKS** | 0.00 | 1 | PASS¹ |
| Qdrant | 7a engine-correct | 1.00 | 0.00 | PASS | 0.00 | 1 | PASS |
| Qdrant | 7b as-deployed | 0.14 | 0.85–0.86 | **LEAKS** | 0.00 | 1 | PASS¹ |

*Caption:* The inversion and the relocation in one table: driven as documented
(7a), both engines hold both boundaries; with the tenant predicate omitted on
read (7b) — one integration line — both silently return the global top-k, with
full-looking results and no error. ¹Deletion is adjudicated by its own leak
column; 7b's depressed deletion-row recall is cross-scenario contamination from
the isolation failure, adjudicated by the W5 row. (Fingerprint-bound: none —
all cells in this table are portable.)

## Table 2 — Post-filter starvation: the mechanism (§5.1)

pgvector, n=4,000, tenant selectivity 1/8, statistics pinned (ANALYZE).

| instrument | ef16 | ef40 | ef64 | ef128 |
|---|---|---|---|---|
| candidate-budget model min(1, ef·s/k) | 0.20 | 0.50 | 0.80² | 1.00² |
| forced-index probe (observed) | 0.25 | 0.54 | 1.00 | — |
| engine-as-shipped ledger (observed) | 0.23 | 0.50 | 1.00³ | 1.00³ |
| unfiltered baseline (observed) | 0.67 | 0.89 | 0.96 | 0.99 |
| + iterative_scan mitigation | 0.94 | — | — | — |

*Caption:* Three independent instruments agree. Plan text at ef16:
`Index Scan … rows=1, Rows Removed by Filter: 15` — sixteen candidates fetched,
fifteen discarded post-scan. ²Model saturates early for this geometry (recorded
limitation). ³Planner abandons the index for an exact filtered sort at ef≥64 at
this small scale — the escape-hatch that closes at 10⁵ (Table 3). Recall cells
portable; dim=64 conditioning applies to any latency reading.

## Table 3 — Scale: the divergence (§5.1–5.3)

Selectivity 1/64 (64 tenants) · ef ∈ {16, 64, 256} · scoped recall@10 [@ p50 ms where stated].

| engine / variant | N=2×10⁴ | N=10⁵ | N=10⁶ |
|---|---|---|---|
| pgvector (shipped) | 1.00 (planner→exact) | 0.04 / 0.10 / 0.31 | best 0.20 @ 11.4 ms (ef256) |
| pgvector + iterative_scan (ceiling @ price) | 0.99 @ 5 ms | 0.81 @ 8 ms | 0.43 @ 30 ms |
| Qdrant (default planner) | 1.00 flat | 1.00 flat | **1.00 flat @ 1.7–1.8 ms** |
| Qdrant (forced traversal, non-default) | — | 0.91 (ef16; vs unfiltered 0.43) | — |

Supporting cost rows, same fingerprint:

| measure | pgvector | Qdrant | oracle (exact, in-process) |
|---|---|---|---|
| build rate 10⁵ → 10⁶ (vec/s) | 8.2k → **1.33k** | 19.7k → 15.6k | — |
| storage amplification (4×10³ / 10⁵ / 10⁶) | 3.70× / 3.67× / 3.66× | estimate-class | 1× (raw) |
| unfiltered @ 10⁶, ef256 | 0.47 @ 14.3 ms | 0.69 | 1.00 @ 10.7 ms |

*Caption:* Post-filtering is not degraded at scale — it is broken, and the
small-N planner rescue is itself scale-dependent. The mitigation's recall
ceiling decays as its price grows. The planning engine delivers exactness at
the cheapest correct plan (~15.6k-row exact tenant scan). Forced traversal is
a deliberately non-default configuration. Latencies fingerprint-bound,
transport-inclusive, dim=64 (at production dims the exact baseline inflates
~with the dimension ratio and ANN's case strengthens).

## Table 4 — The supersession tax (§5.4)

20k chains × D versions (drift 0.15) · as_of mid-history · recall@10 [@ p50 ms].

| variant | D=1 (20k rows) | D=4 (80k) | D=16 (320k) |
|---|---|---|---|
| pgvector | 0.42 / 0.75 / 0.99 | 0.20 / 0.44 / 0.82 | 0.04 / 0.12 / 0.31 @ 0.8–2.4 ms |
| pgvector + iterative_scan | 0.39 / 0.75 / 0.98 | 0.44 / 0.53 / 0.86 | 0.29 / 0.31 / 0.39 |
| Qdrant (default) ⚑ | 1.00 @ 10.5 ms | 1.00 @ 24.9 ms | 1.00 @ 65.1 ms (now-probe 83–84 ms) |
| Qdrant (forced traversal, non-default) | 0.58 / 0.93 / 1.00 | 0.06 / 0.21 / 0.52 | **0.00 / 0.00 / 0.00 — OVER_RESTRICTS** |

*Caption:* Cells are ef 16/64/256. The twofold tax: D=4's curve matches the
engine's *unfiltered* recall at comparable physical N (N-inflation degrades the
graph before the validity filter starves). Temporal leakage 0.000 in every
cell. ⚑ CONFOUND FLAG (F-Q2-0): the default-Qdrant latencies in this table
were produced with the validity fields unindexed by our adapter — ~95% of the
cost is instrument artifact, corrected in Table 5; recall cells unaffected.
The forced-traversal collapse is the study's only OVER_RESTRICTS firing and
arises under a deliberately non-default threshold.

## Table 5 — Adapter-layer closures: the decisive cells (§5.5–§6)

D=16 (320k physical rows) · as_of · ef256 unless noted · one fingerprint family.

| approach | recall | p50 | build (D=16) | storage note |
|---|---|---|---|---|
| pgvector monolithic | 0.31 | 2.4 ms | 25.2 s | 3.66–3.70× raw |
| pgvector + iterative_scan | 0.39 | 2.2 ms | — | — |
| Qdrant unindexed-validity (H4, confound-flagged) | 1.00 | 64–84 ms | 14.6–15.7 s | estimate-class |
| **pg-partitioned (epoch + sentinel snapshot)** | **0.97** | **1.8 ms** | 59.6 s (2.4×, GP3-half failed) | +1/D placement (+6% @ D=16) |
| **Qdrant + validity payload indexes** | **1.00** | **1.5–3.4 ms flat in D** | 18.2 s | estimate-class |
| Qdrant collection-per-epoch (moot) | 1.00 | 1.5–2.6 ms | 63.7 s (3.5×) | +6% |

Gate adjudication (registered before the runs): GP1 PASS — partitioned D=16
recall 0.42/0.75/0.97 ≈ D=1 baseline 0.41/0.74/0.98, depth-independent;
GP2 PASS — p50 0.6–1.8 ms flat in D; GP3 split — storage +1/D as predicted
(D=4 +25%, D=16 +6%), build half FAILED (2.4×, owned). QP0 — payload indexes
alone recover exactness: the H4 row above carries the confound.

*Caption:* The cheapest sufficient fix differs per architecture — partitioning
on the post-filter engine, two index declarations on the planning engine —
and both live in the adapter. Native bi-temporality: optimization, not
requirement. Latencies fingerprint-bound, dim=64; partitioning measured on
epoch-aligned intervals (favorable case, ~2× placement bound general).
