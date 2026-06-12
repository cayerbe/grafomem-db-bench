#!/usr/bin/env python3
"""
H4-stress driver (slot [H4-STRESS]) -- what as_of costs under supersession.

Sweep: depth D in {1, 4, 16} (physical rows = N_LOGICAL * D), four variants
(pgvector, pgvector-iter, qdrant, qdrant-forced), ef in {16, 64, 256}.
Two probes per (variant, D, ef):

  retrieve.as_of_mid     as_of t = mid-history -> exactly one version per chain
                         valid; temporal selectivity = 1/D; stale versions are
                         near-duplicate neighbours (adversarial by design)
  retrieve.as_of_now     as_of t = "current" -> the open-interval (sentinel)
                         version per chain; same 1/D selectivity, tests the
                         valid_until = T_OPEN path specifically

Registered predictions (state before running):
  P1  pgvector post-filter as_of recall ~ min(1, ef/(D*k)) when the ANN plan is
      chosen; iterative_scan recovers partially at multiplied latency (H1 shape).
  P2  qdrant default: per-segment cardinality fallback -> 1.00 flat while the
      valid-set payload is below full_scan_threshold; forced: graceful HNSW
      degradation, well above pgvector at matched ef.
  P3  storage grows ~linearly in D (the bi-temporal tax of version-as-row).
  P4  leak 0.00 on every correctly-driven row (predicates enforce validity) --
      the COST of temporal correctness, not its violation, is the finding.

Checkpoint: out/h4_rows.jsonl (delete to restart). Canonical out/h4_ledger.{csv,json}.
"""
import os, sys, json, time
from dataclasses import asdict
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
from gmp_cost.protocol import LedgerRow
from gmp_cost.h4_stress import (make_chain_corpus, exact_asof_topk,
                                temporal_leak, EPOCH)
from gmp_cost.oracle import make_queries
from gmp_cost.metrics import percentiles, recall_at_k, measure_calls
from gmp_cost.harness import fingerprint, _verdict
from gmp_cost.protocol import T_OPEN

SEED_CORPUS, SEED_QUERY = 1729, 4104
N_LOGICAL, DIM, NQ, K = 20_000, 64, 30, 10
DEPTHS = [int(x) for x in os.environ.get("RQ9_H4_DEPTHS", "1,4,16").split(",")]
EFS = [16, 64, 256]
CKPT = "out/h4_rows.jsonl"


def _pg(**kw):
    from adapters.pgvector_adapter import PgVectorBackend
    return PgVectorBackend(dim=DIM, index="hnsw", m=16, ef_construction=64,
                           ef_search=EFS[0], defer_index=True,
                           deployed_correctly=True, **kw)

def _qd(**kw):
    from adapters.qdrant_adapter import QdrantBackend
    return QdrantBackend(dim=DIM, m=16, ef_construct=64, hnsw_ef=EFS[0],
                         deployed_correctly=True, **kw)

VARIANTS = [
    ("pgvector",      lambda: _pg()),
    ("pgvector-iter", lambda: _pg(iterative_scan="relaxed_order")),
    ("qdrant",        lambda: _qd()),
    ("qdrant-forced", lambda: _qd(full_scan_threshold=10)),
]


def pg_ok():
    if not os.environ.get("RQ9_PG_DSN"):
        return False, "RQ9_PG_DSN not set"
    try:
        import psycopg2; psycopg2.connect(os.environ["RQ9_PG_DSN"]).close()
        return True, "ok"
    except Exception as e:
        return False, str(e)

def qd_ok():
    url = os.environ.get("RQ9_QDRANT_URL", "http://127.0.0.1:6333")
    if url == ":memory:":
        return True, "local-mode (plumbing only)"
    try:
        import urllib.request; urllib.request.urlopen(url, timeout=3).read()
        return True, "ok"
    except Exception as e:
        return False, str(e)


def set_ef(b, ef):
    if "ef_search" in b.index_config:
        b.index_config["ef_search"] = ef
    if hasattr(b, "hnsw_ef"):
        b.hnsw_ef = ef
        b.index_config["hnsw_ef"] = ef


def cfg_str(b, D):
    d = dict(b.index_config); d["D"] = D; d["Nlog"] = N_LOGICAL
    return ",".join(f"{k}={v}" for k, v in d.items())


def run_asof(b, corpus, queries, D, ef, t, label):
    payloads = [(q, K, None, t) for q in queries]
    lat, outs = measure_calls(b.retrieve, payloads)
    recs, leaks = [], []
    for q, hits in zip(queries, outs):
        ids = [h.rid for h in hits]
        recs.append(recall_at_k(ids, exact_asof_topk(corpus, q, K, t), K))
        leaks.append(temporal_leak(corpus, ids, t))
    L = percentiles(lat)
    rec, lk = float(np.mean(recs)), float(np.mean(leaks))
    return LedgerRow(b.name, b.version, cfg_str(b, D), label, "H4/RQ4",
                     _verdict(rec, lk), rec, lk, L.p50, L.p95, L.p99, L.mx,
                     None, None, None, None, None,
                     notes=f"ef={ef} D={D} t={t} sel=1/{D}")


def main():
    os.makedirs("out", exist_ok=True)
    fp = fingerprint(SEED_CORPUS, SEED_QUERY, K)
    fp["h4_params"] = {"n_logical": N_LOGICAL, "dim": DIM,
                       "depths": DEPTHS, "efs": EFS, "epoch": EPOCH}
    avail = {"pg": pg_ok(), "qd": qd_ok()}
    for k_, (ok, why) in avail.items():
        if not ok:
            print(f"[skip] {k_}: {why}")
    done = set()
    if os.path.exists(CKPT):
        with open(CKPT) as f:
            for line in f:
                try:
                    done.add(json.loads(line)["_unit"])
                except Exception:
                    pass
        if done:
            print(f"[resume] {len(done)} unit(s)")

    queries = make_queries(SEED_QUERY, NQ, DIM)
    for D in DEPTHS:
        corpus = None
        t_mid = (max(D // 2, 1) * EPOCH) - EPOCH // 2   # mid-history instant
        t_now = (D - 1) * EPOCH + EPOCH // 2            # inside the open epoch
        for vname, factory in VARIANTS:
            if vname.startswith("pg") and not avail["pg"][0]:
                continue
            if vname.startswith("qd") and not avail["qd"][0]:
                continue
            unit = f"{vname}|D={D}"
            if unit in done:
                print(f"[skip-done] {unit}")
                continue
            if corpus is None:
                print(f"[corpus] D={D}: {N_LOGICAL:,} chains x {D} = "
                      f"{N_LOGICAL*D:,} physical rows ...")
                corpus = make_chain_corpus(SEED_CORPUS, N_LOGICAL, D, DIM)
            print(f"[run] {unit}")
            b = factory(); b.name = vname
            t0 = time.perf_counter()
            for batch in corpus.records_batches(2000):
                b.write(batch)
            b.flush()
            secs = time.perf_counter() - t0
            rows = [LedgerRow(b.name, b.version, cfg_str(b, D), "ingest.build",
                              "-", "N/A", None, None, None, None, None, None,
                              (N_LOGICAL * D) / secs, b.storage_bytes(),
                              None, None, None,
                              notes=f"D={D}; {secs:.1f}s; physical={N_LOGICAL*D}")]
            print(f"       build {secs:.1f}s")
            for ef in EFS:
                set_ef(b, ef)
                r1 = run_asof(b, corpus, queries, D, ef, t_mid, "retrieve.as_of_mid")
                r2 = run_asof(b, corpus, queries, D, ef, t_now, "retrieve.as_of_now")
                rows += [r1, r2]
                print(f"       ef={ef}: mid rec={r1.recall_at_k:.2f} "
                      f"leak={r1.leak_rate:.2f} | now rec={r2.recall_at_k:.2f} "
                      f"leak={r2.leak_rate:.2f} (p50 {r1.p50_ms:.1f}ms)")
            with open(CKPT, "a") as f:
                for r in rows:
                    d = asdict(r); d["_unit"] = unit
                    f.write(json.dumps(d) + "\n")
            print(f"       checkpointed {len(rows)} rows")
        corpus = None

    _emit(fp)


def _emit(fp):
    rows = [json.loads(l) for l in open(CKPT)]
    with open("out/h4_ledger.json", "w") as f:
        json.dump({"fingerprint": fp, "ledger": rows}, f, indent=2)
    import csv
    cols = ["engine", "index_config", "scenario", "w_ref", "correctness",
            "recall_at_k", "leak_rate", "p50_ms", "p95_ms",
            "throughput_ops_s", "storage_bytes", "source_class", "notes"]
    with open("out/h4_ledger.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print("\n%-15s%-4s%-22s%-4s%-10s%6s%6s%9s%14s" % (
        "engine", "D", "scenario", "ef", "verdict", "rec", "leak", "p50ms", "store/rate"))
    print("-" * 96)
    for r in rows:
        cfgp = dict(p.split("=", 1) for p in r["index_config"].split(",") if "=" in p)
        ef = (r.get("notes") or "").split("ef=")[-1].split(" ")[0] \
            if "ef=" in (r.get("notes") or "") else "-"
        rec = "-" if r["recall_at_k"] is None else f"{r['recall_at_k']:.2f}"
        lk = "-" if r["leak_rate"] is None else f"{r['leak_rate']:.2f}"
        p50 = "-" if r["p50_ms"] is None else f"{r['p50_ms']:.1f}"
        tail = f"{r['throughput_ops_s']:,.0f}/s" if r.get("throughput_ops_s") else \
            (f"{r['storage_bytes']:,}B" if r.get("storage_bytes") else "")
        print("%-15s%-4s%-22s%-4s%-10s%6s%6s%9s%14s" % (
            r["engine"], cfgp.get("D", "-"), r["scenario"], ef,
            r["correctness"], rec, lk, p50, tail))
    print("\nCanonical: out/h4_ledger.{csv,json}")


if __name__ == "__main__":
    main()
