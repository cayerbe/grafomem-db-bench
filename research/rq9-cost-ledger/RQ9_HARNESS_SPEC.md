# RQ9 — Cost Ledger Harness (Specification + Reference Implementation)

**Status:** R0 instrument. Reference implementation runs today (numpy-only); commercial adapters (pgvector, Qdrant) run when those services are reachable.
**Belongs to:** MOBY DB research, RQ9 (§4) — *"the price of every guarantee."*
**One-line contract:** every correctness verdict the W5/W6 suite produces gets a measured price on the same row, on a common harness, source-tagged `[OBSERVED]`. RQ8 cannot rule outcome (e) in or out without this.

---

## 1. What this instrument is, and what it refuses to be

The parent project already owns the *correctness* instrument — the two-sided W5/W6 suite that decides PASS / LEAKS / OVER_RESTRICTS against an external oracle. RQ9 adds the missing axis: **what each verdict costs**. It is built so that a guarantee can never be reported without its price, because that omission is exactly how a correctness-maximal design (honest deletion, physical isolation, native bi-temporality) gets to look like a "win" over performance-maximal incumbents when it is really a *trade*.

Three non-negotiables, inherited from the parent discipline:

1. **Oracle-grounded, deterministic.** Recall and leak are measured against an exact brute-force KNN oracle over a seed-pinned corpus — never against another engine's output, never via an LLM judge. These numbers reproduce bit-for-bit on any machine.
2. **Cost is paired, never freestanding.** A latency row without the recall it bought is discarded — a fast wrong answer is not a finding.
3. **Portability is labelled.** `recall_at_k`, `leak_rate`, and `ops_until_gone` are hardware-independent and travel. **Latency is environment-bound** and is comparable *only within one fingerprint*. The harness stamps every run so nobody cross-reads latency between machines.

---

## 2. Corpus (deterministic, adversarial by construction)

`make_corpus(seed, n, dim, n_tenants, superseded_frac)` → seed-pinned. Defaults used in the worked example: `n=4000, dim=64, n_tenants=8, k=10`.

- **Interleaved tenants.** Tenant cluster centres share the embedding space and records are assigned round-robin, so the *true* nearest neighbours of a tenant-A query **include tenant-B vectors**. This is deliberate: it forces tenant scoping to exclude by *scope*, not by distance — the only honest way to pass W5. A store that filters "by convention" and then drops the filter (the 7b path, §6) leaks here visibly, and the leak is a measured fraction, not a yes/no.
- **Query-adjacent delete set.** The deletion scenario removes records that are near-neighbours of the probe, so removal actually changes the answer. A tombstone the read path ignores shows up as deleted ids still ranked — W6 in miniature.
- **Sentinel-encoded open intervals.** `valid_until` defaults to `T_OPEN = 2**62` ("still true"), with a `superseded_frac` carrying closed intervals. This is H2 sentinel encoding in the *literal, glossary-fixed* sense — an extreme constant so an open interval is range-scannable. It is an indexing convenience, **not** a security property, and the code comments say so at the definition site.

Corpus parameters scale: run the full table at `n ∈ {1e4, 1e5, 1e6}` for the §RQ6 "architectural corner" sweep; the worked example uses `n=4000` so it completes in seconds for CI.

## 3. Queries

`make_queries(seed, n_queries, dim)` draws from a **disjoint random stream** (`seed + 9973`) so queries are never corpus members. Default `n_queries=60`; the first `warmup=5` latency samples per scenario are discarded (cache/connection warmup) while their *outputs* are kept for recall.

## 4. k and index config — recorded on every row

`recall@k` is meaningless without the ANN search parameter that produced it. Every ledger row carries `index_config` verbatim (e.g. `index=hnsw,M=16,ef_construction=64,ef_search=40`). Sweep `ef_search` / `probes` to trace the recall-vs-latency frontier per engine; each point is its own row. Comparing two engines means comparing *frontiers at matched recall*, never single points.

## 5. The five scenarios (each bound to a correctness anchor)

| scenario | anchor | oracle (what SHOULD return) | cost collected |
|---|---|---|---|
| `retrieve.unfiltered` | — | exact top-k, whole corpus | recall@k, p50/p95/p99/max |
| `retrieve.tenant_scoped` | **W5** | exact top-k **within querying tenant** | recall@k (must-return), **leak_rate** (out-of-tenant returned), latency |
| `delete.honest` | **W6** | exact top-k over corpus **minus deleted** | **leak of deleted**, `delete_ack_ms`, **delete-to-unretrievable** (walltime + op-count), post-delete storage |
| `retrieve.as_of` | **H4 / RQ4** | exact top-k among records valid `as_of t` | recall@k, leak of temporally-invalid, latency, native-vs-emulated tag |
| `storage.amplification` | **H3** | — | live+dead footprint; physical-vs-logical tag |

**Two-sided verdict rule** (encoded in `_verdict`): `leak>0` → LEAKS; `recall==0` → OVER_RESTRICTS; `recall≥0.999 & leak==0` → PASS. **0.000 leak with 0.000 recall is never a pass.** This mirrors the parent W5/W6 table exactly.

### 5.1 Delete-to-unretrievable — the portable W6 footprint

The headline W6 measurement is *not* wall-clock. `delete_unretrievable()` polls `retrieve()` after a delete and reports **`ops_until_gone`** — the number of read calls until none of the deleted ids is rankable. This is hardware-independent: an honest read-path excision goes at probe 1; a store whose read path never consults the tombstone never goes within budget (`gone@never`) — which *is* claims-but-leaks, in a number. `delete_ack_ms` (when the API returned) is reported alongside, so the gap between "delete returned 200" and "actually gone" is on the row.

## 6. 7a engine-correct vs 7b engine-as-deployed

The commercial adapters expose `deployed_correctly`:

- **7a (engine-correct):** the API used exactly as documented — tenant predicate set, tombstones honoured. Measures the engine on its best behaviour.
- **7b (engine-as-deployed):** the realistic-misconfiguration path — tenant filter omitted, default namespace, scope dropped by the calling layer. This is where real agent stacks fail.

Run both per target. **A 7a PASS with a 7b LEAK is itself the headline result** (the guarantee exists but is opt-in and silently defeatable). The reference foils in this repo (`LeakyTenant`, `TombstoneLeaky`) are the 7b failure modes made explicit so the harness output is interpretable before any commercial engine is wired in.

## 7. Fingerprint & reproducibility

Every run emits a fingerprint: platform, CPU physical cores, RAM, Python/numpy versions, both seeds, k, UTC, and the comparability note. Two runs with the same seeds produce identical recall/leak/op-count; latency is re-measured. The fingerprint is the unit within which latency may be compared — across fingerprints, only the portable metrics travel.

## 8. Output schema

`out/cost_ledger.json` (fingerprint + full rows) and `out/cost_ledger.csv` (flat). One `LedgerRow` per (engine, scenario): engine/version/index_config, scenario, `w_ref`, correctness verdict, `recall_at_k`, `leak_rate`, `p50/p95/p99/max_ms`, `throughput_ops_s`, `storage_bytes`, `delete_ack_ms`, `unretrievable_ms`, `ops_until_gone`, `source_class` (always `OBSERVED` here), notes. The verdict column is filled by the oracle, not the engine.

## 9. Worked example — real output from this implementation

Run on a single-core container (`n=4000, dim=64, 8 tenants, k=10, seeds 1729/4104`). Reference backends only; **these are actual measured rows**, not illustrations:

```
engine          scenario              W      verdict        rec@k  leak   p50ms  ack_ms  gone@     bytes
ReferenceHonest retrieve.unfiltered   -      PASS            1.00     -    2.95       -      -   1024000
ReferenceHonest retrieve.tenant_scoped W5    PASS            1.00  0.00    0.41       -      -   1024000
ReferenceHonest retrieve.as_of        H4/RQ4 PASS            1.00  0.00    4.08       -      -   1024000
ReferenceHonest storage.amplification H3     N/A                -     -       -       -      -   1024000
ReferenceHonest delete.honest         W6     PASS            1.00  0.00       -    1.21      1   1022720
TombstoneHonest retrieve.unfiltered   -      PASS            1.00     -    3.01       -      -   1024000
TombstoneHonest retrieve.tenant_scoped W5    PASS            1.00  0.00    0.95       -      -   1024000
TombstoneHonest delete.honest         W6     PASS            1.00  0.00       -    0.00      1   1024000
TombstoneLeaky  delete.honest         W6     LEAKS           0.50  0.50       -    0.00  never   1024000
LeakyTenant     retrieve.tenant_scoped W5    LEAKS           0.14  0.86    3.05       -      -   1024000
LeakyTenant     delete.honest         W6     PASS            0.00  0.00       -    0.00      1   1024000
```

How to read it — the cost↔correctness pairing the ledger exists to surface:

- **`ReferenceHonest` vs `TombstoneHonest` on W6.** Both PASS deletion (leak 0, gone@1). The *price* differs: ReferenceHonest pays `ack=1.21ms` (true row excision → array rebuild) and its storage **drops** to `1022720`; TombstoneHonest deletes in `~0ms` but storage **stays** at `1024000` until `compact()`. Same verdict, different bill — invisible without RQ9.
- **`TombstoneLeaky` on W6.** Delete returns in `0ms`, `audit()` reports the record gone — yet it stays rankable (`gone@never`, leak 0.50). This is claims-but-leaks as a measured window: cheap, "successful", and porous.
- **`LeakyTenant` on W5.** In-tenant recall collapses to `0.14` with `0.86` cross-tenant leak — the foil that consults distance but not scope.
- **Honest harness caveat (worth keeping in the report):** `LeakyTenant`'s `delete.honest` row shows PASS but `recall 0.00`. The deletion verdict is deletion-specific; the recall-0 here is contamination *from* its isolation failure (it returns cross-tenant ids the in-tenant oracle never lists), and that failure is adjudicated by its **W5** row, not W6. Scenarios are scored on their own anchor; cross-effects surface as flags, not silent passes.

(Reference backends are exact, so their `rec@k` on unfiltered is 1.00 by construction — the variable they exercise is the *cost and leak* surface. Commercial ANN engines will trade recall below 1.00 for latency, and *that* frontier is what RQ8 compares.)

## 10. Runbook

```bash
cd rq9
python run_demo.py                      # reference backends, numpy only -> out/

# pgvector (RQ7 control). Needs Postgres + vector ext.
export RQ9_PG_DSN='postgresql://user:pass@localhost:5432/rq9'
#   then in a runner: PgVectorBackend(dim=64, index='hnsw', deployed_correctly=True)   # 7a
#                     PgVectorBackend(dim=64, index='hnsw', deployed_correctly=False)  # 7b

# Qdrant (first commercial target).
docker run -p 6333:6333 qdrant/qdrant
export RQ9_QDRANT_URL='http://localhost:6333'
#   QdrantBackend(dim=64, deployed_correctly=True / False)
```

Commercial adapters implement the identical `Backend` protocol (`write/supersede/delete/retrieve/audit/flush/compact/storage_bytes` + `Capabilities`), so they drop into the same `run_all()` → `emit()` path; the only new outputs are real engine rows beside the reference anchors.

## 11. Honest limitations

- **Latency is single-machine.** The worked example ran on one core; absolute ms are not portable and the harness says so. Recall/leak/op-count are.
- **`storage_bytes` is best-effort** per engine (pgvector exposes `pg_total_relation_size`; Qdrant does not expose exact on-disk cheaply — estimated). Tag the precise ones `[OBSERVED]` and the estimates `[REPORTED-self]`.
- **Reference backends are exact, not ANN.** They are controls, not stand-ins for engine behaviour. The recall-vs-latency *trade* only appears once a real ANN index (pgvector HNSW, Qdrant HNSW) is wired in and `ef_search` is swept.
- **The corpus is synthetic.** It is built to be adversarial on the isolation/deletion boundaries on purpose; it is not a claim about real embedding distributions. A second pass on a real embedded corpus (held-out, deterministic) is a fair extension once the boundary behaviour is characterised.

## 12. Maps to R0 exit criterion (3)

This instrument satisfies R0 exit (3) — *"the RQ9 cost ledger pairs every correctness verdict with its measured price on a common local harness"* — once at least the two RQ7 targets (pgvector-as-control, Qdrant) have run all five scenarios at matched recall on one fingerprint, with 7a and 7b reported separately. The reference anchors ship now so the table is interpretable from the first commercial row.
