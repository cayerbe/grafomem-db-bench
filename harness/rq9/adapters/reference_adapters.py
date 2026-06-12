"""
Reference backends (numpy, exact). These are NOT commercial engines; they are the
control anchors. Because they are exact brute-force stores their recall is ~1.0,
so the variable the demo surfaces is the COST of each correctness posture and the
LEAK/unretrievable behaviour -- which is exactly what RQ9 pairs.

  ReferenceHonest      physical per-tenant arrays; delete = true row excision.
                       -> 0 leak, gone at probe 1, but delete pays an array
                          rebuild and storage drops immediately. The "what
                          perfect correctness costs" anchor.
  TombstoneHonest      shared array + tombstone consulted on read; physical
                       reclaim only at compact().
                       -> 0 leak, gone at probe 1, delete ~free, but storage
                          stays inflated until compaction (H3/W6 cost shape).
  TombstoneLeaky       claims-but-leaks foil: sets tombstone, audit says "gone",
                       read path NEVER consults it.
                       -> delete returns instantly, audit clean, yet deleted ids
                          stay rankable forever (ops_until_gone = never). W6.
  LeakyTenant          ignores tenant scope on read.
                       -> full recall AND full cross-tenant leak. W5.
"""
from __future__ import annotations

import numpy as np
from gmp_cost.protocol import Record, Hit, Capabilities, T_OPEN


def _topk(mat, rids, query, k):
    # Apple-Silicon/Accelerate BLAS raises spurious FP-status warnings here
    # (overflow/divide/invalid) although inputs are unit vectors and outputs are
    # finite cosine sims in [-1,1]. Suppress the cosmetic flags; correctness is
    # unaffected -- portable recall/leak are identical across BLAS backends.
    with np.errstate(all="ignore"):
        sims = mat @ query
    if len(rids) == 0:
        return []
    kk = min(k, len(rids))
    idx = np.argpartition(-sims, kk - 1)[:kk]
    idx = idx[np.argsort(-sims[idx])]
    return [Hit(rids[i], float(sims[i])) for i in idx]


class _Base:
    version = "ref-0.1"
    index_config = {"index": "bruteforce", "metric": "cosine"}

    def supersede(self, rid, new, at):
        # close the old interval, write the new version
        if rid in self._byrid:
            r = self._byrid[rid]
            self._byrid[rid] = Record(r.rid, r.vector, r.tenant, r.valid_from, at)
        self.write([Record(new.rid, new.vector, new.tenant, at, T_OPEN)])

    def flush(self):
        pass

    def compact(self):
        pass


class ReferenceHonest(_Base):
    name = "ReferenceHonest"
    caps = Capabilities(physical_tenant_isolation=True, hard_delete=True,
                        native_bitemporal=True, consults_tombstone_on_read=True,
                        consults_tenant_on_read=True)

    def __init__(self):
        self._tenants: dict[str, dict] = {}   # tenant -> {rids, mat}
        self._byrid: dict[str, Record] = {}

    def write(self, recs):
        for r in recs:
            t = self._tenants.setdefault(r.tenant, {"rids": [], "vecs": []})
            t["rids"].append(r.rid)
            t["vecs"].append(r.vector)
            self._byrid[r.rid] = r

    def delete(self, rids):
        rids = set(rids)
        for t in self._tenants.values():
            keep = [i for i, rid in enumerate(t["rids"]) if rid not in rids]
            t["rids"] = [t["rids"][i] for i in keep]
            t["vecs"] = [t["vecs"][i] for i in keep]   # true excision -> rebuild
        for rid in rids:
            self._byrid.pop(rid, None)

    def retrieve(self, query, k, tenant, as_of=None):
        if tenant is None:
            rids, vecs = [], []
            for t in self._tenants.values():
                rids += t["rids"]; vecs += t["vecs"]
        else:
            t = self._tenants.get(tenant, {"rids": [], "vecs": []})
            rids, vecs = list(t["rids"]), list(t["vecs"])
        if as_of is not None:
            f = [(i, rid) for i, rid in enumerate(rids)
                 if self._valid(rid, as_of)]
            rids = [rid for _, rid in f]; vecs = [vecs[i] for i, _ in f]
        if not rids:
            return []
        return _topk(np.stack(vecs), rids, query, k)

    def _valid(self, rid, t):
        r = self._byrid.get(rid)
        return r is not None and r.valid_from <= t < r.valid_until

    def audit(self, rid):
        return {"present": rid in self._byrid}

    def storage_bytes(self):
        return sum(len(t["rids"]) for t in self._tenants.values()) * \
            (self._dim() * 4) if self._byrid else 0

    def _dim(self):
        for t in self._tenants.values():
            if t["vecs"]:
                return len(t["vecs"][0])
        return 0


class _SharedTombstone(_Base):
    """Shared array, tenant tag column, tombstone set. Subclasses decide whether
    the read path consults the tombstone (honest) or not (claims-but-leaks)."""
    caps = Capabilities(physical_tenant_isolation=False, hard_delete=True,
                        native_bitemporal=True, consults_tombstone_on_read=True,
                        consults_tenant_on_read=True)
    consult_tombstone = True
    consult_tenant = True

    def __init__(self):
        self._rids: list[str] = []
        self._vecs: list[np.ndarray] = []
        self._ten: list[str] = []
        self._byrid: dict[str, Record] = {}
        self._dead: set[str] = set()

    def write(self, recs):
        for r in recs:
            self._rids.append(r.rid); self._vecs.append(r.vector)
            self._ten.append(r.tenant); self._byrid[r.rid] = r

    def delete(self, rids):
        self._dead |= set(rids)            # tombstone only; no reclaim

    def compact(self):
        keep = [i for i, rid in enumerate(self._rids) if rid not in self._dead]
        self._rids = [self._rids[i] for i in keep]
        self._vecs = [self._vecs[i] for i in keep]
        self._ten = [self._ten[i] for i in keep]
        for rid in self._dead:
            self._byrid.pop(rid, None)
        self._dead.clear()

    def retrieve(self, query, k, tenant, as_of=None):
        rids, vecs = [], []
        for i, rid in enumerate(self._rids):
            if self.consult_tenant and tenant is not None and self._ten[i] != tenant:
                continue
            if self.consult_tombstone and rid in self._dead:
                continue
            if as_of is not None and not self._valid(rid, as_of):
                continue
            rids.append(rid); vecs.append(self._vecs[i])
        if not rids:
            return []
        return _topk(np.stack(vecs), rids, query, k)

    def _valid(self, rid, t):
        r = self._byrid.get(rid)
        return r is not None and r.valid_from <= t < r.valid_until

    def audit(self, rid):
        # self-report: a claims-but-leaks store still says 'gone' here
        return {"present": rid in self._byrid and rid not in self._dead}

    def storage_bytes(self):
        d = len(self._vecs[0]) if self._vecs else 0
        return len(self._rids) * d * 4     # dead rows still counted until compact


class TombstoneHonest(_SharedTombstone):
    name = "TombstoneHonest"
    consult_tombstone = True
    consult_tenant = True


class TombstoneLeaky(_SharedTombstone):
    """Advertises hard_delete; read path ignores the tombstone. W6 foil."""
    name = "TombstoneLeaky"
    caps = Capabilities(physical_tenant_isolation=False, hard_delete=True,
                        native_bitemporal=True, consults_tombstone_on_read=False,
                        consults_tenant_on_read=True)
    consult_tombstone = False
    consult_tenant = True


class LeakyTenant(_SharedTombstone):
    """Advertises isolation; read path ignores tenant scope. W5 foil."""
    name = "LeakyTenant"
    caps = Capabilities(physical_tenant_isolation=False, hard_delete=True,
                        native_bitemporal=True, consults_tombstone_on_read=True,
                        consults_tenant_on_read=False)
    consult_tombstone = True
    consult_tenant = False
