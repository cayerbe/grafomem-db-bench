# grafomem-db-bench — artifact repository

Artifact for: *The Guarantees Hold, the Costs Diverge: A Two-Sided
Conformance and Cost-Ledger Study of Vector Databases for Governed Agent
Memory* (Concept DOI: 10.5281/zenodo.20666338 (this snapshot: 10.5281/zenodo.20666339)). Companion benchmark paper: GRAFOMEM
(academia.edu/167598244).

## What's here
- `harness/rq9/` — adapter protocol, exact-KNN + bi-temporal oracles,
  two-sided metrics, drivers (conformance, scale, supersession,
  partitioning gate, Qdrant probe), `audit_numbers.py`.
- `research/rq9-cost-ledger/results/` — the five canonical ledgers
  (CSV+JSON, embedded hardware fingerprints).
- `research/rq7-conformance/` — evidence log (F-PG/F-QD/F-S/F-H4/G3/Q2
  series) + commercial ledger.
- `research/rq1-landscape/` — source-tagged industry table.
- `research/h8-attestation/` — verified attestation sweep.
- `paper/` — draft, tables, resolved numbers audit (claim→row hash),
  references, scoping guide, fairness pass.
- `PROVENANCE.md` — registered-prediction commit ordering.

## Reproduce
Recall, leakage, verdicts, and ops_until_gone reproduce exactly from the
pinned seeds (1729/4104); latency re-measures within YOUR fingerprint and
is transport-inclusive (see paper §3.6).

    cd harness/rq9
    docker compose up -d          # pgvector :5433 (shm_size raised), qdrant :6333 (tmpfs)
    pip3 install psycopg2-binary qdrant-client numpy
    export RQ9_PG_DSN='postgresql://rq9:rq9@127.0.0.1:5433/rq9'
    python3 run_commercial.py     # conformance (7a/7b)
    python3 run_scale.py          # N-sweep (1e6 takes ~15 min on 10 cores)
    python3 run_h4_stress.py      # supersession
    python3 run_g3_probe.py       # partitioning gate
    python3 run_g3_qdrant.py      # payload-index probe
    cd ../.. && python3 harness/rq9/audit_numbers.py   # expect 28/28

## License
Apache-2.0 (see LICENSE / NOTICE) — the same license gate this study
applied to the engines it evaluated.
