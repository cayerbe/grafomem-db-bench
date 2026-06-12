#!/usr/bin/env python3
"""
Qdrant Q2 probe (run_g3_qdrant.py) -- decides the backend question with
evidence. Same chain corpus / probes / seeds as run_h4_stress.py; two variants:

  qdrant-rangeidx     monolithic + integer payload indexes on the validity
                      fields. QP0: was H4's 64-84 ms exactness largely an
                      UNINDEXED-range-filter confound? If this alone reaches
                      ~2 ms flat, partitioning is unnecessary on Qdrant and the
                      H4 qdrant cost rows carry a confound flag.
  qdrant-partitioned  collection-per-epoch + cur (adapter routing). QP1: recall
                      ~= D=1 baseline, D-independent (expected 1.00 flat: each
                      epoch collection sits under the full-scan threshold ->
                      exact per epoch). QP2: p50 flat ~1-3 ms.

Baselines to beat (same fingerprint family):
  h4: qdrant monolithic D=16 -> 1.00 @ 64-84 ms (validity fields UNindexed)
  g3: pg-partitioned   D=16 -> 0.97 @ 1.8 ms

Run:
    docker compose up -d   # qdrant on 127.0.0.1:6333
    python3 run_g3_qdrant.py
Checkpoint: out/g3q_rows.jsonl. Canonical: out/g3q_ledger.{csv,json}.
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
DEPTHS = [int(x) for x in os.environ.get("RQ9_G3Q_DEPTHS", "1,4,16").split(",")]
EFS = [16, 64, 256]
CKPT = "out/g3q_rows.jsonl"


def variants():
    from adapters.qdrant_adapter import QdrantBackend
    from adapters.qdrant_partitioned_adapter import QdrantPartitionedBackend
    def rangeidx(D):
        return QdrantBackend(dim=DIM, m=16, ef_construct=64, hnsw_ef=EFS[0],
                             deployed_correctly=True, index_validity=True)
    def partitioned(D):
        return QdrantPartitionedBackend(dim=DIM, max_epoch=D - 1,
                                        m=16, ef_construct=64, hnsw_ef=EFS[0])
    return [("qdrant-rangeidx", rangeidx), ("qdrant-partitioned", partitioned)]


def qd_ok():
    url = os.environ.get("RQ9_QDRANT_URL", "http://127.0.0.1:6333")
    if url == ":memory:":
        return True, "local-mode (plumbing only)"
    try:
        import urllib.request
        urllib.request.urlopen(url, timeout=3).read()
        return True, "ok"
    except Exception as e:
        return False, str(e)


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
    return LedgerRow(b.name, b.version, cfg_str(b, D), label, "G3q-probe",
                     _verdict(rec, lk), rec, lk, L.p50, L.p95, L.p99, L.mx,
                     None, None, None, None, None,
                     notes=f"ef={ef} D={D} t={t}")


def set_ef(b, ef):
    b.hnsw_ef = ef
    b.index_config["hnsw_ef"] = ef


def main():
    os.makedirs("out", exist_ok=True)
    ok, why = qd_ok()
    if not ok:
        sys.exit(f"qdrant unavailable: {why}")
    fp = fingerprint(SEED_CORPUS, SEED_QUERY, K)
    fp["g3q_params"] = {"n_logical": N_LOGICAL, "dim": DIM,
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
        corpus = None
        t_mid = (max(D // 2, 1) * EPOCH) - EPOCH // 2
        t_now = (D - 1) * EPOCH + EPOCH // 2
        for vname, factory in variants():
            unit = f"{vname}|D={D}"
            if unit in done:
                print(f"[skip-done] {unit}")
                continue
            if corpus is None:
                print(f"[corpus] D={D}: {N_LOGICAL:,} x {D} = "
                      f"{N_LOGICAL*D:,} physical ...")
                corpus = make_chain_corpus(SEED_CORPUS, N_LOGICAL, D, DIM)
            print(f"[run] {unit}")
            b = factory(D); b.name = vname
            t0 = time.perf_counter()
            for batch in corpus.records_batches(2000):
                b.write(batch)
            b.flush()
            secs = time.perf_counter() - t0
            rows = [LedgerRow(b.name, b.version, cfg_str(b, D), "ingest.build",
                              "-", "N/A", None, None, None, None, None, None,
                              (N_LOGICAL * D) / secs, b.storage_bytes(),
                              None, None, None,
                              notes=f"D={D}; {secs:.1f}s")]
            print(f"       build {secs:.1f}s | est. storage "
                  f"{b.storage_bytes():,} B")
            for ef in EFS:
                set_ef(b, ef)
                r1 = run_asof(b, corpus, queries, D, ef, t_mid,
                              "retrieve.as_of_mid")
                r2 = run_asof(b, corpus, queries, D, ef, t_now,
                              "retrieve.as_of_now")
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
        corpus = None

    _emit(fp)


def _emit(fp):
    rows = [json.loads(l) for l in open(CKPT)]
    with open("out/g3q_ledger.json", "w") as f:
        json.dump({"fingerprint": fp, "ledger": rows}, f, indent=2)
    import csv
    cols = ["engine", "index_config", "scenario", "w_ref", "correctness",
            "recall_at_k", "leak_rate", "p50_ms", "p95_ms",
            "throughput_ops_s", "storage_bytes", "source_class", "notes"]
    with open("out/g3q_ledger.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print("\nGATE CHECK (registered; decide against these numbers):")
    print("  QP0: rangeidx D=16 p50 << 64-84ms? If ~2ms flat -> H4 qdrant rows")
    print("       carry an unindexed-range CONFOUND flag; partitioning moot here.")
    print("  QP1: partitioned recall ~= D=1 baseline, D-independent (expect 1.00)?")
    print("  QP2: partitioned p50 ~flat ~1-3ms across D?")
    print("  Compare: pg-partitioned was 0.97 @ 1.8ms at D=16 (g3_ledger).")
    print("  Backend question (Q2): pick the column that wins recall@cost at D=16.")
    print("Canonical: out/g3q_ledger.{csv,json}")


if __name__ == "__main__":
    main()
