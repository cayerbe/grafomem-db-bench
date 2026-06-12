"""
Oracle: deterministic corpus, queries, and EXACT nearest-neighbour ground truth.

Everything here is seed-pinned and embedder-free -- the recall/leak numbers it
produces are reproducible bit-for-bit on any machine. This is the "no LLM-judged
evidence / deterministic checks" discipline applied to the cost harness: the
oracle decides what SHOULD be returned, the harness measures what the engine DID
return and what that cost. Latency varies by hardware; recall and leak do not.

Adversarial structure (deliberate, mirrors the W5/W6 foils):
  * Tenants share the embedding space (interleaved cluster centres), so the true
    nearest neighbours of a tenant-A query INCLUDE tenant-B vectors. Tenant
    scoping must therefore exclude by *scope*, not by distance -- the only way to
    pass W5 honestly. A store that filters "by convention" and drops the filter
    leaks here, visibly.
  * The delete set is chosen from query-adjacent records, so removing them
    actually changes the result set. A tombstone the read path ignores
    (claims-but-leaks) shows up as deleted ids still ranked -- W6 in miniature.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
from .protocol import Record, T_OPEN


@dataclass
class Corpus:
    records: list[Record]
    by_rid: dict[str, Record]
    matrix: np.ndarray          # (N, dim) L2-normalized float32
    rids: list[str]
    tenants: list[str]


def _normalize(x: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(x, axis=-1, keepdims=True)
    n[n == 0] = 1.0
    return (x / n).astype(np.float32)


def make_corpus(seed: int, n: int, dim: int, n_tenants: int,
                superseded_frac: float = 0.1) -> Corpus:
    rng = np.random.default_rng(seed)
    tenants = [f"t{i}" for i in range(n_tenants)]
    # Interleaved cluster centres so tenants overlap in space (adversarial).
    centres = _normalize(rng.standard_normal((n_tenants, dim)))
    recs: list[Record] = []
    for i in range(n):
        ten_idx = i % n_tenants                 # round-robin => interleaved
        v = centres[ten_idx] + 0.6 * rng.standard_normal(dim)
        v = _normalize(v.astype(np.float32))
        rid = f"r{i:06d}"
        # A fraction carry a closed valid interval (already superseded once),
        # the rest are open (valid_until == T_OPEN, the sentinel).
        if rng.random() < superseded_frac:
            vf, vu = 0, 100
        else:
            vf, vu = 0, T_OPEN
        recs.append(Record(rid=rid, vector=v, tenant=tenants[ten_idx],
                            valid_from=vf, valid_until=vu))
    by_rid = {r.rid: r for r in recs}
    matrix = np.stack([r.vector for r in recs])
    return Corpus(records=recs, by_rid=by_rid, matrix=matrix,
                  rids=[r.rid for r in recs], tenants=tenants)


def make_queries(seed: int, n_queries: int, dim: int) -> np.ndarray:
    rng = np.random.default_rng(seed + 9973)    # disjoint stream from corpus
    q = rng.standard_normal((n_queries, dim)).astype(np.float32)
    return _normalize(q)


def exact_knn(corpus: Corpus, query: np.ndarray, k: int,
              allowed_rids: set[str] | None = None,
              as_of: int | None = None) -> list[str]:
    """Ground-truth top-k by cosine similarity, restricted to `allowed_rids`
    and/or temporally valid `as_of`. This is THE oracle: every recall and leak
    number is measured against this, never against another engine's output."""
    mask = np.ones(len(corpus.rids), dtype=bool)
    if allowed_rids is not None:
        allowed = np.array([r in allowed_rids for r in corpus.rids])
        mask &= allowed
    if as_of is not None:
        valid = np.array([(r.valid_from <= as_of < r.valid_until)
                          for r in corpus.records])
        mask &= valid
    with np.errstate(all="ignore"):          # see reference_adapters._topk note
        sims = corpus.matrix @ query
    sims = np.where(mask, sims, -np.inf)
    idx = np.argpartition(-sims, min(k, mask.sum() - 1))[:k]
    idx = idx[np.argsort(-sims[idx])]
    return [corpus.rids[i] for i in idx if np.isfinite(sims[i])]


def in_tenant_rids(corpus: Corpus, tenant: str,
                   excluded: set[str] | None = None) -> set[str]:
    excluded = excluded or set()
    return {r.rid for r in corpus.records
            if r.tenant == tenant and r.rid not in excluded}
