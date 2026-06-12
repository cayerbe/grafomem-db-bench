"""
Scale-native corpus + oracle for the N-sweep (1e4 .. 1e6 vectors).

The base oracle (oracle.py) carries a list of Record objects and builds masks
with Python loops -- fine at n=4000, prohibitive at 1e6. This module keeps the
same determinism contract (seed-pinned, exact, embedder-free) on vectorized
structures:

    matrix      (N, dim) float32, L2-normalized
    tenant_ids  (N,) int32        -- tenant of row i
    rid(i) == f"r{i:07d}"         -- identity is the row index; no string table

Intervals are all-open at scale (the as_of probe is corpus-shape-gated, not
size-gated, and is excluded from the N-sweep on purpose).

Adversarial structure is preserved: tenant cluster centres are interleaved in
the embedding space, so true nearest neighbours of a tenant-A query include
other tenants' vectors -- scoping must exclude by scope, not by distance.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
from .protocol import Record, T_OPEN


def rid_of(i: int) -> str:
    return f"r{i:07d}"


def idx_of(rid: str) -> int:
    return int(rid[1:])


@dataclass
class ScaleCorpus:
    matrix: np.ndarray        # (N, dim) float32, unit rows
    tenant_ids: np.ndarray    # (N,) int32
    n_tenants: int
    seed: int

    @property
    def n(self) -> int:
        return self.matrix.shape[0]

    @property
    def dim(self) -> int:
        return self.matrix.shape[1]

    def tenant_name(self, t: int) -> str:
        return f"t{t}"

    def records_batches(self, batch: int = 2000):
        """Yield transient Record batches for adapter.write(). Records are
        created per batch and discarded -- never held for the whole corpus."""
        for lo in range(0, self.n, batch):
            hi = min(lo + batch, self.n)
            yield [Record(rid=rid_of(i), vector=self.matrix[i],
                          tenant=self.tenant_name(int(self.tenant_ids[i])),
                          valid_from=0, valid_until=T_OPEN)
                   for i in range(lo, hi)]


def make_scale_corpus(seed: int, n: int, dim: int, n_tenants: int) -> ScaleCorpus:
    rng = np.random.default_rng(seed)
    centres = rng.standard_normal((n_tenants, dim)).astype(np.float32)
    centres /= np.linalg.norm(centres, axis=1, keepdims=True)
    tenant_ids = (np.arange(n) % n_tenants).astype(np.int32)   # interleaved
    # generate in chunks to bound peak memory at 1e6
    mat = np.empty((n, dim), dtype=np.float32)
    CH = 100_000
    for lo in range(0, n, CH):
        hi = min(lo + CH, n)
        noise = rng.standard_normal((hi - lo, dim)).astype(np.float32)
        mat[lo:hi] = centres[tenant_ids[lo:hi]] + 0.6 * noise
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    mat /= norms
    return ScaleCorpus(matrix=mat, tenant_ids=tenant_ids,
                       n_tenants=n_tenants, seed=seed)


def exact_topk(c: ScaleCorpus, query: np.ndarray, k: int,
               tenant: int | None = None,
               excluded_idx: np.ndarray | None = None) -> list[str]:
    """Exact oracle, fully vectorized. tenant: restrict to that tenant id.
    excluded_idx: int array of row indices that must not appear (deleted)."""
    with np.errstate(all="ignore"):   # spurious Accelerate FP flags; see reference_adapters._topk
        sims = c.matrix @ query
    if tenant is not None:
        sims = np.where(c.tenant_ids == tenant, sims, -np.inf)
    if excluded_idx is not None and len(excluded_idx):
        sims[excluded_idx] = -np.inf
    kk = min(k, c.n)
    idx = np.argpartition(-sims, kk - 1)[:kk]
    idx = idx[np.argsort(-sims[idx])]
    return [rid_of(int(i)) for i in idx if np.isfinite(sims[i])]


def out_of_tenant(c: ScaleCorpus, retrieved: list[str], tenant: int) -> float:
    """Leak rate: fraction of returned rids whose row is NOT in `tenant`."""
    if not retrieved:
        return 0.0
    bad = sum(1 for r in retrieved if int(c.tenant_ids[idx_of(r)]) != tenant)
    return bad / len(retrieved)
