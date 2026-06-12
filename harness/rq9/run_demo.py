#!/usr/bin/env python3
"""
RQ9 cost-ledger demo. Runs the reference backends end-to-end and emits a real,
source-tagged cost ledger -- the paired table where every correctness verdict
sits next to its price. Runnable with numpy only:

    python run_demo.py

Commercial adapters (adapters/pgvector_adapter.py, adapters/qdrant_adapter.py)
plug into the identical run_all() path when those services are reachable.
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
from gmp_cost import make_corpus, make_queries, fingerprint, run_all, emit
from adapters.reference_adapters import (
    ReferenceHonest, TombstoneHonest, TombstoneLeaky, LeakyTenant)

SEED_CORPUS, SEED_QUERY = 1729, 4104
N, DIM, TENANTS, NQ, K = 4000, 64, 8, 60, 10


def load(backend, corpus):
    backend.write(corpus.records)
    backend.flush()
    return backend


def main():
    corpus = make_corpus(SEED_CORPUS, N, DIM, TENANTS)
    queries = make_queries(SEED_QUERY, NQ, DIM)
    fp = fingerprint(SEED_CORPUS, SEED_QUERY, K)

    backends = [ReferenceHonest, TombstoneHonest, TombstoneLeaky, LeakyTenant]
    all_rows = []
    for B in backends:
        b = load(B(), make_corpus(SEED_CORPUS, N, DIM, TENANTS))  # fresh copy each
        all_rows += run_all(b, corpus, queries, K)

    os.makedirs("out", exist_ok=True)
    emit(all_rows, fp, "out/cost_ledger.csv", "out/cost_ledger.json")
    _print(all_rows, fp)


def _print(rows, fp):
    print("=" * 110)
    print("RQ9 COST LEDGER  (fingerprint: %s | %s cores | k=%d | seeds %d/%d)" % (
        fp["platform"], fp["cpu_cores_physical"], fp["k"],
        fp["seed_corpus"], fp["seed_query"]))
    print("=" * 110)
    hdr = f"{'engine':<16}{'scenario':<24}{'W':<7}{'verdict':<14}" \
          f"{'rec@k':>6}{'leak':>6}{'p50ms':>8}{'ack_ms':>8}{'gone@':>7}{'bytes':>10}"
    print(hdr); print("-" * 110)
    for r in rows:
        rec = "-" if r.recall_at_k is None else f"{r.recall_at_k:.2f}"
        lk = "-" if r.leak_rate is None else f"{r.leak_rate:.2f}"
        p50 = "-" if r.p50_ms is None else f"{r.p50_ms:.2f}"
        ack = "-" if r.delete_ack_ms is None else f"{r.delete_ack_ms:.2f}"
        gone = ("never" if (r.scenario == "delete.honest" and r.ops_until_gone is None)
                else ("-" if r.ops_until_gone is None else str(r.ops_until_gone)))
        by = "-" if r.storage_bytes is None else str(r.storage_bytes)
        print(f"{r.engine:<16}{r.scenario:<24}{r.w_ref:<7}{r.correctness:<14}"
              f"{rec:>6}{lk:>6}{p50:>8}{ack:>8}{gone:>7}{by:>10}")
    print("-" * 110)
    print("All rows are [OBSERVED]. Latency comparable only within this fingerprint;")
    print("recall_at_k / leak / gone@ (ops-until-unretrievable) are hardware-portable.")
    print("Written: out/cost_ledger.csv  out/cost_ledger.json")


if __name__ == "__main__":
    main()
