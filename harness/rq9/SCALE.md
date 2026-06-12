# The N-sweep (run_scale.py)

Every question left open after runs 1–3 is scale-gated. This instrument answers
them together, on one fingerprint.

## What it measures, per (variant, N)

| row | answers |
|---|---|
| `ingest.build` | bulk load + index build time (vec/s) — a *price*, not overhead |
| `retrieve.unfiltered` × ef {16,64,256} | the real recall/latency frontier |
| `retrieve.tenant_scoped` × ef, selectivity **1/64** | H1 at scale; W5 cost |
| `delete.honest` | W6 `gone@` on a large index; ack + post storage |
| `oracle-exact` anchor | vectorized exact baseline per N |

Variants:
- **pgvector** — post-filter default (7a only; the 7b leak is established and scale-invariant arithmetic)
- **pgvector-iter** — `hnsw.iterative_scan=relaxed_order`: the H1 mitigation's *price* (recall recovery vs latency, same rows)
- **qdrant** — the engine's own filtered-search planner
- **qdrant-forced** — `full_scan_threshold=10 (engine minimum)`, forcing filtered queries through the HNSW graph. **This splits F-QD-3's mechanism:** if forced-traversal scoped recall *drops* at low ef while the default holds, the default's 1.00 came from the exact fallback and Qdrant's answer to H1 is *planning*, not graph magic; if forced traversal also holds, filter-aware HNSW genuinely works.

## Run

    cd harness/rq9
    docker compose up -d
    export RQ9_PG_DSN='postgresql://rq9:rq9@127.0.0.1:5433/rq9'
    python3 run_scale.py                      # default N = 20,000 and 100,000

Expected wall time at defaults: minutes-to-tens-of-minutes, dominated by
pgvector HNSW builds (the build seconds print live and become ledger rows).

The 1e6 point is deliberate, not default:

    export RQ9_SCALE_NS="1000000"
    export RQ9_QDRANT_GREEN_TIMEOUT=1800
    python3 run_scale.py                      # plan for an hour+; it checkpoints

## Checkpointing

Each completed (variant, N) appends to `out/scale_rows.jsonl` and is skipped on
rerun — a run that dies at variant 3 resumes there. Delete the jsonl to start
fresh. `out/scale_ledger.{csv,json}` are regenerated from the checkpoint every
run; commit those to `research/` when canonical.

## Reading it

1. **Frontier:** unfiltered recall vs p50 across ef, per engine, at each N —
   compare engines at matched recall only. The oracle-exact row shows where
   brute force stops being competitive (ANN's reason to exist appearing).
2. **H1 at scale:** pgvector scoped recall at ef16 with 1/64 selectivity —
   post-filter model predicts ~ef·sel/k ≈ 0.025·ef/10. pgvector-iter's same
   row shows the mitigation's recall; its p50 vs plain pgvector is the price.
3. **The Qdrant split:** qdrant vs qdrant-forced on scoped rows (see above).
4. **RQ6 inputs:** build vec/s and storage bytes vs N — where guarantees and
   scale start to trade.
5. **W6 at scale:** `gone@` on indexes 25–250× larger than runs 1–3.

## Honest limitations

- dim=64 synthetic vectors: smaller than production embeddings (768–3072);
  amplification and build-rate *trends* transfer, absolute numbers don't.
- Latency still includes client/TCP transport (same caveat as F-PG-3).
- qdrant `storage_bytes` remains estimate-class [REPORTED-self].
- `:memory:` qdrant URL runs the driver but measures nothing real — plumbing
  validation only.

## Resource notes (learned at N=1e5)

- pgvector's parallel HNSW build allocates shared memory ~= maintenance_work_mem;
  the compose file sets `shm_size: "1g"` because Docker's 64 MB default fails
  with DiskFull at N>=1e5. Recreate the container after pulling this change.
- Both data dirs are tmpfs (RAM). At N=1e6 the pgvector table+index can reach
  several GB in RAM: give the Docker VM >=8 GB before attempting the 1e6 point,
  or drop the tmpfs line to use disk (slower, but bounded).
