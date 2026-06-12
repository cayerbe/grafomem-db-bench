#!/usr/bin/env python3
"""
Numbers audit v2 (audit_numbers.py) — resolves every numeric claim in the
paper draft to its canonical ledger row, checks the value, emits a row hash.

v2 changes (after the 2026-06-12 first run):
- Reads the JSON ledgers (which carry ALL fields incl. index_config); the
  commercial/scale CSVs omit index_config and cannot disambiguate 7a/7b or ef.
- Selectors: exact match on `engine`, then needle groups — each group is a
  tuple of alternatives, ANY of which must appear somewhere in the row.
- Self-diagnosing failures: a no-match claim prints the nearest same-engine
  candidate rows into the report, so a selector fix is visible from output.

Run from the repo root:
    python3 harness/rq9/audit_numbers.py
Output: research/paper/AUDIT_RESOLVED.md ; exit 1 on any failure.
"""
import csv, hashlib, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RES = os.path.join(ROOT, "research", "rq9-cost-ledger", "results")
CONF = os.path.join(ROOT, "research", "rq7-conformance")
OUT = os.path.join(ROOT, "research", "paper", "AUDIT_RESOLVED.md")

L = {
    "commercial": os.path.join(CONF, "commercial_ledger"),
    "scale": os.path.join(RES, "scale_ledger"),
    "h4": os.path.join(RES, "h4_ledger"),
    "g3": os.path.join(RES, "g3_ledger"),
    "g3q": os.path.join(RES, "g3q_ledger"),
}

# (claim_id, draft_ref, ledger, engine_exact, needle_groups, field, expect, tol)
# needle group = tuple of alternatives; any one matching anywhere in the row
# satisfies the group; ALL groups must be satisfied.
CLAIMS = [
    # §4 — conformance (Table 1)
    ("C1", "§4.2 7a scoped leak 0.00 (pgvector)", "commercial", "pgvector",
     [("tenant_scoped",), ("deployed=7a", "7a-correct", "deployed_correctly=True")],
     "leak_rate", 0.0, 0.005),
    ("C2", "§4.3 7b leak 0.85–0.86 (pgvector)", "commercial", "pgvector",
     [("tenant_scoped",), ("deployed=7b", "7b-misconfig", "deployed_correctly=False")],
     "leak_rate", (0.845, 0.875), None),   # 2dp claim -> half-ulp bounds (0.8499.. prints as 0.85)
    ("C3", "§4.3 7b in-tenant recall 0.14 (pgvector)", "commercial", "pgvector",
     [("tenant_scoped",), ("deployed=7b", "7b-misconfig", "deployed_correctly=False")],
     "recall_at_k", 0.14, 0.02),
    ("C4", "§4.1 W6 gone@1 (pgvector 7a)", "commercial", "pgvector",
     [("delete.honest",), ("deployed=7a", "7a-correct", "deployed_correctly=True")],
     "ops_until_gone", 1, 0),
    ("C5", "§4.1 W6 gone@1 (qdrant 7a)", "commercial", "qdrant",
     [("delete.honest",), ("deployed=7a", "7a-correct", "deployed_correctly=True")],
     "ops_until_gone", 1, 0),
    ("C6", "§4.3 7b leak (qdrant)", "commercial", "qdrant",
     [("tenant_scoped",), ("deployed=7b", "7b-misconfig", "deployed_correctly=False")],
     "leak_rate", (0.85, 0.87), None),
    # §5.1–5.3 — scale (Table 3)
    ("S1", "§5.1 pgvector scoped 0.04 @ 1e5 ef16", "scale", "pgvector",
     [("tenant_scoped",), ("100000", "N=100000", "1e5"), ("ef_search=16", "ef=16")],
     "recall_at_k", 0.04, 0.015),
    ("S2", "§5.1 pgvector scoped 0.31 @ 1e5 ef256", "scale", "pgvector",
     [("tenant_scoped",), ("100000", "N=100000", "1e5"), ("ef_search=256", "ef=256")],
     "recall_at_k", 0.31, 0.02),
    ("S3", "§5.1 iter CEILING 0.43 @ 1e6 (max across ef sweep)", "scale", "pgvector-iter",
     [("tenant_scoped",), ("1000000", "N=1000000", "1e6")],
     "max:recall_at_k", (0.40, 0.46), None),
    ("S4", "§5.2 qdrant-forced scoped 0.91 @ 1e5 ef16", "scale", "qdrant-forced",
     [("tenant_scoped",), ("100000", "N=100000", "1e5"), ("hnsw_ef=16", "ef_search=16", "ef=16")],
     "recall_at_k", 0.91, 0.03),
    ("S5", "§5.2 qdrant default scoped 1.00 @ 1e6", "scale", "qdrant",
     [("tenant_scoped",), ("1000000", "N=1000000", "1e6")],
     "recall_at_k", 1.00, 0.005),
    ("S6", "§5.2 qdrant default scoped p50 1.7–1.8ms @ 1e6", "scale", "qdrant",
     [("tenant_scoped",), ("1000000", "N=1000000", "1e6")],
     "p50_ms", (1.5, 2.1), None),
    ("S7", "§5.2 F-S-0 qdrant unfiltered 0.14 @ 1e6 ef16", "scale", "qdrant",
     [("unfiltered",), ("1000000", "N=1000000", "1e6"), ("hnsw_ef=16", "ef_search=16", "ef=16")],
     "recall_at_k", 0.14, 0.03),
    ("S8", "§5.3 pgvector unfiltered 0.47 @ 1e6 ef256", "scale", "pgvector",
     [("unfiltered",), ("1000000", "N=1000000", "1e6"), ("ef_search=256", "ef=256")],
     "recall_at_k", 0.47, 0.03),
    ("S9", "§5.3 build cliff: pgvector 1.33k vec/s @ 1e6", "scale", "pgvector",
     [("ingest.build", "build"), ("1000000", "N=1000000", "1e6")],
     "throughput_ops_s", (1200, 1500), None),
    ("S10", "§5.3 qdrant build 15.6k vec/s @ 1e6", "scale", "qdrant",
     [("ingest.build", "build"), ("1000000", "N=1000000", "1e6")],
     "throughput_ops_s", (14500, 17000), None),
    # §5.4 — supersession (Table 4)
    ("H1", "§5.4 pgvector D=16 as_of_mid ef16 = 0.04", "h4", "pgvector",
     [("as_of_mid",), ("ef=16 ",), ("D=16",)], "recall_at_k", 0.04, 0.015),
    ("H2", "§5.4 pgvector D=16 as_of_mid ef256 = 0.31", "h4", "pgvector",
     [("as_of_mid",), ("ef=256",), ("D=16",)], "recall_at_k", 0.31, 0.02),
    ("H3", "§5.4 pgvector D=4 ef16 = 0.20", "h4", "pgvector",
     [("as_of_mid",), ("ef=16 ",), ("D=4",)], "recall_at_k", 0.20, 0.02),
    ("H4c", "§6 confounded qdrant D=16 mid p50 ~65ms", "h4", "qdrant",
     [("as_of_mid",), ("ef=64",), ("D=16",)], "p50_ms", (60, 70), None),
    ("H5", "§4.4 forced D=16 = 0.00 OVER_RESTRICTS (ef64)", "h4", "qdrant-forced",
     [("as_of_mid",), ("ef=64",), ("D=16",)], "recall_at_k", 0.0, 0.005),
    ("H6", "§4.4 forced D=16 leak 0.00", "h4", "qdrant-forced",
     [("as_of_mid",), ("ef=64",), ("D=16",)], "leak_rate", 0.0, 0.005),
    # §5.5 — closures (Table 5)
    ("G1", "§5.5 pg-partitioned D=16 mid ef256 = 0.97", "g3", "pg-partitioned",
     [("as_of_mid",), ("ef=256",), ("D=16",)], "recall_at_k", 0.97, 0.015),
    ("G2", "§5.5 pg-partitioned D=16 mid ef256 p50 = 1.8ms", "g3", "pg-partitioned",
     [("as_of_mid",), ("ef=256",), ("D=16",)], "p50_ms", (1.4, 2.2), None),
    ("G3", "§5.5 pg-partitioned D=16 ef16 ≈ D=1 baseline", "g3", "pg-partitioned",
     [("as_of_mid",), ("ef=16 ",), ("D=16",)], "recall_at_k", 0.42, 0.02),
    ("Q1", "§5.5/§6 qdrant-rangeidx D=16 = 1.00", "g3q", "qdrant-rangeidx",
     [("as_of_mid",), ("ef=256",), ("D=16",)], "recall_at_k", 1.00, 0.005),
    ("Q2", "§6 rangeidx D=16 p50 1.5–3.4ms", "g3q", "qdrant-rangeidx",
     [("as_of_mid",), ("ef=16 ",), ("D=16",)], "p50_ms", (1.2, 3.8), None),
    ("Q3", "§5.5 qdrant-partitioned moot: 1.00", "g3q", "qdrant-partitioned",
     [("as_of_mid",), ("ef=16 ",), ("D=16",)], "recall_at_k", 1.00, 0.005),
]


def load(stem):
    """Prefer the JSON ledger (full fields); fall back to CSV."""
    jp, cp = stem + ".json", stem + ".csv"
    if os.path.exists(jp):
        with open(jp) as f:
            doc = json.load(f)
        return [{k: ("" if v is None else v) for k, v in r.items()}
                for r in doc.get("ledger", [])], "json"
    if os.path.exists(cp):
        with open(cp, newline="") as f:
            return list(csv.DictReader(f)), "csv"
    return None, None


def haystack(r):
    return " | ".join(f"{k}={r[k]}" for k in sorted(r)).lower()


def match(rows, engine, groups, all_matches=False):
    out = []
    for r in rows:
        if str(r.get("engine", "")).strip() != engine:
            continue
        hay = haystack(r)
        if all(any(alt.lower() in hay for alt in grp) for grp in groups):
            if not all_matches:
                return r
            out.append(r)
    return out if all_matches else None


def near(rows, engine, n=3):
    out = []
    for r in rows:
        if str(r.get("engine", "")).strip() == engine:
            brief = {k: r.get(k) for k in ("scenario", "index_config", "notes") if k in r}
            out.append(str(brief)[:220])
            if len(out) >= n:
                break
    return out


def row_hash(r):
    line = "|".join(f"{k}={r[k]}" for k in sorted(r))
    return hashlib.sha256(line.encode()).hexdigest()[:16]


def check(val, expect, tol):
    try:
        v = float(val)
    except (TypeError, ValueError):
        return False, "non-numeric"
    if isinstance(expect, tuple):
        return (expect[0] <= v <= expect[1]), f"{v:g} in [{expect[0]:g},{expect[1]:g}]"
    return (abs(v - expect) <= tol), f"{v:g} vs {expect:g}±{tol:g}"


def main():
    ledgers = {}
    lines = ["# Numbers Audit — RESOLVED (v2, JSON-backed)", "",
             "Generated by `harness/rq9/audit_numbers.py`. Row hash pins the",
             "exact ledger row each paper claim resolves to.", ""]
    for name, stem in L.items():
        rows, kind = load(stem)
        if rows is None:
            lines.append(f"**MISSING ledger {name}** ({stem}.json/.csv)")
        else:
            ledgers[name] = rows
            lines.append(f"- {name}: {len(rows)} rows ({kind})")
    lines += ["", "| claim | draft ref | ledger | row sha256/16 | check | status |",
              "|---|---|---|---|---|---|"]
    failures, diags = 0, []
    for cid, ref, lg, engine, groups, field, expect, tol in CLAIMS:
        rows = ledgers.get(lg)
        if rows is None:
            lines.append(f"| {cid} | {ref} | {lg} | — | ledger missing | **FAIL** |")
            failures += 1
            continue
        if field.startswith("max:"):
            f0 = field[4:]
            ms = [m for m in match(rows, engine, groups, all_matches=True)
                  if str(m.get(f0, "")) not in ("", "None")]
            r = max(ms, key=lambda m: float(m[f0])) if ms else None
            field_eff = f0
        else:
            r = match(rows, engine, groups)
            field_eff = field
        if r is None:
            lines.append(f"| {cid} | {ref} | {lg} | — | no row matched | **FAIL** |")
            failures += 1
            diags.append((cid, lg, engine, groups, near(rows, engine)))
            continue
        ok, detail = check(r.get(field_eff), expect, tol)
        status = "PASS" if ok else "**FAIL**"
        failures += (0 if ok else 1)
        lines.append(f"| {cid} | {ref} | {lg} | `{row_hash(r)}` | {field_eff}: {detail} | {status} |")
    lines += ["", f"**Result: {len(CLAIMS)-failures}/{len(CLAIMS)} claims resolved and passing.**"]
    if diags:
        lines += ["", "## No-match diagnostics (nearest same-engine rows)"]
        for cid, lg, engine, groups, cands in diags:
            lines.append(f"- **{cid}** [{lg} / {engine}] needles={groups}")
            for c in cands:
                lines.append(f"    - {c}")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
