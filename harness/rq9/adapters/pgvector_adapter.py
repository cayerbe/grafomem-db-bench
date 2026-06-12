"""
pgvector adapter -- the RQ7 control engine (local-runnable, Apache/PostgreSQL
licensed, already the GRAFOMEM Cloud backend). Runnable when a Postgres with the
`vector` extension is reachable via $RQ9_PG_DSN; otherwise import-guarded so the
reference demo still runs.

This adapter is written to expose the 7a/7b distinction the charter now requires:
  deployed_correctly=True  (7a) -> tenant predicate always applied (engine-correct)
  deployed_correctly=False (7b) -> tenant predicate dropped (realistic misconfig)
pgvector does a real row DELETE, so it is honest-by-construction on W6; the
interesting cost it surfaces is index residue -- recall/latency drift between
DELETE and a VACUUM/REINDEX, which run_delete_honest + a compact() hook capture.
"""
from __future__ import annotations
import os
import numpy as np
from gmp_cost.protocol import Record, Hit, Capabilities, T_OPEN

try:
    import psycopg2
    from psycopg2.extras import execute_values
    _HAVE_PG = True
except Exception:
    _HAVE_PG = False


class PgVectorBackend:
    name = "pgvector"
    version = "unknown"            # filled from server at connect
    caps = Capabilities(physical_tenant_isolation=False, hard_delete=True,
                        native_bitemporal=False,            # timestamps-as-metadata
                        consults_tombstone_on_read=True,
                        consults_tenant_on_read=True)

    def __init__(self, dim: int, index: str = "hnsw",
                 m: int = 16, ef_construction: int = 64, ef_search: int = 40,
                 lists: int = 100, probes: int = 10,
                 deployed_correctly: bool = True, dsn: str | None = None,
                 iterative_scan: str | None = None,   # 'relaxed_order'/'strict_order' (pgvector>=0.8): engine's own H1 mitigation
                 force_index: bool = False,           # SET enable_seqscan=off: deterministic ANN path for the H1 probe
                 defer_index: bool = False):          # scale path: bulk-load first, build HNSW once in flush()
        if not _HAVE_PG:
            raise RuntimeError("psycopg2 not installed; this adapter needs a live "
                               "Postgres+pgvector. The reference demo does not.")
        self.dim = dim
        self.deployed_correctly = deployed_correctly
        self.index = index
        self.index_config = {"index": index, "M": m, "ef_construction": ef_construction,
                             "ef_search": ef_search, "lists": lists, "probes": probes,
                             "deployed": "7a-correct" if deployed_correctly else "7b-misconfig"}
        self.iterative_scan = iterative_scan
        self.force_index = force_index
        self.defer_index = defer_index
        self._index_built = False
        if iterative_scan:
            self.index_config["iterative"] = iterative_scan
        if force_index:
            self.index_config["forced"] = True
        self.dsn = dsn or os.environ["RQ9_PG_DSN"]
        self.conn = psycopg2.connect(self.dsn); self.conn.autocommit = True
        self._setup(m, ef_construction, lists)

    def _setup(self, m, ef_construction, lists):
        with self.conn.cursor() as c:
            c.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            c.execute("SELECT extversion FROM pg_extension WHERE extname='vector';")
            self.version = (c.fetchone() or ["?"])[0]
            c.execute("DROP TABLE IF EXISTS rq9_mem;")
            c.execute(f"""CREATE TABLE rq9_mem(
                rid text PRIMARY KEY, tenant text NOT NULL,
                valid_from bigint NOT NULL, valid_until bigint NOT NULL,
                embedding vector({self.dim}));""")
            c.execute("CREATE INDEX ON rq9_mem(tenant);")
            self._vec_index_ddl = (
                f"CREATE INDEX ON rq9_mem USING hnsw (embedding vector_cosine_ops) "
                f"WITH (m={m}, ef_construction={ef_construction});"
                if self.index == "hnsw" else
                f"CREATE INDEX ON rq9_mem USING ivfflat (embedding vector_cosine_ops) "
                f"WITH (lists={lists});")
            if not self.defer_index:
                c.execute(self._vec_index_ddl)
                self._index_built = True

    def write(self, recs):
        rows = [(r.rid, r.tenant, r.valid_from, r.valid_until,
                 "[" + ",".join(f"{x:.6f}" for x in r.vector) + "]") for r in recs]
        with self.conn.cursor() as c:
            execute_values(c, "INSERT INTO rq9_mem VALUES %s ON CONFLICT (rid) "
                              "DO UPDATE SET embedding=EXCLUDED.embedding", rows)

    def supersede(self, rid, new, at):
        with self.conn.cursor() as c:
            c.execute("UPDATE rq9_mem SET valid_until=%s WHERE rid=%s", (at, rid))
        self.write([Record(new.rid, new.vector, new.tenant, at, T_OPEN)])

    def delete(self, rids):
        with self.conn.cursor() as c:
            c.execute("DELETE FROM rq9_mem WHERE rid = ANY(%s)", (list(rids),))

    def compact(self):
        with self.conn.cursor() as c:
            c.execute("VACUUM rq9_mem;")     # reclaim + index cleanup

    def retrieve(self, query, k, tenant, as_of=None):
        q = "[" + ",".join(f"{x:.6f}" for x in query) + "]"
        preds, args = [], []
        if tenant is not None and self.deployed_correctly:   # 7b drops this
            preds.append("tenant = %s"); args.append(tenant)
        if as_of is not None:
            preds.append("valid_from <= %s AND %s < valid_until"); args += [as_of, as_of]
        where = ("WHERE " + " AND ".join(preds)) if preds else ""
        with self.conn.cursor() as c:
            if self.force_index:
                c.execute("SET enable_seqscan = off;")
            if self.iterative_scan:
                try:
                    c.execute(f"SET hnsw.iterative_scan = {self.iterative_scan};")
                except Exception:
                    pass    # pgvector < 0.8: parameter absent
            if self.index == "hnsw":
                c.execute(f"SET hnsw.ef_search = {self.index_config['ef_search']};")
            else:
                c.execute(f"SET ivfflat.probes = {self.index_config['probes']};")
            c.execute(f"SELECT rid, 1-(embedding <=> %s::vector) AS s FROM rq9_mem "
                      f"{where} ORDER BY embedding <=> %s::vector LIMIT %s",
                      [q] + args + [q, k])
            return [Hit(rid, float(s)) for rid, s in c.fetchall()]

    def audit(self, rid):
        with self.conn.cursor() as c:
            c.execute("SELECT 1 FROM rq9_mem WHERE rid=%s", (rid,))
            return {"present": c.fetchone() is not None}

    def flush(self):
        with self.conn.cursor() as c:
            if self.defer_index and not self._index_built:
                # scale path: HNSW built once over the loaded table -- vastly
                # cheaper than incremental graph inserts at large N
                c.execute("SET maintenance_work_mem = '512MB';")
                c.execute(self._vec_index_ddl)
                self._index_built = True
            # Pin planner statistics (plan-flip lesson from runs 1-2).
            c.execute("ANALYZE rq9_mem;")

    def storage_bytes(self):
        with self.conn.cursor() as c:
            c.execute("SELECT pg_total_relation_size('rq9_mem');")
            return int(c.fetchone()[0])
