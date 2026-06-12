"""
H4-stress corpus: supersession chains. Slot [H4-STRESS].

N_logical facts, each superseded to depth D: version v of chain c is valid on
[v*EPOCH, (v+1)*EPOCH), last version open (valid_until = T_OPEN sentinel).
Physical rows = N_logical * D.

Adversarial core: versions of the same chain are NEAR-DUPLICATES in embedding
space (base vector + small per-version drift). At any as_of t, the nearest
neighbours of a query are dominated by temporally-INVALID versions of the right
chains -- distance actively retrieves stale data; only the validity predicate
excludes it. Temporal selectivity at any t is exactly 1/D, so as_of inherits
the H1 filtered-ANN cost structure with selectivity = chain depth.

Two-sided as ever: as_of must return the version valid at t (recall side) and
must NOT return stale/future versions (leak side). A store that ranks by
similarity and ignores validity returns the freshest-looking wrong answer.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
from .protocol import Record, T_OPEN

EPOCH = 100   # version v of any chain is valid on [v*EPOCH, (v+1)*EPOCH)


def rid_of(chain: int, ver: int) -> str:
    return f"c{chain:06d}v{ver:02d}"


def parse_rid(rid: str) -> tuple[int, int]:
    return int(rid[1:7]), int(rid[8:10])


@dataclass
class ChainCorpus:
    matrix: np.ndarray        # (N_logical*D, dim) float32 unit rows
    chain_ids: np.ndarray     # (P,) int32
    versions: np.ndarray      # (P,) int16
    valid_from: np.ndarray    # (P,) int64
    valid_until: np.ndarray   # (P,) int64
    depth: int
    seed: int

    @property
    def n_physical(self) -> int:
        return self.matrix.shape[0]

    def records_batches(self, batch: int = 2000):
        for lo in range(0, self.n_physical, batch):
            hi = min(lo + batch, self.n_physical)
            yield [Record(rid=rid_of(int(self.chain_ids[i]), int(self.versions[i])),
                          vector=self.matrix[i], tenant="t0",
                          valid_from=int(self.valid_from[i]),
                          valid_until=int(self.valid_until[i]))
                   for i in range(lo, hi)]


def make_chain_corpus(seed: int, n_logical: int, depth: int, dim: int,
                      drift: float = 0.15) -> ChainCorpus:
    """drift: per-version perturbation scale relative to the base vector.
    Small drift => versions are tight clusters => maximally adversarial for
    similarity-only retrieval (stale versions rank immediately adjacent)."""
    rng = np.random.default_rng(seed)
    P = n_logical * depth
    base = rng.standard_normal((n_logical, dim)).astype(np.float32)
    mat = np.empty((P, dim), dtype=np.float32)
    chain_ids = np.repeat(np.arange(n_logical, dtype=np.int32), depth)
    versions = np.tile(np.arange(depth, dtype=np.int16), n_logical)
    for v in range(depth):
        idx = versions == v
        mat[idx] = base + drift * rng.standard_normal((n_logical, dim)).astype(np.float32)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    mat /= norms
    valid_from = versions.astype(np.int64) * EPOCH
    valid_until = (versions.astype(np.int64) + 1) * EPOCH
    valid_until[versions == depth - 1] = T_OPEN          # sentinel: still true
    return ChainCorpus(matrix=mat, chain_ids=chain_ids, versions=versions,
                       valid_from=valid_from, valid_until=valid_until,
                       depth=depth, seed=seed)


def exact_asof_topk(c: ChainCorpus, query: np.ndarray, k: int, t: int) -> list[str]:
    """Exact oracle for as_of t: top-k among temporally valid rows only."""
    with np.errstate(all="ignore"):
        sims = c.matrix @ query
    valid = (c.valid_from <= t) & (t < c.valid_until)
    sims = np.where(valid, sims, -np.inf)
    kk = min(k, int(valid.sum()))
    idx = np.argpartition(-sims, kk - 1)[:kk]
    idx = idx[np.argsort(-sims[idx])]
    return [rid_of(int(c.chain_ids[i]), int(c.versions[i]))
            for i in idx if np.isfinite(sims[i])]


def temporal_leak(c: ChainCorpus, retrieved: list[str], t: int) -> float:
    """Fraction of returned rids that are temporally INVALID at t -- stale or
    future versions. This is W2/H4's leak side."""
    if not retrieved:
        return 0.0
    bad = 0
    for r in retrieved:
        chain, ver = parse_rid(r)
        i = chain * c.depth + ver                  # row layout is chain-major
        if not (c.valid_from[i] <= t < c.valid_until[i]):
            bad += 1
    return bad / len(retrieved)
