"""
G3 probe adapter for Qdrant: collection-per-epoch + current-snapshot collection.

Mirrors pg_partitioned_adapter (same placement function epochs_for, imported —
already unit-tested) on Qdrant primitives:

  rq9q_cur     open rows (valid_until = T_OPEN)
  rq9q_e{v}    rows valid during epoch v

retrieve(as_of=t) routes to the epoch collection; the validity filter stays in
every query (routing = optimization, predicate = guarantee). Each collection
carries integer payload indexes on the validity fields.

Registered predictions (decide before looking):
  QP1  recall ~= the D=1 baseline, INDEPENDENT of D. Expected 1.00 flat: each
       epoch collection is ~N_logical points (~5 MB at 20k/dim64), below the
       default full_scan_threshold -> exact fallback PER EPOCH.
  QP2  p50 ~flat in D at ~1-3 ms (vs H4 monolithic qdrant 64-84 ms @ D=16).
Compared against qdrant-rangeidx (QP0): if range indexes alone reach ~2 ms on
the monolith, partitioning is unnecessary on this engine.
"""
from __future__ import annotations
import os
import numpy as np
from gmp_cost.protocol import Record, Hit, Capabilities, T_OPEN
from adapters.pg_partitioned_adapter import epochs_for, EPOCH

try:
    from qdrant_client import QdrantClient, models as qm
    _HAVE_Q = True
except Exception:
    _HAVE_Q = False


class QdrantPartitionedBackend:
    name = "qdrant-partitioned"
    version = "unknown"
    caps = Capabilities(physical_tenant_isolation=False, hard_delete=True,
                        native_bitemporal=False,
                        consults_tombstone_on_read=True,
                        consults_tenant_on_read=True)

    def __init__(self, dim: int, max_epoch: int,
                 m: int = 16, ef_construct: int = 64, hnsw_ef: int = 64,
                 url: str | None = None):
        if not _HAVE_Q:
            raise RuntimeError("qdrant_client required.")
        self.dim = dim
        self.max_epoch = max_epoch
        self.hnsw_ef = hnsw_ef
        self.index_config = {"index": "hnsw-partitioned", "M": m,
                             "ef_construct": ef_construct, "hnsw_ef": hnsw_ef,
                             "epochs": max_epoch + 1}
        self.url = url or os.environ.get("RQ9_QDRANT_URL", "http://127.0.0.1:6333")
        if self.url == ":memory:":
            self.cli = QdrantClient(location=":memory:")
            self.version = "local-mode(:memory:)"
        else:
            self.cli = QdrantClient(url=self.url)
            try:
                import json as _json, urllib.request as _rq
                with _rq.urlopen(self.url, timeout=3) as r:
                    self.version = _json.loads(r.read()).get("version", "?")
            except Exception:
                self.version = "?"
        self._colls = ["rq9q_cur"] + [f"rq9q_e{v}" for v in range(max_epoch + 1)]
        self._counter = 0
        self._idmap: dict[tuple[str, str], int] = {}   # (coll, rid) -> point id
        for coll in self._colls:
            try:
                self.cli.delete_collection(coll)
            except Exception:
                pass
            self.cli.create_collection(
                coll,
                vectors_config=qm.VectorParams(size=dim,
                                               distance=qm.Distance.COSINE),
                hnsw_config=qm.HnswConfigDiff(m=m, ef_construct=ef_construct),
                optimizers_config=qm.OptimizersConfigDiff(indexing_threshold=10),
            )
            for f, sch in (("tenant", qm.PayloadSchemaType.KEYWORD),
                           ("valid_from", qm.PayloadSchemaType.INTEGER),
                           ("valid_until", qm.PayloadSchemaType.INTEGER)):
                try:
                    self.cli.create_payload_index(coll, f, field_schema=sch)
                except Exception:
                    pass

    # ------------------------------------------------------------------ write
    def write(self, recs):
        per_coll: dict[str, list] = {}
        for r in recs:
            payload = {"rid": r.rid, "tenant": r.tenant,
                       "valid_from": r.valid_from, "valid_until": r.valid_until}
            targets = [f"rq9q_e{e}" for e in
                       epochs_for(r.valid_from, r.valid_until, self.max_epoch)]
            if r.valid_until >= T_OPEN:
                targets.append("rq9q_cur")
            for coll in targets:
                pid = self._counter; self._counter += 1
                self._idmap[(coll, r.rid)] = pid
                per_coll.setdefault(coll, []).append(
                    qm.PointStruct(id=pid, vector=r.vector.tolist(),
                                   payload=payload))
        CH = 1024
        for coll, pts in per_coll.items():
            many = len(pts) > CH
            for lo in range(0, len(pts), CH):
                self.cli.upsert(coll, points=pts[lo:lo + CH], wait=not many)

    def supersede(self, rid, new, at):
        for coll in self._colls:
            pid = self._idmap.get((coll, rid))
            if pid is not None:
                self.cli.set_payload(coll, payload={"valid_until": at},
                                     points=[pid], wait=True)
        pid = self._idmap.pop(("rq9q_cur", rid), None)
        if pid is not None:
            self.cli.delete(
                "rq9q_cur", points_selector=qm.PointIdsList(points=[pid]),
                wait=True)
        self.write([Record(new.rid, new.vector, new.tenant, at, T_OPEN)])

    def delete(self, rids):
        for coll in self._colls:
            ids = [self._idmap[(coll, r)] for r in rids
                   if (coll, r) in self._idmap]
            if ids:
                self.cli.delete(coll,
                                points_selector=qm.PointIdsList(points=ids),
                                wait=True)

    # ------------------------------------------------------------------ flush
    def flush(self):
        import time as _t, os as _os
        deadline = _t.time() + float(_os.environ.get("RQ9_QDRANT_GREEN_TIMEOUT",
                                                     "120"))
        total_indexed = 0
        for coll in self._colls:
            while _t.time() < deadline:
                try:
                    info = self.cli.get_collection(coll)
                    if "green" in str(getattr(info, "status", "")).lower():
                        total_indexed += int(
                            getattr(info, "indexed_vectors_count", 0) or 0)
                        break
                except Exception:
                    pass
                _t.sleep(0.2)
        self.index_config["indexed"] = total_indexed

    # --------------------------------------------------------------- retrieve
    def _route(self, as_of: int | None) -> str:
        if as_of is None:
            return "rq9q_cur"
        e = as_of // EPOCH
        return f"rq9q_e{e}" if e <= self.max_epoch else "rq9q_cur"

    def retrieve(self, query, k, tenant, as_of=None):
        coll = self._route(as_of)
        must = []
        if tenant is not None:
            must.append(qm.FieldCondition(key="tenant",
                                          match=qm.MatchValue(value=tenant)))
        if as_of is not None:
            must.append(qm.FieldCondition(key="valid_from",
                                          range=qm.Range(lte=as_of)))
            must.append(qm.FieldCondition(key="valid_until",
                                          range=qm.Range(gt=as_of)))
        else:
            must.append(qm.FieldCondition(key="valid_until",
                                          range=qm.Range(gte=T_OPEN)))
        flt = qm.Filter(must=must)
        params = qm.SearchParams(hnsw_ef=self.hnsw_ef)
        if hasattr(self.cli, "query_points"):
            res = self.cli.query_points(coll, query=query.tolist(), limit=k,
                                        query_filter=flt, search_params=params,
                                        with_payload=True).points
        else:
            res = self.cli.search(coll, query_vector=query.tolist(), limit=k,
                                  query_filter=flt, search_params=params)
        return [Hit(p.payload["rid"], float(p.score)) for p in res]

    # ------------------------------------------------------------------ misc
    def audit(self, rid):
        return {"present": ("rq9q_cur", rid) in self._idmap}

    def compact(self):
        pass

    def storage_bytes(self):
        total = 0
        for coll in self._colls:
            try:
                info = self.cli.get_collection(coll)
                total += int((info.points_count or 0) * self.dim * 4)
            except Exception:
                pass
        return total   # estimate-class [REPORTED-self], includes placement dup
