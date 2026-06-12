#!/usr/bin/env python3
"""
G3 gating probe (run_g3_probe.py) -- the experiment that decides between RQ8
outcomes (c) and (b).

Same corpus, probes, seeds, and ef sweep as run_h4_stress.py, one new variant:
pg-partitioned (epoch tables + sentinel current-snapshot, adapter-side routing;
see adapters/pg_partitioned_adapter.py for the registered gate GP1-GP3).

H4 monolithic baselines to beat (from h4_ledger, same fingerprint family):
  pgvector  D=16  as_of recall 0.04/0.12/0.31 @ ~1-2 ms     (fast, wrong)
  qdrant    D=16  as_of recall 1.00 flat      @ 64-84 ms    (right, linear-in-D)
  D=1 graph baseline (the partitioned ideal): 0.42/0.75/0.99 @ ~1-2 ms

Gate: GP1 (recall ~= D=1 baseline, independent of D) AND GP2 (p50 ~flat in D
at ~1-2 ms) holding at D=16 => G3 closes at the adapter layer => (c).
Either failing => first load-bearing engine-native gap => (b) opens.

Run:
    export RQ9_PG_DSN='postgresql://rq9:rq9@127.0.0.1:5433/rq9'
    python3 run_g3_probe.py
Checkpoint: out/g3_rows.jsonl. Canonical: out/g3_ledger.{csv,json}.
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

SEED_CORPUS, SEED_QUERY = 1729, 4104
N_LOGICAL, DIM, NQ, K = 20_000, 64, 30, 10
DEPTHS = [int(x) for x in os.environ.get("RQ9_G3_DEPTHS", "1,4,16").split(",")]
EFS = [16, 64, 256]
CKPT = "out/g3_rows.jsonl"


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
    return LedgerRow(b.name, b.version, cfg_str(b, D), label, "G3-probe",
                     _verdict(rec, lk), rec, lk, L.p50, L.p95, L.p99, L.mx,
                     None, None, None, None, None,
                     notes=f"ef={ef} D={D} t={t}")


def main():
    os.makedirs("out", exist_ok=True)
    if not os.environ.get("RQ9_PG_DSN"):
        sys.exit("RQ9_PG_DSN not set (this probe targets pgvector)")
    try:
        import psycopg2; psycopg2.connect(os.environ["RQ9_PG_DSN"]).close()
    except Exception as e:
        sys.exit(f"cannot connect: {e}")

    from adapters.pg_partitioned_adapter import PgPartitionedBackend
    fp = fingerprint(SEED_CORPUS, SEED_QUERY, K)
    fp["g3_params"] = {"n_logical": N_LOGICAL, "dim": DIM,
                       "depths": DEPTHS, "efs": EFS, "epoch": EPOCH}
    done = set()
    if os.path.exists(CKPT):
        for line in open(CKPT):
            try:
                done.add(json.loads(line)["_unit"])
            except Exception:
                pass
        if done:
            print(f"[resume] {len(done)} unit(s)")

    queries = make_queries(SEED_QUERY, NQ, DIM)
    for D in DEPTHS:
        unit = f"pg-partitioned|D={D}"
        if unit in done:
            print(f"[skip-done] {unit}")
            continue
        print(f"[corpus] D={D}: {N_LOGICAL:,} x {D} = {N_LOGICAL*D:,} physical ...")
        corpus = make_chain_corpus(SEED_CORPUS, N_LOGICAL, D, DIM)
        t_mid = (max(D // 2, 1) * EPOCH) - EPOCH // 2
        t_now = (D - 1) * EPOCH + EPOCH // 2
        print(f"[run] {unit}")
        b = PgPartitionedBackend(dim=DIM, max_epoch=D - 1,
                                 ef_search=EFS[0])
        t0 = time.perf_counter()
        for batch in corpus.records_batches(2000):
            b.write(batch)
        b.flush()
        secs = time.perf_counter() - t0
        rows = [LedgerRow(b.name, b.version, cfg_str(b, D), "ingest.build", "-",
                          "N/A", None, None, None, None, None, None,
                          (N_LOGICAL * D) / secs, b.storage_bytes(),
                          None, None, None,
                          notes=f"D={D}; {secs:.1f}s; {D+1} HNSW indexes; "
                                f"placement+cur tax in storage_bytes")]
        print(f"       build {secs:.1f}s ({D+1} indexes) | "
              f"storage {b.storage_bytes():,} B")
        for ef in EFS:
            b.index_config["ef_search"] = ef
            r1 = run_asof(b, corpus, queries, D, ef, t_mid, "retrieve.as_of_mid")
            r2 = run_asof(b, corpus, queries, D, ef, t_now, "retrieve.as_of_now")
            rows += [r1, r2]
            print(f"       ef={ef}: mid rec={r1.recall_at_k:.2f} "
                  f"leak={r1.leak_rate:.2f} p50={r1.p50_ms:.1f}ms | "
                  f"now rec={r2.recall_at_k:.2f} leak={r2.leak_rate:.2f} "
                  f"p50={r2.p50_ms:.1f}ms")
        with open(CKPT, "a") as f:
            for r in rows:
                d = asdict(r); d["_unit"] = unit
                f.write(json.dumps(d) + "\n")
        print(f"       checkpointed {len(rows)} rows")

    _emit(fp)


def _emit(fp):
    rows = [json.loads(l) for l in open(CKPT)]
    with open("out/g3_ledger.json", "w") as f:
        json.dump({"fingerprint": fp, "ledger": rows}, f, indent=2)
    import csv
    cols = ["engine", "index_config", "scenario", "w_ref", "correctness",
            "recall_at_k", "leak_rate", "p50_ms", "p95_ms",
            "throughput_ops_s", "storage_bytes", "source_class", "notes"]
    with open("out/g3_ledger.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print("\nGATE CHECK (registered criteria, decide against these numbers):")
    print("  GP1: D=16 as_of recall ~= D=1 baseline 0.42/0.75/0.99 (ef 16/64/256)?")
    print("       (H4 monolithic pgvector D=16 was 0.04/0.12/0.31)")
    print("  GP2: D=16 p50 ~= D=1 p50 (~1-2ms)?  (qdrant fallback was 64-84ms)")
    print("  GP3: storage tax modest (+~1/D placement) vs monolithic?")
    print("  GP1+GP2 hold => G3 closes at the adapter layer => RQ8 outcome (c)")
    print("  either fails => first load-bearing engine-native gap => (b) opens")
    print("Canonical: out/g3_ledger.{csv,json}")


if __name__ == "__main__":
    main()
