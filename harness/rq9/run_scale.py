#!/usr/bin/env python3
"""
RQ9 N-sweep (run_scale.py) -- the scale-gated questions, one instrument:

  * real recall/latency frontier (ANN's reason to exist is invisible at n=4k)
  * iterative_scan's price (pgvector's H1 mitigation: recall recovery vs latency)
  * Qdrant mechanism split (default planner vs full_scan_threshold=1, which
    forces filtered queries through the HNSW graph -- F-QD-3's open question)
  * index build time + storage amplification vs N (RQ6 corner inputs)
  * W6 delete-to-unretrievable on large indexes

Variants (each x each N, ef swept WITHIN one build -- ef is query-time):
  pgvector            post-filter default (7a only; 7b is established + scale-invariant)
  pgvector-iter       hnsw.iterative_scan=relaxed_order
  qdrant              engine's own filtered-search planner
  qdrant-forced       full_scan_threshold=1 (graph traversal forced)

Checkpointing: each completed (variant, N) appends its rows to
out/scale_rows.jsonl and is skipped on rerun. Delete out/scale_rows.jsonl to
start fresh. Final table + CSV/JSON regenerated from the checkpoint each run.

Env:
  RQ9_PG_DSN          postgresql://rq9:rq9@127.0.0.1:5433/rq9
  RQ9_QDRANT_URL      http://127.0.0.1:6333   (":memory:" = plumbing test only)
  RQ9_SCALE_NS        comma list, default "20000,100000" (add 1000000 deliberately)
  RQ9_QDRANT_GREEN_TIMEOUT  seconds to wait for optimizer green (default 120;
                            set ~1800 for 1e6)
Expect minutes per pgvector build at 1e5 and tens of minutes at 1e6 -- the build
time is not overhead, it is a measured price (ingest.build rows).
"""
import os, sys, json, time
from dataclasses import asdict
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
from gmp_cost.protocol import LedgerRow
from gmp_cost.scale import (make_scale_corpus, exact_topk, out_of_tenant,
                            rid_of, idx_of)
from gmp_cost.metrics import percentiles, recall_at_k, measure_calls, timed
from gmp_cost.harness import fingerprint, _verdict

SEED_CORPUS, SEED_QUERY = 1729, 4104
DIM, TENANTS, NQ, K = 64, 64, 30, 10          # 1/64 selectivity forces the issue
EFS = [16, 64, 256]
DELETE_EF = 64
NS = [int(x) for x in os.environ.get("RQ9_SCALE_NS", "20000,100000").split(",")]
CKPT = "out/scale_rows.jsonl"


# ---------------------------------------------------------------- variants
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
    ("pgvector",       lambda: _pg()),
    ("pgvector-iter",  lambda: _pg(iterative_scan="relaxed_order")),
    ("qdrant",         lambda: _qd()),
    # Qdrant enforces a 10 KB floor on full_scan_threshold (server-validated).
    # 10 still forces traversal at our selectivities: per-tenant payload is
    # ~80 KB at N=20k and ~400 KB at 100k, both > 10; the engine DEFAULT is
    # 10,000 KB, under which the same queries take the exact fallback.
    ("qdrant-forced",  lambda: _qd(full_scan_threshold=10)),
]


def pg_ok():
    if not os.environ.get("RQ9_PG_DSN"):
        return False, "RQ9_PG_DSN not set"
    try:
        import psycopg2
        psycopg2.connect(os.environ["RQ9_PG_DSN"]).close()
        return True, "ok"
    except Exception as e:
        return False, str(e)

def qd_ok():
    url = os.environ.get("RQ9_QDRANT_URL", "http://127.0.0.1:6333")
    if url == ":memory:":
        return True, "local-mode (plumbing test only)"
    try:
        import urllib.request
        urllib.request.urlopen(url, timeout=3).read()
        return True, "ok"
    except Exception as e:
        return False, str(e)


def set_ef(b, ef):
    if "ef_search" in b.index_config:
        b.index_config["ef_search"] = ef
    if hasattr(b, "hnsw_ef"):
        b.hnsw_ef = ef
        b.index_config["hnsw_ef"] = ef


def cfg_str(b, N):
    d = dict(b.index_config); d["N"] = N
    return ",".join(f"{k}={v}" for k, v in d.items())


# ---------------------------------------------------------------- scenarios
def load_and_price(b, corpus, N):
    t0 = time.perf_counter()
    for batch in corpus.records_batches(2000):
        b.write(batch)
    b.flush()                      # builds deferred index / waits for green
    secs = time.perf_counter() - t0
    return secs, LedgerRow(b.name, b.version, cfg_str(b, N), "ingest.build", "-",
                           "N/A", None, None, None, None, None, None,
                           N / secs, b.storage_bytes(), None, None, None,
                           notes=f"bulk load + index build = {secs:.1f}s "
                                 f"({N/secs:,.0f} vec/s)")


def run_unfiltered(b, corpus, queries, N, ef):
    payloads = [(q, K, None, None) for q in queries]
    lat, outs = measure_calls(b.retrieve, payloads)
    recs = [recall_at_k([h.rid for h in hits], exact_topk(corpus, q, K), K)
            for q, hits in zip(queries, outs)]
    L = percentiles(lat); rec = float(np.mean(recs))
    return LedgerRow(b.name, b.version, cfg_str(b, N), "retrieve.unfiltered", "-",
                     "PASS" if rec >= 0.999 else "PARTIAL", rec, None,
                     L.p50, L.p95, L.p99, L.mx, None, None, None, None, None,
                     notes=f"ef={ef}")


def run_scoped(b, corpus, queries, N, ef):
    payloads, oracles, tens = [], [], []
    for i, q in enumerate(queries):
        t = i % TENANTS
        tens.append(t)
        payloads.append((q, K, corpus.tenant_name(t), None))
        oracles.append(exact_topk(corpus, q, K, tenant=t))
    lat, outs = measure_calls(b.retrieve, payloads)
    recs, leaks = [], []
    for hits, orc, t in zip(outs, oracles, tens):
        ids = [h.rid for h in hits]
        recs.append(recall_at_k(ids, orc, K))
        leaks.append(out_of_tenant(corpus, ids, t))
    L = percentiles(lat)
    rec, lk = float(np.mean(recs)), float(np.mean(leaks))
    return LedgerRow(b.name, b.version, cfg_str(b, N), "retrieve.tenant_scoped",
                     "W5/H1", _verdict(rec, lk), rec, lk,
                     L.p50, L.p95, L.p99, L.mx, None, None, None, None, None,
                     notes=f"ef={ef} selectivity=1/{TENANTS}")


def run_delete(b, corpus, queries, N):
    from gmp_cost.metrics import delete_unretrievable
    t = 0
    probe = queries[0]
    pre = exact_topk(corpus, probe, K, tenant=t)
    dele = pre[: max(1, K // 2)]
    del_idx = np.array([idx_of(r) for r in dele])
    (_, ack_ms) = timed(b.delete, dele)
    b.flush()
    hits = b.retrieve(probe, K, corpus.tenant_name(t))
    got = [h.rid for h in hits]
    lk = sum(1 for r in got if r in set(dele)) / len(got) if got else 0.0
    du = delete_unretrievable(b, set(dele), probe, corpus.tenant_name(t), K)
    post = exact_topk(corpus, probe, K, tenant=t, excluded_idx=del_idx)
    rec = recall_at_k(got, post, K)
    verdict = "LEAKS" if lk > 0 else ("PASS" if du["gone"] else "LEAKS")
    return LedgerRow(b.name, b.version, cfg_str(b, N), "delete.honest", "W6",
                     verdict, rec, lk, None, None, None, None, None,
                     b.storage_bytes(), ack_ms,
                     du["walltime_ms"] if du["gone"] else None,
                     du["ops_until_gone"],
                     notes=f"ef={DELETE_EF}; ack={ack_ms:.1f}ms; "
                           f"gone@{du['ops_until_gone']}" if du["gone"] else
                           f"ef={DELETE_EF}; STILL RANKABLE")


def oracle_anchor(corpus, queries, N):
    lat, _ = measure_calls(lambda q: exact_topk(corpus, q, K),
                           [(q,) for q in queries])
    L = percentiles(lat)
    return LedgerRow("oracle-exact", "-", f"N={N}", "retrieve.unfiltered", "-",
                     "PASS", 1.0, None, L.p50, L.p95, L.p99, L.mx,
                     None, corpus.matrix.nbytes, None, None, None,
                     notes="vectorized exact baseline (in-process)")


# ---------------------------------------------------------------- driver
def done_keys():
    if not os.path.exists(CKPT):
        return set()
    keys = set()
    with open(CKPT) as f:
        for line in f:
            try:
                keys.add(json.loads(line)["_unit"])
            except Exception:
                pass
    return keys


def append_rows(unit, rows):
    with open(CKPT, "a") as f:
        for r in rows:
            d = asdict(r); d["_unit"] = unit
            f.write(json.dumps(d) + "\n")


def main():
    os.makedirs("out", exist_ok=True)
    fp = fingerprint(SEED_CORPUS, SEED_QUERY, K)
    fp["scale_params"] = {"dim": DIM, "tenants": TENANTS, "efs": EFS, "Ns": NS}
    avail = {"pg": pg_ok(), "qd": qd_ok()}
    for k, (ok, why) in avail.items():
        if not ok:
            print(f"[skip] {k}: {why}")
    done = done_keys()
    if done:
        print(f"[resume] {len(done)} completed unit(s) in {CKPT}")

    queries_cache = {}
    for N in NS:
        corpus = None
        for vname, factory in VARIANTS:
            if vname.startswith("pg") and not avail["pg"][0]:
                continue
            if vname.startswith("qd") and not avail["qd"][0]:
                continue
            unit = f"{vname}|N={N}"
            if unit in done:
                print(f"[skip-done] {unit}")
                continue
            if corpus is None:
                print(f"[corpus] generating N={N:,} ...")
                corpus = make_scale_corpus(SEED_CORPUS, N, DIM, TENANTS)
                from gmp_cost.oracle import make_queries
                queries_cache[N] = make_queries(SEED_QUERY, NQ, DIM)
                append_rows(f"oracle|N={N}",
                            [oracle_anchor(corpus, queries_cache[N], N)]) \
                    if f"oracle|N={N}" not in done else None
            queries = queries_cache[N]
            print(f"[run] {unit}")
            b = factory()
            b.name = vname                       # variant label in the ledger
            rows = []
            secs, build_row = load_and_price(b, corpus, N)
            rows.append(build_row)
            print(f"       build {secs:.1f}s")
            for ef in EFS:
                set_ef(b, ef)
                rows.append(run_unfiltered(b, corpus, queries, N, ef))
                rows.append(run_scoped(b, corpus, queries, N, ef))
                print(f"       ef={ef}: unf={rows[-2].recall_at_k:.2f} "
                      f"scoped={rows[-1].recall_at_k:.2f} "
                      f"(p50 {rows[-1].p50_ms:.1f}ms)")
            set_ef(b, DELETE_EF)
            rows.append(run_delete(b, corpus, queries, N))
            append_rows(unit, rows)
            print(f"       checkpointed {len(rows)} rows")
        # free before next N
        corpus = None

    _emit_and_print(fp)


def _emit_and_print(fp):
    rows = []
    with open(CKPT) as f:
        for line in f:
            rows.append(json.loads(line))
    with open("out/scale_ledger.json", "w") as f:
        json.dump({"fingerprint": fp, "ledger": rows}, f, indent=2)
    import csv
    cols = ["engine", "index_config", "scenario", "w_ref", "correctness",
            "recall_at_k", "leak_rate", "p50_ms", "p95_ms",
            "throughput_ops_s", "delete_ack_ms", "ops_until_gone",
            "storage_bytes", "source_class", "notes"]
    with open("out/scale_ledger.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    print("\n" + "=" * 118)
    print("RQ9 SCALE LEDGER  (%s | k=%d | dim=%d | tenants=%d | sel=1/%d)" %
          (fp["platform"], K, DIM, TENANTS, TENANTS))
    print("=" * 118)
    hdr = (f"{'engine':<16}{'N':>9} {'scenario':<24}{'ef':>5}{'verdict':<10}"
           f"{'rec@k':>6}{'leak':>6}{'p50ms':>9}{'gone@':>7}{'build/store':>22}")
    print(hdr); print("-" * 118)
    for r in rows:
        cfgp = dict(p.split("=", 1) for p in r["index_config"].split(",") if "=" in p)
        Nv = cfgp.get("N", "-")
        ef = (r.get("notes") or "").split("ef=")[-1].split(" ")[0].split(";")[0] \
            if "ef=" in (r.get("notes") or "") else "-"
        rec = "-" if r["recall_at_k"] is None else f"{r['recall_at_k']:.2f}"
        lk = "-" if r["leak_rate"] is None else f"{r['leak_rate']:.2f}"
        p50 = "-" if r["p50_ms"] is None else f"{r['p50_ms']:.2f}"
        gone = str(r["ops_until_gone"]) if r["ops_until_gone"] else \
            ("never" if r["scenario"] == "delete.honest" and r["correctness"] == "LEAKS" else "-")
        tail = ""
        if r["scenario"] == "ingest.build" and r["throughput_ops_s"]:
            tail = f"{r['throughput_ops_s']:,.0f} vec/s"
        elif r["storage_bytes"]:
            tail = f"{r['storage_bytes']:,} B"
        print(f"{r['engine']:<16}{Nv:>9} {r['scenario']:<24}{ef:>5}"
              f"{r['correctness']:<10}{rec:>6}{lk:>6}{p50:>9}{gone:>7}{tail:>22}")
    print("-" * 118)
    print("Checkpoint: out/scale_rows.jsonl (delete to restart). "
          "Canonical: out/scale_ledger.{csv,json}")


if __name__ == "__main__":
    main()
