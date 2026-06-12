"""
RQ9 cost harness runner.

Each scenario produces LedgerRow(s) that pair an [OBSERVED] correctness verdict
(decided by the oracle, not the engine) with the [OBSERVED] cost of obtaining it.
The five scenarios map onto the parent project's correctness anchors:

  retrieve.unfiltered     -> baseline recall/latency (no guarantee under test)
  retrieve.tenant_scoped  -> W5 isolation: recall in-tenant + leak of out-of-tenant
  delete.honest           -> W6 deletion: leak of deleted + delete-to-unretrievable
  retrieve.as_of          -> H4/RQ4 bi-temporal: as_of recall + native-vs-emulated cost
  storage.amplification   -> H3 physical-vs-logical isolation footprint tax

Latency is comparable only WITHIN one run on one machine; recall, leak, and
ops_until_gone are portable. The fingerprint pins the run.
"""
from __future__ import annotations

import csv, json, platform, sys, time
from dataclasses import asdict
import numpy as np

import os as _os
try:
    import psutil
    _RAM = psutil.virtual_memory().total
    _CPU = psutil.cpu_count(logical=False) or psutil.cpu_count()
except Exception:                       # psutil optional: degrade gracefully
    _RAM, _CPU = None, _os.cpu_count()

from .protocol import Backend, LedgerRow, Record, T_OPEN
from .oracle import Corpus, exact_knn, in_tenant_rids
from .metrics import (percentiles, recall_at_k, leak_rate, measure_calls,
                      throughput, delete_unretrievable, timed)


def fingerprint(seed_corpus: int, seed_query: int, k: int) -> dict:
    return {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "cpu_cores_physical": _CPU,
        "ram_bytes": _RAM,
        "seed_corpus": seed_corpus,
        "seed_query": seed_query,
        "k": k,
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "comparability_note": (
            "Latency rows are comparable ONLY across engines run in THIS "
            "fingerprint. recall_at_k, leak_rate, ops_until_gone are portable."
        ),
    }


def _verdict(recall: float, leak: float) -> str:
    # Two-sided: never call 0 leak a pass without recall.
    if leak > 0 and recall > 0:
        return "LEAKS"
    if leak > 0:
        return "LEAKS"
    if recall == 0:
        return "OVER_RESTRICTS"
    if recall >= 0.999:
        return "PASS"
    return "PARTIAL"


def _cfg(b: Backend) -> str:
    return ",".join(f"{k}={v}" for k, v in b.index_config.items())


def run_unfiltered(b: Backend, c: Corpus, queries, k) -> LedgerRow:
    payloads = [(q, k, None, None) for q in queries]
    lat, outs = measure_calls(b.retrieve, payloads)
    recalls = []
    for q, hits in zip(queries, outs):
        oracle = exact_knn(c, q, k)
        recalls.append(recall_at_k([h.rid for h in hits], oracle, k))
    L = percentiles(lat)
    rec = float(np.mean(recalls))
    return LedgerRow(b.name, b.version, _cfg(b), "retrieve.unfiltered", "-",
                     "PASS" if rec >= 0.999 else "PARTIAL", rec, None,
                     L.p50, L.p95, L.p99, L.mx, None, b.storage_bytes(),
                     None, None, None,
                     notes=f"recall@{k}={rec:.3f}; baseline, no guarantee under test")


def run_tenant_scoped(b: Backend, c: Corpus, queries, k) -> LedgerRow:
    tenants = c.tenants
    payloads, oracles, forbiddens = [], [], []
    for i, q in enumerate(queries):
        ten = tenants[i % len(tenants)]
        payloads.append((q, k, ten, None))
        allowed = in_tenant_rids(c, ten)
        oracles.append(exact_knn(c, q, k, allowed_rids=allowed))
        forbiddens.append({r for r in c.rids if r not in allowed})
    lat, outs = measure_calls(b.retrieve, payloads)
    recalls, leaks = [], []
    for hits, orc, forb in zip(outs, oracles, forbiddens):
        ids = [h.rid for h in hits]
        recalls.append(recall_at_k(ids, orc, k))
        leaks.append(leak_rate(ids, forb))
    L = percentiles(lat)
    rec, lk = float(np.mean(recalls)), float(np.mean(leaks))
    return LedgerRow(b.name, b.version, _cfg(b), "retrieve.tenant_scoped", "W5",
                     _verdict(rec, lk), rec, lk, L.p50, L.p95, L.p99, L.mx,
                     None, b.storage_bytes(), None, None, None,
                     notes=f"in-tenant recall@{k}={rec:.3f}; out-of-tenant leak={lk:.3f}")


def run_delete_honest(b: Backend, c: Corpus, queries, k) -> LedgerRow:
    # Delete a query-adjacent slice from one tenant, then measure (a) the leak of
    # deleted ids on reads and (b) delete-to-unretrievable. Re-seed a fresh copy
    # of the data first so this scenario is independent.
    ten = c.tenants[0]
    probe = queries[0]
    oracle_pre = exact_knn(c, probe, k, allowed_rids=in_tenant_rids(c, ten))
    to_delete = set(oracle_pre[: max(1, k // 2)])      # remove half the answer
    # time the delete call(s)
    (_, ack_ms) = timed(b.delete, list(to_delete))
    b.flush()
    # leak: do deleted ids still appear?
    hits = b.retrieve(probe, k, ten)
    lk = leak_rate([h.rid for h in hits], to_delete)
    # unretrievable timing (op-count is the portable W6 footprint)
    du = delete_unretrievable(b, to_delete, probe, ten, k,
                              settle_ms=0.2 if hasattr(b, "compact") else 0.0)
    oracle_post = exact_knn(
        c, probe, k, allowed_rids=in_tenant_rids(c, ten, excluded=to_delete))
    rec = recall_at_k([h.rid for h in hits], oracle_post, k)
    verdict = "LEAKS" if lk > 0 else ("PASS" if du["gone"] else "LEAKS")
    return LedgerRow(b.name, b.version, _cfg(b), "delete.honest", "W6",
                     verdict, rec, lk, None, None, None, None, None,
                     b.storage_bytes(), ack_ms,
                     du["walltime_ms"] if du["gone"] else None,
                     du["ops_until_gone"],
                     notes=(f"delete ack={ack_ms:.3f}ms; "
                            f"unretrievable after {du['ops_until_gone']} probe(s)"
                            if du["gone"] else
                            f"delete ack={ack_ms:.3f}ms; STILL RANKABLE after "
                            f"{200} probes (claims-but-leaks window)"))


def run_as_of(b: Backend, c: Corpus, queries, k) -> LedgerRow:
    as_of_t = 50    # inside the closed-interval window of superseded records
    payloads = [(q, k, None, as_of_t) for q in queries]
    lat, outs = measure_calls(b.retrieve, payloads)
    recalls, leaks = [], []
    for q, hits in zip(queries, outs):
        oracle = exact_knn(c, q, k, as_of=as_of_t)
        forbidden = {r.rid for r in c.records
                     if not (r.valid_from <= as_of_t < r.valid_until)}
        ids = [h.rid for h in hits]
        recalls.append(recall_at_k(ids, oracle, k))
        leaks.append(leak_rate(ids, forbidden))
    L = percentiles(lat)
    rec, lk = float(np.mean(recalls)), float(np.mean(leaks))
    mode = "native" if b.caps.native_bitemporal else "emulated/metadata-filter"
    return LedgerRow(b.name, b.version, _cfg(b), "retrieve.as_of", "H4/RQ4",
                     _verdict(rec, lk), rec, lk, L.p50, L.p95, L.p99, L.mx,
                     None, b.storage_bytes(), None, None, None,
                     notes=f"as_of={as_of_t} [{mode}]; recall={rec:.3f} leak={lk:.3f}")


def run_storage_amplification(b: Backend, c: Corpus) -> LedgerRow:
    live = b.storage_bytes()
    mode = ("physical/per-tenant" if b.caps.physical_tenant_isolation
            else "logical/shared")
    return LedgerRow(b.name, b.version, _cfg(b), "storage.amplification", "H3",
                     "N/A", None, None, None, None, None, None, None, live,
                     None, None, None,
                     notes=f"{mode} isolation; live+dead footprint={live} bytes")


def run_all(b: Backend, c: Corpus, queries, k) -> list[LedgerRow]:
    rows = [
        run_unfiltered(b, c, queries, k),
        run_tenant_scoped(b, c, queries, k),
        run_as_of(b, c, queries, k),
        run_storage_amplification(b, c),
        run_delete_honest(b, c, queries, k),   # last: mutates the store
    ]
    return rows


def emit(rows: list[LedgerRow], fp: dict, csv_path: str, json_path: str) -> None:
    with open(json_path, "w") as f:
        json.dump({"fingerprint": fp, "ledger": [asdict(r) for r in rows]},
                  f, indent=2)
    cols = ["engine", "index_config", "scenario", "w_ref", "correctness", "recall_at_k",
            "leak_rate", "p50_ms", "p95_ms", "delete_ack_ms",
            "unretrievable_ms", "ops_until_gone", "storage_bytes",
            "source_class", "notes"]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(asdict(r))
