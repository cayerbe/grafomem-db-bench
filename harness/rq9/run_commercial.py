#!/usr/bin/env python3
"""
RQ9 commercial-engine driver. Runs pgvector -- the RQ7 *control* (already the
GRAFOMEM Cloud backend) -- through the identical cost-ledger path as the
reference anchors, in BOTH deployment postures and across an ef_search sweep:

  7a engine-correct   tenant predicate applied  (API used as documented)
  7b engine-as-deployed  tenant predicate dropped (realistic misconfiguration)

The reference ReferenceHonest anchor is included so the recall-vs-latency frontier
of a real ANN index can be read against the exact-but-slow control on the same
fingerprint. A 7a PASS with a 7b LEAK on the W5 row is the headline RQ7 result.

Run:
    docker compose up -d                       # throwaway pgvector (see compose file)
    pip3 install psycopg2-binary
    export RQ9_PG_DSN='postgresql://rq9:rq9@localhost:5432/rq9'
    python3 run_commercial.py

With no DSN / driver / server reachable it degrades to the reference anchor and
tells you what's missing -- so it always runs.
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
from gmp_cost import make_corpus, make_queries, fingerprint, run_all, emit
from adapters.reference_adapters import ReferenceHonest

SEED_CORPUS, SEED_QUERY = 1729, 4104
N, DIM, TENANTS, NQ, K = 4000, 64, 8, 60, 10
EF_SEARCH_SWEEP = [16, 40, 64, 128]        # trace the recall/latency frontier
HNSW_M, HNSW_EFC = 16, 64


def fresh_corpus():
    return make_corpus(SEED_CORPUS, N, DIM, TENANTS)


def load(backend, corpus):
    backend.write(corpus.records)
    backend.flush()
    return backend


def pgvector_available() -> tuple[bool, str]:
    if not os.environ.get("RQ9_PG_DSN"):
        return False, "RQ9_PG_DSN not set"
    try:
        import psycopg2  # noqa: F401
    except Exception:
        return False, "psycopg2 not installed (pip3 install psycopg2-binary)"
    try:
        import psycopg2
        psycopg2.connect(os.environ["RQ9_PG_DSN"]).close()
    except Exception as e:
        return False, f"cannot connect: {e}"
    return True, "ok"


def qdrant_available() -> tuple[bool, str]:
    try:
        import qdrant_client  # noqa: F401
    except Exception:
        return False, "qdrant-client not installed (pip3 install qdrant-client)"
    import urllib.request
    url = os.environ.get("RQ9_QDRANT_URL", "http://127.0.0.1:6333")
    try:
        urllib.request.urlopen(url, timeout=3).read()
    except Exception as e:
        return False, f"cannot reach {url}: {e}"
    return True, "ok"


def main():
    corpus = fresh_corpus()
    queries = make_queries(SEED_QUERY, NQ, DIM)
    fp = fingerprint(SEED_CORPUS, SEED_QUERY, K)
    rows = []

    # exact control anchor for the frontier comparison
    rows += run_all(load(ReferenceHonest(), fresh_corpus()), corpus, queries, K)

    ok, why = pgvector_available()
    if not ok:
        print(f"[skip] pgvector unavailable: {why}")
        print("       start it with `docker compose up -d` (see docker-compose.yml),")
        print("       `pip3 install psycopg2-binary`, then export RQ9_PG_DSN.")
        print("       Running reference anchor only for now.\n")
    else:
        from adapters.pgvector_adapter import PgVectorBackend
        for ef in EF_SEARCH_SWEEP:
            for deployed in (True, False):     # 7a, then 7b
                b = PgVectorBackend(dim=DIM, index="hnsw", m=HNSW_M,
                                    ef_construction=HNSW_EFC, ef_search=ef,
                                    deployed_correctly=deployed)
                rows += run_all(load(b, fresh_corpus()), corpus, queries, K)

    ok, why = qdrant_available()
    if not ok:
        print(f"[skip] qdrant unavailable: {why}")
        print("       start it with `docker compose up -d` (qdrant service on :6333),")
        print("       `pip3 install qdrant-client`.\n")
    else:
        from adapters.qdrant_adapter import QdrantBackend
        for ef in EF_SEARCH_SWEEP:
            for deployed in (True, False):     # 7a, then 7b
                b = QdrantBackend(dim=DIM, m=HNSW_M, ef_construct=HNSW_EFC,
                                  hnsw_ef=ef, deployed_correctly=deployed)
                rows += run_all(load(b, fresh_corpus()), corpus, queries, K)

    os.makedirs("out", exist_ok=True)
    emit(rows, fp, "out/commercial_ledger.csv", "out/commercial_ledger.json")
    _print(rows, fp)


def _tag(cfg: str) -> str:
    """Compact label from index_config: ef + 7a/7b, or '-' for the anchor."""
    parts = dict(p.split("=", 1) for p in cfg.split(",") if "=" in p)
    ef = parts.get("ef_search") or parts.get("hnsw_ef")
    if ef is None:
        return "exact"
    dep = "7a" if parts.get("deployed", "").startswith("7a") else "7b"
    tag = f"ef{ef}/{dep}"
    if "indexed" in parts:                    # adapter reports which path ran
        n = parts["indexed"]
        tag += "/ann" if (n not in ("0", "None") and n) else "/PLAIN"
    return tag


def _print(rows, fp):
    print("=" * 116)
    print("RQ9 COMMERCIAL LEDGER  (fingerprint: %s | %s cores | k=%d | seeds %d/%d)" % (
        fp["platform"], fp["cpu_cores_physical"], fp["k"],
        fp["seed_corpus"], fp["seed_query"]))
    print("=" * 116)
    hdr = (f"{'engine':<16}{'cfg':<15}{'scenario':<24}{'W':<7}{'verdict':<14}"
           f"{'rec@k':>6}{'leak':>6}{'p50ms':>8}{'gone@':>7}{'bytes':>10}")
    print(hdr); print("-" * 116)
    for r in rows:
        rec = "-" if r.recall_at_k is None else f"{r.recall_at_k:.2f}"
        lk = "-" if r.leak_rate is None else f"{r.leak_rate:.2f}"
        p50 = "-" if r.p50_ms is None else f"{r.p50_ms:.2f}"
        gone = ("never" if (r.scenario == "delete.honest" and r.ops_until_gone is None)
                else ("-" if r.ops_until_gone is None else str(r.ops_until_gone)))
        by = "-" if r.storage_bytes is None else str(r.storage_bytes)
        print(f"{r.engine:<16}{_tag(r.index_config):<15}{r.scenario:<24}{r.w_ref:<7}"
              f"{r.correctness:<14}{rec:>6}{lk:>6}{p50:>8}{gone:>7}{by:>10}")
    print("-" * 116)
    print("All rows [OBSERVED]. Read pgvector as a recall/latency FRONTIER across ef;")
    print("compare engines at matched recall, never single points. 7a-PASS + 7b-LEAK")
    print("on the W5 row == guarantee exists but is opt-in and silently defeatable.")
    print("Written: out/commercial_ledger.csv  out/commercial_ledger.json")


if __name__ == "__main__":
    main()
