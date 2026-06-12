"""
Qdrant adapter -- first commercial RQ7 target (open-source, Rust, Apache-2.0
core, local-runnable via `docker run -p 6333:6333 qdrant/qdrant`). Import-guarded;
reach a live instance via $RQ9_QDRANT_URL.

Why Qdrant is the interesting W6 case: deletes are mark-deleted in the HNSW
segments and only physically reclaimed by the optimizer. run_delete_honest's
op-count poller + the compact() hook (which triggers an optimizer pass) are
exactly what measures the "delete returned 200 vs zero recall footprint" gap the
charter calls out -- on a real engine rather than a foil.

Tenant scope here is a payload filter (logical, by convention) -- which is the
H3 distinction made concrete, and the 7b switch drops the filter.
"""
from __future__ import annotations
import os, time
import numpy as np
from gmp_cost.protocol import Record, Hit, Capabilities, T_OPEN

try:
    from qdrant_client import QdrantClient, models as qm
    _HAVE_Q = True
except Exception:
    _HAVE_Q = False

COLL = "rq9_mem"


class QdrantBackend:
    name = "qdrant"
    version = "unknown"
    caps = Capabilities(physical_tenant_isolation=False,   # payload-filter tenancy
                        hard_delete=True,                   # claim; W6 verifies
                        native_bitemporal=False,
                        consults_tombstone_on_read=True,
                        consults_tenant_on_read=True)

    def __init__(self, dim: int, m: int = 16, ef_construct: int = 64,
                 hnsw_ef: int = 64, deployed_correctly: bool = True,
                 url: str | None = None,
                 full_scan_threshold: int | None = None,
                 index_validity: bool = False):
        # index_validity: create integer payload indexes on valid_from /
        # valid_until. Tests QP0 -- whether H4's 64-84 ms exactness was largely
        # an UNINDEXED-range-filter confound rather than inherent fallback cost.
        # full_scan_threshold (KB): Qdrant's planner falls back to exact scan
        # when the estimated filtered-cardinality payload is below this. Setting
        # it to 1 forces filtered queries THROUGH the HNSW graph -- the
        # diagnostic that splits "filter-aware traversal works" from "the 1.00
        # came from the exact fallback" (F-QD-3 mechanism question).
        if not _HAVE_Q:
            raise RuntimeError("qdrant_client not installed; needs a live Qdrant. "
                               "The reference demo does not.")
        self.dim = dim
        self.deployed_correctly = deployed_correctly
        self.hnsw_ef = hnsw_ef
        self.index_config = {"index": "hnsw", "M": m, "ef_construct": ef_construct,
                             "hnsw_ef": hnsw_ef,
                             "deployed": "7a-correct" if deployed_correctly else "7b-misconfig"}
        self.full_scan_threshold = full_scan_threshold
        if full_scan_threshold is not None:
            self.index_config["fst"] = full_scan_threshold
        self.url = url or os.environ.get("RQ9_QDRANT_URL", "http://127.0.0.1:6333")
        if self.url == ":memory:":
            # in-process local mode: exact search, no real HNSW. Useful ONLY for
            # validating adapter plumbing (filters, delete, 7a/7b); never cite
            # its numbers as Qdrant engine behaviour.
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
        # recreate_collection is deprecated; delete-if-exists + create
        try:
            self.cli.delete_collection(COLL)
        except Exception:
            pass
        # Qdrant only builds the vector index once a segment exceeds
        # indexing_threshold (default 20000 KB). Small benchmark corpora sit
        # below it and get PLAIN full-scan search -- hnsw_ef becomes a no-op and
        # recall pins flat at 1.00 (the run-2 fingerprint). Force a tiny
        # threshold so HNSW actually builds; record indexed_vectors_count on
        # every row so "which code path ran" is observed, not inferred.
        self.cli.create_collection(
            COLL,
            vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
            hnsw_config=qm.HnswConfigDiff(
                m=m, ef_construct=ef_construct,
                **({"full_scan_threshold": full_scan_threshold}
                   if full_scan_threshold is not None else {})),
            optimizers_config=qm.OptimizersConfigDiff(indexing_threshold=10),
        )
        self.cli.create_payload_index(COLL, "tenant",
                                      field_schema=qm.PayloadSchemaType.KEYWORD)
        self.index_validity = index_validity
        if index_validity:
            self.index_config["validx"] = True
            for f in ("valid_from", "valid_until"):
                try:
                    self.cli.create_payload_index(
                        COLL, f, field_schema=qm.PayloadSchemaType.INTEGER)
                except Exception:
                    pass    # local mode may not support; server does
        self._counter = 0
        self._idmap: dict[str, int] = {}

    def write(self, recs):
        pts = []
        for r in recs:
            pid = self._counter; self._counter += 1
            self._idmap[r.rid] = pid
            pts.append(qm.PointStruct(id=pid, vector=r.vector.tolist(),
                       payload={"rid": r.rid, "tenant": r.tenant,
                                "valid_from": r.valid_from, "valid_until": r.valid_until}))
        # chunked upsert: large batches in one call stall/oversize at scale.
        # wait=False during bulk load; flush() polls optimizer green afterwards.
        CH = 1024
        many = len(pts) > CH
        for lo in range(0, len(pts), CH):
            self.cli.upsert(COLL, points=pts[lo:lo + CH], wait=not many)

    def supersede(self, rid, new, at):
        pid = self._idmap.get(rid)
        if pid is not None:
            self.cli.set_payload(COLL, payload={"valid_until": at}, points=[pid], wait=True)
        self.write([Record(new.rid, new.vector, new.tenant, at, T_OPEN)])

    def delete(self, rids):
        ids = [self._idmap[r] for r in rids if r in self._idmap]
        # wait=True: ack after the operation is applied. The W6 probe then asks
        # the only question that matters: is 'applied' the same as 'unrankable'?
        # Mark-deleted points are excluded by Qdrant's read path even before the
        # optimizer physically reclaims them -- gone@1 expected; a gap here would
        # be the claims-but-leaks window on a real engine.
        self.cli.delete(COLL, points_selector=qm.PointIdsList(points=ids), wait=True)

    def compact(self):
        # force an optimizer pass so mark-deleted points are physically reclaimed
        self.cli.update_collection(
            COLL, optimizer_config=qm.OptimizersConfigDiff(default_segment_number=1))
        time.sleep(0.5)

    def retrieve(self, query, k, tenant, as_of=None):
        must = []
        if tenant is not None and self.deployed_correctly:    # 7b drops this
            must.append(qm.FieldCondition(key="tenant", match=qm.MatchValue(value=tenant)))
        if as_of is not None:
            must.append(qm.FieldCondition(key="valid_from", range=qm.Range(lte=as_of)))
            must.append(qm.FieldCondition(key="valid_until", range=qm.Range(gt=as_of)))
        flt = qm.Filter(must=must) if must else None
        params = qm.SearchParams(hnsw_ef=self.hnsw_ef)
        if hasattr(self.cli, "query_points"):      # qdrant-client >= 1.10
            res = self.cli.query_points(COLL, query=query.tolist(), limit=k,
                                        query_filter=flt, search_params=params,
                                        with_payload=True).points
        else:                                       # older clients
            res = self.cli.search(COLL, query_vector=query.tolist(), limit=k,
                                  query_filter=flt, search_params=params)
        return [Hit(p.payload["rid"], float(p.score)) for p in res]

    def audit(self, rid):
        pid = self._idmap.get(rid)
        if pid is None:
            return {"present": False}
        got = self.cli.retrieve(COLL, ids=[pid])
        return {"present": bool(got)}

    def flush(self):
        # wait for the optimizer to finish (status green), then record how many
        # vectors are actually in the HNSW index. indexed=0 on a row means that
        # row measured plain search, not ANN -- never cite it as HNSW behaviour.
        import time as _t, os as _os
        deadline = _t.time() + float(_os.environ.get("RQ9_QDRANT_GREEN_TIMEOUT", "120"))
        status, indexed = "?", None
        while _t.time() < deadline:
            try:
                info = self.cli.get_collection(COLL)
                status = str(getattr(info, "status", "?"))
                indexed = getattr(info, "indexed_vectors_count", None)
                if "green" in status.lower():
                    break
            except Exception:
                pass
            _t.sleep(0.2)
        self.index_config["indexed"] = indexed
        self.index_config["status"] = status.split(".")[-1].lower()

    def storage_bytes(self):
        info = self.cli.get_collection(COLL)
        # best-effort: points * dim * 4 (Qdrant does not expose exact on-disk easily)
        return int((info.points_count or 0) * self.dim * 4)
