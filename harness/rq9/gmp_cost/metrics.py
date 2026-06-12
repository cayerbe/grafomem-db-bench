"""
Metric primitives. Each is deterministic given its inputs; latency is the only
hardware-bound family and is always reported WITH the recall it bought, never
alone (a fast wrong answer is not a finding).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
import numpy as np


@dataclass
class Lat:
    p50: float
    p95: float
    p99: float
    mx: float
    mean: float


def percentiles(samples_ms: list[float]) -> Lat:
    a = np.asarray(samples_ms, dtype=np.float64)
    return Lat(
        p50=float(np.percentile(a, 50)),
        p95=float(np.percentile(a, 95)),
        p99=float(np.percentile(a, 99)),
        mx=float(a.max()),
        mean=float(a.mean()),
    )


def recall_at_k(retrieved: list[str], oracle: list[str], k: int) -> float:
    """|retrieved ∩ oracle| / |oracle|, both truncated to k. The two-sided point:
    this measures the MUST-return side. The leak side is measured separately."""
    if not oracle:
        return float("nan")
    r = set(retrieved[:k])
    o = set(oracle[:k])
    return len(r & o) / len(o)


def leak_rate(retrieved: list[str], forbidden: set[str]) -> float:
    """Fraction of returned ids that MUST NOT have appeared (out-of-tenant, or
    deleted, or temporally invalid). This is the W5/W6 leak side. 0.0 with full
    recall == PASS; 0.0 with 0.0 recall == OVER_RESTRICTS, caught upstream."""
    if not retrieved:
        return 0.0
    return sum(1 for r in retrieved if r in forbidden) / len(retrieved)


def timed(fn, *args, **kw) -> tuple[object, float]:
    t0 = time.perf_counter()
    out = fn(*args, **kw)
    return out, (time.perf_counter() - t0) * 1e3   # ms


def measure_calls(fn, payloads, warmup: int = 5) -> tuple[list[float], list[object]]:
    """Run fn over payloads; discard `warmup` first samples from the latency
    distribution (cache/JIT/connection warmup) but keep their outputs."""
    lat: list[float] = []
    outs: list[object] = []
    for i, p in enumerate(payloads):
        out, ms = timed(fn, *p)
        outs.append(out)
        if i >= warmup:
            lat.append(ms)
    return lat, outs


def throughput(n_ops: int, wall_s: float) -> float:
    return n_ops / wall_s if wall_s > 0 else float("inf")


def delete_unretrievable(backend, deleted_rids: set[str], probe_query: np.ndarray,
                         tenant: str | None, k: int,
                         max_probes: int = 200, settle_ms: float = 0.0) -> dict:
    """Time from delete()-ack to the moment NONE of `deleted_rids` is rankable.

    Returns wall time AND op-count-until-gone. The op count is hardware
    independent and IS the W6 footprint: a store whose read path never consults
    the tombstone never goes (capped at max_probes -> 'never within budget'),
    which is exactly claims-but-leaks. A store that excises on the read path
    goes at probe 1.
    """
    t0 = time.perf_counter()
    probes = 0
    while probes < max_probes:
        probes += 1
        hits = backend.retrieve(probe_query, k, tenant)
        still = {h.rid for h in hits} & deleted_rids
        if not still:
            return {
                "gone": True,
                "ops_until_gone": probes,
                "walltime_ms": (time.perf_counter() - t0) * 1e3,
            }
        # allow a deferred read path (compaction-driven) a chance to settle
        if settle_ms:
            time.sleep(settle_ms / 1e3)
            backend.flush()
    return {"gone": False, "ops_until_gone": None,
            "walltime_ms": (time.perf_counter() - t0) * 1e3}
