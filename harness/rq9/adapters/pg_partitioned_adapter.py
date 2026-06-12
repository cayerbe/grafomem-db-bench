"""
G3 probe adapter: epoch-partitioned pgvector ("pg-partitioned").

The gating experiment between RQ8 outcomes (c) and (b): can an ADAPTER-LAYER
fix recover cheap, correct as_of under supersession — without engine-native
bi-temporality? This adapter is that fix made literal:

  rq9p_cur     all rows with valid_until = T_OPEN (the current snapshot).
               The H2 sentinel doing real work: "current" becomes an exact-
               match indexable predicate. Own HNSW over ~N_logical rows.
  rq9p_e{v}    one table per epoch v, holding exactly the rows valid during
               [v*EPOCH, (v+1)*EPOCH). Own HNSW each, ~N_logical rows each.

retrieve(as_of=t) routes to rq9p_e{floor(t/EPOCH)} (falls back to cur for t
beyond the last epoch). The validity predicate `valid_from <= t < valid_until`
REMAINS in every query: routing is an optimization; the predicate is the
two-sided correctness guarantee. Leak must be 0.00 even if routing is wrong.

Placement rule (general, bounded): a row is placed in every epoch table its
interval overlaps, capped at max_epoch; open rows (valid_until = T_OPEN) are
additionally placed in rq9p_cur. On the epoch-aligned H4 corpus each closed
version lands in exactly one epoch; the tax is the cur duplication (~+1/D).
Arbitrary intervals imply multi-epoch placement (~2x bound for chain-shaped
data) — registered limitation, favorable-case probe.

Registered gate (decide BEFORE looking):
  GP1  as_of recall ~= the single-epoch (N_logical-row) graph baseline,
       INDEPENDENT of D  (H4 monolithic baseline: 0.04 @ D=16, ef16).
  GP2  p50 ~flat in D at single-epoch latency (~1-2 ms)
       (H4 exact-fallback baseline: 65 ms @ D=16).
  GP3  storage tax ~ +1/D on this corpus; total build <= monolithic build.
GP1+GP2 holding at D=16 => G3 closes at the adapter layer => outcome (c).
Either failing => first load-bearing engine-native gap => outcome (b) opens.
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

EPOCH = 100   # must match gmp_cost.h4_stress.EPOCH


def epochs_for(valid_from: int, valid_until: int, max_epoch: int) -> list[int]:
    """Epoch tables an interval must be placed in (pure function, unit-tested).
    Closed interval -> every epoch it overlaps. Open (T_OPEN) -> from its start
    epoch through max_epoch (plus cur, handled by caller)."""
    e0 = min(valid_from // EPOCH, max_epoch)   # clamp: a row must never be
    # lost from every epoch table; the in-query validity predicate guarantees
    # correctness even when clamping over-places.
    if valid_until >= T_OPEN:
        return list(range(e0, max_epoch + 1))
    e1 = (valid_until - 1) // EPOCH          # inclusive last epoch touched
    return list(range(e0, min(e1, max_epoch) + 1))


class PgPartitionedBackend:
    name = "pg-partitioned"
    version = "unknown"
    caps = Capabilities(physical_tenant_isolation=False, hard_delete=True,
                        native_bitemporal=False,   # the POINT: emulation, adapter-side
                        consults_tombstone_on_read=True,
                        consults_tenant_on_read=True)

    def __init__(self, dim: int, max_epoch: int,
                 m: int = 16, ef_construction: int = 64, ef_search: int = 40,
                 dsn: str | None = None):
        if not _HAVE_PG:
            raise RuntimeError("psycopg2 required (live Postgres+pgvector).")
        self.dim = dim
        self.max_epoch = max_epoch
        self.index_config = {"index": "hnsw-partitioned", "M": m,
                             "ef_construction": ef_construction,
                             "ef_search": ef_search, "epochs": max_epoch + 1}
        self._m, self._efc = m, ef_construction
        self.dsn = dsn or os.environ["RQ9_PG_DSN"]
        self.conn = psycopg2.connect(self.dsn); self.conn.autocommit = True
        self._tables = ["rq9p_cur"] + [f"rq9p_e{v}" for v in range(max_epoch + 1)]
        self._index_built = False
        with self.conn.cursor() as c:
            c.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            c.execute("SELECT extversion FROM pg_extension WHERE extname='vector';")
            self.version = (c.fetchone() or ["?"])[0]
            for t in self._tables:
                c.execute(f"DROP TABLE IF EXISTS {t};")
                c.execute(f"""CREATE TABLE {t}(
                    rid text PRIMARY KEY, tenant text NOT NULL,
                    valid_from bigint NOT NULL, valid_until bigint NOT NULL,
                    embedding vector({dim}));""")

    # ------------------------------------------------------------------ write
    def write(self, recs):
        per_table: dict[str, list] = {}
        for r in recs:
            row = (r.rid, r.tenant, r.valid_from, r.valid_until,
                   "[" + ",".join(f"{x:.6f}" for x in r.vector) + "]")
            for e in epochs_for(r.valid_from, r.valid_until, self.max_epoch):
                per_table.setdefault(f"rq9p_e{e}", []).append(row)
            if r.valid_until >= T_OPEN:
                per_table.setdefault("rq9p_cur", []).append(row)
        with self.conn.cursor() as c:
            for t, rows in per_table.items():
                execute_values(c, f"INSERT INTO {t} VALUES %s "
                                  f"ON CONFLICT (rid) DO NOTHING", rows)

    def supersede(self, rid, new, at):
        # close the old interval everywhere it lives; remove it from cur;
        # write the new open version (lands in its epochs + cur via write()).
        with self.conn.cursor() as c:
            for t in self._tables:
                c.execute(f"UPDATE {t} SET valid_until=%s WHERE rid=%s", (at, rid))
            c.execute("DELETE FROM rq9p_cur WHERE rid=%s", (rid,))
        self.write([Record(new.rid, new.vector, new.tenant, at, T_OPEN)])

    def delete(self, rids):
        with self.conn.cursor() as c:
            for t in self._tables:
                c.execute(f"DELETE FROM {t} WHERE rid = ANY(%s)", (list(rids),))

    # ------------------------------------------------------------------ flush
    def flush(self):
        with self.conn.cursor() as c:
            if not self._index_built:
                c.execute("SET maintenance_work_mem = '512MB';")
                for t in self._tables:
                    c.execute(f"CREATE INDEX ON {t} USING hnsw "
                              f"(embedding vector_cosine_ops) "
                              f"WITH (m={self._m}, ef_construction={self._efc});")
                self._index_built = True
            for t in self._tables:
                c.execute(f"ANALYZE {t};")

    # --------------------------------------------------------------- retrieve
    def _route(self, as_of: int | None) -> str:
        if as_of is None:
            return "rq9p_cur"                      # "now" semantics
        e = as_of // EPOCH
        return f"rq9p_e{e}" if e <= self.max_epoch else "rq9p_cur"

    def retrieve(self, query, k, tenant, as_of=None):
        table = self._route(as_of)
        q = "[" + ",".join(f"{x:.6f}" for x in query) + "]"
        preds, args = [], []
        if tenant is not None:
            preds.append("tenant = %s"); args.append(tenant)
        if as_of is not None:
            # routing is an optimization; the predicate is the guarantee
            preds.append("valid_from <= %s AND %s < valid_until")
            args += [as_of, as_of]
        else:
            preds.append("valid_until = %s"); args.append(T_OPEN)
        where = "WHERE " + " AND ".join(preds)
        with self.conn.cursor() as c:
            c.execute(f"SET hnsw.ef_search = {self.index_config['ef_search']};")
            c.execute(f"SELECT rid, 1-(embedding <=> %s::vector) AS s FROM {table} "
                      f"{where} ORDER BY embedding <=> %s::vector LIMIT %s",
                      [q] + args + [q, k])
            return [Hit(rid, float(s)) for rid, s in c.fetchall()]

    # ------------------------------------------------------------------ misc
    def audit(self, rid):
        with self.conn.cursor() as c:
            c.execute("SELECT 1 FROM rq9p_cur WHERE rid=%s", (rid,))
            return {"present": c.fetchone() is not None}

    def compact(self):
        with self.conn.cursor() as c:
            for t in self._tables:
                c.execute(f"VACUUM {t};")

    def storage_bytes(self):
        with self.conn.cursor() as c:
            total = 0
            for t in self._tables:
                c.execute(f"SELECT pg_total_relation_size('{t}');")
                total += int(c.fetchone()[0])
            return total
