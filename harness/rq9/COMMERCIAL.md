# Running a real engine through the cost ledger (pgvector, the RQ7 control)

pgvector is the control: it's already the GRAFOMEM Cloud backend, local-runnable,
and PostgreSQL-licensed. Getting its rows into the ledger validates the adapter
protocol against a real engine and produces the first genuine recall-vs-latency
frontier (the foils are exact and cannot show that trade).

## One-time

    pip3 install psycopg2-binary          # the harness itself needs only numpy
    docker compose up -d                  # throwaway pgvector on :5432 (tmpfs)
    export RQ9_PG_DSN='postgresql://rq9:rq9@127.0.0.1:5433/rq9'

## Run

    python3 run_commercial.py             # -> out/commercial_ledger.{csv,json}

This runs pgvector in both postures across an ef_search sweep, beside the exact
ReferenceHonest anchor:

  * 7a engine-correct      tenant predicate applied (API as documented)
  * 7b engine-as-deployed  tenant predicate dropped (realistic misconfig)
  * ef_search in {16,40,64,128}   one row-set per point on the frontier

## What to look for

  * W5 / retrieve.tenant_scoped: does 7a hold (leak 0, recall high) while 7b
    leaks? That gap -- guarantee present but opt-in and silently defeatable --
    is the headline RQ7 result. (pgvector's tenant scope is a WHERE clause, so
    expect exactly this shape.)
  * W6 / delete.honest: pgvector does a real DELETE; MVCC visibility should make
    deleted rows unretrievable immediately (gone@1, leak 0), but storage stays
    inflated until VACUUM. Call `backend.compact()` (VACUUM) to see reclaim --
    same deferred-storage shape as TombstoneHonest, on a real engine.
  * recall@k vs p50ms across ef: this is the FRONTIER. Compare engines at matched
    recall, never at a single ef point.

## Commit canonical numbers

`out/` is scratch. When a run is the reference one, copy it into the tracked
results tree and commit:

    cp out/commercial_ledger.* ../../research/rq7-conformance/

## Tear down

    docker compose down                   # nothing persists (tmpfs)

---

# Engine 2: Qdrant (first non-control target)

Why Qdrant is the interesting W6 case: deletes are mark-deleted inside HNSW
segments and physically reclaimed only by the optimizer. The probe asks whether
"applied" (delete ack, wait=true) equals "unrankable" -- the exact gap where a
claims-but-leaks window would live on a real engine. Tenant scope is a payload
filter (logical, by convention), so the 7a/7b split applies identically.

## One-time

    pip3 install qdrant-client
    docker compose up -d              # starts qdrant on 127.0.0.1:6333 (and pgvector)

## Run

    python3 run_commercial.py         # sweeps hnsw_ef x {7a,7b} for qdrant too

RQ9_QDRANT_URL defaults to http://127.0.0.1:6333; export it only if different.

## What to look for

  * W6 / delete.honest: gone@1 expected (Qdrant's read path excludes mark-deleted
    points before reclaim). gone@>1 or never = a real claims-but-leaks window.
    Either result is a finding.
  * W5: same 7a-PASS / 7b-LEAK shape as pgvector predicted (payload filter).
  * Filtered recall vs ef: unlike pgvector (whose planner bypassed the index at
    n=4k, F-PG-4), Qdrant's filterable HNSW always goes through the graph --
    so the tenant_scoped rows here DO exercise filtered-ANN. Watch whether
    scoped recall at low ef drops below unfiltered (under-retrieval, H1/RQ5).
  * storage_bytes is ESTIMATED for Qdrant (points x dim x 4) -- tag
    [REPORTED-self], not [OBSERVED], unlike pgvector's exact figure.

## Adapter validation note

The adapter supports url=":memory:" (qdrant-client local mode) for plumbing
validation only -- exact search, no real HNSW. Never cite local-mode numbers as
engine behaviour.
