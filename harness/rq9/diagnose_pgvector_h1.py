#!/usr/bin/env python3
"""
H1 / F-PG-4 diagnostic for pgvector. Two questions, answered deterministically:

  Q1 (plan): which plan does Postgres choose for the tenant-scoped ANN query --
     HNSW index scan (post-filtered) or a non-index plan (exact)? Run-1 vs run-2
     disagreement (scoped recall 1.00 vs 0.21 at ef16) is explained iff the plan
     flips. EXPLAIN ANALYZE settles it. [resolves the F-PG-4 hypothesis]

  Q2 (starvation): with the index FORCED (enable_seqscan=off), how does scoped
     recall scale with ef -- and does pgvector's own mitigation
     (hnsw.iterative_scan, >=0.8) recover it? Post-filter model predicts
     recall ~= min(1, ef * selectivity / k): ef16 -> ~0.2, ef40 -> ~0.5,
     ef64 -> ~0.8, ef128 -> ~1.0 at 1/8 selectivity, k=10. [the H1 probe]

Usage:
    export RQ9_PG_DSN='postgresql://rq9:rq9@127.0.0.1:5433/rq9'
    python3 diagnose_pgvector_h1.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
from gmp_cost import make_corpus, make_queries, exact_knn, in_tenant_rids
from gmp_cost.metrics import recall_at_k
from adapters.pgvector_adapter import PgVectorBackend

SEED_CORPUS, SEED_QUERY = 1729, 4104
N, DIM, TENANTS, K = 4000, 64, 8, 10
EFS = [16, 40, 64, 128]


def vec_literal(v):
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def q1_explain(corpus, query, tenant):
    print("=" * 78)
    print("Q1 -- plan choice for the tenant-scoped ANN query (per ef)")
    print("=" * 78)
    b = PgVectorBackend(dim=DIM, index="hnsw", ef_search=EFS[0])
    b.write(corpus.records); b.flush()
    q = vec_literal(query)
    for ef in EFS:
        with b.conn.cursor() as c:
            c.execute(f"SET hnsw.ef_search = {ef};")
            c.execute(
                "EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF) "
                "SELECT rid FROM rq9_mem WHERE tenant = %s "
                "ORDER BY embedding <=> %s::vector LIMIT %s",
                (tenant, q, K))
            plan = "\n".join(r[0] for r in c.fetchall())
        head = plan.splitlines()[1] if len(plan.splitlines()) > 1 else plan.splitlines()[0]
        uses_index = "Index Scan" in plan and "hnsw" in plan.lower() or "Index Scan" in plan
        rows_removed = [l.strip() for l in plan.splitlines() if "Removed by Filter" in l]
        print(f"\n-- ef={ef}: {'INDEX SCAN (post-filtered)' if uses_index else 'NON-INDEX PLAN (exact)'}")
        print("   " + head.strip())
        for l in rows_removed:
            print("   " + l)
    print("\n(Interpretation: 'Rows Removed by Filter' under an Index Scan node ==")
    print(" candidates fetched from HNSW then discarded by the tenant predicate")
    print(" == post-filtering. A Sort/Seq-Scan plan == the exact path, recall 1.0.)")


def q2_starvation(corpus, queries):
    print("\n" + "=" * 78)
    print("Q2 -- forced-index scoped recall vs ef (H1 probe), +/- iterative_scan")
    print("=" * 78)
    sel = 1.0 / TENANTS
    print(f"post-filter model prediction: recall ~ min(1, ef*{sel:.3f}/{K})\n")
    hdr = f"{'mode':<22}" + "".join(f"{'ef'+str(e):>9}" for e in EFS)
    print(hdr); print("-" * len(hdr))
    for iterative in (None, "relaxed_order"):
        label = "post-filter (default)" if iterative is None else "iterative_scan"
        cells = []
        for ef in EFS:
            b = PgVectorBackend(dim=DIM, index="hnsw", ef_search=ef,
                                force_index=True, iterative_scan=iterative)
            b.write(corpus.records); b.flush()
            recalls = []
            for i, qv in enumerate(queries):
                ten = corpus.tenants[i % TENANTS]
                oracle = exact_knn(corpus, qv, K,
                                   allowed_rids=in_tenant_rids(corpus, ten))
                hits = b.retrieve(qv, K, ten)
                recalls.append(recall_at_k([h.rid for h in hits], oracle, K))
            cells.append(f"{float(np.mean(recalls)):>9.2f}")
        print(f"{label:<22}" + "".join(cells))
    pred = "".join(f"{min(1.0, e*sel/K):>9.2f}" for e in EFS)
    print(f"{'model prediction':<22}{pred}")
    print("\n(If the default row tracks the prediction, H1 under-retrieval is")
    print(" confirmed mechanistically. If iterative_scan recovers recall, the")
    print(" mitigation works -- measure its latency price in the main ledger.)")


def main():
    if not os.environ.get("RQ9_PG_DSN"):
        sys.exit("RQ9_PG_DSN not set")
    corpus = make_corpus(SEED_CORPUS, N, DIM, TENANTS)
    queries = make_queries(SEED_QUERY, 40, DIM)
    q1_explain(corpus, queries[0], corpus.tenants[0])
    q2_starvation(corpus, queries)


if __name__ == "__main__":
    main()
