# RQ9 cost-ledger harness (runnable code)

Spec lives at `../../research/rq9-cost-ledger/RQ9_HARNESS_SPEC.md`.
Canonical observed results live at `../../research/rq9-cost-ledger/results/`.

## Run (numpy only)
    python run_demo.py        # reference backends -> out/cost_ledger.{csv,json}

## Run against a live engine
    export RQ9_PG_DSN='postgresql://user:pass@localhost:5432/rq9'   # pgvector (control)
    docker run -p 6333:6333 qdrant/qdrant && export RQ9_QDRANT_URL='http://localhost:6333'

Adapters implement the same `Backend` protocol, so they drop into the identical
`run_all()` -> `emit()` path. `out/` is scratch for local runs; commit canonical
numbers to `research/rq9-cost-ledger/results/`.
