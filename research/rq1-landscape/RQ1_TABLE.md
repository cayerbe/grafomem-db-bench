# RQ1 — Landscape Table (first pass)

**Convention:** every cell carries a source class — [OBSERVED] (we ran it),
[DOCUMENTED] (vendor primary source + URL), [REPORTED] (third party), [HYP]
(unverified). No cell enters on a vendor blog sentence alone. License is a
GATE (extend/fork feasibility), not a trailing attribute.

**Scope of first pass (per revised sequencing):** the two RQ7 engines are
PRE-FILLED below from our own observed results — a legitimate head start.
Remaining rows are the reading task. Second pass extends to the full §5
inventory.

## Tier 1 — instrumented engines (pre-filled, [OBSERVED] unless noted)

### pgvector (+ PostgreSQL)
| dimension | finding | class |
|---|---|---|
| Architecture | Postgres extension; HNSW + IVFFlat; heap rows + per-index graph | [DOCUMENTED] |
| Filtering | **Post-filter**: predicate applied after index scan; candidate-budget starvation `~ef·sel/k` (F-PG-6, F-S-1); plan-mediated (flips index↔exact with stats/ef, F-PG-8); mitigation `iterative_scan` recovers partially, non-scaling ceiling (F-S-2/6) | [OBSERVED] |
| Multi-tenancy | Logical (WHERE clause); 7a holds (leak 0.00), 7b total silent leak (0.85–0.86); by-convention, not structural | [OBSERVED] |
| Deletion | Honest on read (MVCC, gone@1, leak 0.00 at every N to 1e6); physical reclaim deferred to VACUUM | [OBSERVED] |
| Temporal | No native bi-temporality; emulated as_of pays twofold tax (F-H4); **epoch-partitioned adapter recovers 0.97 @ 1.8 ms at D=16** (G3 probe) | [OBSERVED] |
| Consistency | Postgres MVCC; not stress-probed (W10 open) | [DOCUMENTED] |
| Audit/attestation | Inherits Postgres (pgaudit-class); no vector-specific attestation; no receipts/erasure certs | [DOCUMENTED-absent] |
| Deployment | Extension; self-host / any managed Postgres | [DOCUMENTED] |
| **License (gate)** | PostgreSQL License (permissive) — fork/extend feasible | [DOCUMENTED] |
| Cost notes | Storage amplification 3.66–3.70× stable across 3 orders of magnitude; build cliff 8.2k→1.33k vec/s at 1e6; shm_size requirement for parallel build | [OBSERVED] |

### Qdrant
| dimension | finding | class |
|---|---|---|
| Architecture | Rust; segmented HNSW; per-segment optimizer; mark-deleted + deferred reclaim | [DOCUMENTED] |
| Filtering | **Planning engine**: per-segment cardinality choice between filtered-HNSW traversal and exact fallback, governed by full_scan_threshold (per-segment — F-S-0 model, prediction confirmed at 1e6); filter-aware traversal holds where post-filter starves (0.91 vs 0.04 at ef16/1e6, F-S-3) BUT collapses structurally under extreme selective+clustered filters when forced (0.00/OVER_RESTRICTS at D=16 — planner is load-bearing, F-H4) | [OBSERVED] |
| Multi-tenancy | Logical (payload filter); same 7a-PASS / 7b-LEAK shape as pgvector | [OBSERVED] |
| Deletion | Honest on read with graph live (mark-deleted excluded pre-reclaim, gone@1 to 1e6); claims-but-leaks NOT reproduced | [OBSERVED] |
| Temporal | No native bi-temporality; **with integer payload indexes on validity fields: exact as_of 1.00 @ ~2 ms flat in D** (F-Q2-0/2; H4's 64–84 ms was our instrument's unindexed-range confound, owned) | [OBSERVED] |
| Consistency | wait=true ack semantics observed; W10 (snapshot/restore reviving deletes) open | [OBSERVED]/[HYP] |
| Audit/attestation | Native logging = metrics/telemetry/system; Cloud audit logs (enterprise, recent); third party notes no tamper protection on logs; no receipts/erasure certs | [DOCUMENTED]+[REPORTED] |
| Deployment | Self-host (docker), Qdrant Cloud, hybrid | [DOCUMENTED] |
| **License (gate)** | Apache-2.0 core; managed features commercial — fork/extend of core feasible | [DOCUMENTED] |
| Cost notes | Build 15–20k vec/s stable to 1e6; storage_bytes estimate-class only [REPORTED-self]; payload indexes on every filterable field are MANDATORY (the F-Q2-0 lesson) | [OBSERVED] |

## Tier 2 — swept 2026-06-12 (assistant web sweep; owner spot-check complete)

Tag legend: [DOCUMENTED] = vendor primary source, URL given. [REPORTED] =
third party. [DOCUMENTED] = filled from stable prior knowledge, flagged
for the owner spot-check pass. Cells not load-bearing for the paper are
deliberately light.

### Full rows — architecture-class representatives

#### Pinecone (managed/serverless)
| dimension | finding | class + source |
|---|---|---|
| Architecture | Proprietary serverless; index = JSON documents, dense/sparse vector fields + auto-indexed metadata, object-storage-backed | [DOCUMENTED] docs.pinecone.io/guides/index-data/indexing-overview |
| Filtering | Metadata filter applied at query time limits search to matching records ("single-stage" in vendor terms); all metadata auto-indexed, flat key-value only | [DOCUMENTED] same URL |
| Multi-tenancy | **Namespaces**: partition of an index; "queries and other operations confined to a single namespace… as if separate indexes"; one namespace per query, no cross-namespace search; vendor recommends namespaces over per-tenant indexes | [DOCUMENTED] docs.pinecone.io/troubleshooting/use-namespaces-instead-of-several-indexes + /namespaces-vs-metadata-filtering |
| Deletion | Delete by ID / by namespace; serverless freshness window applies | [DOCUMENTED] docs.pinecone.io/guides/manage-data/delete-data |
| Temporal | None native; timestamps as filterable metadata only | [DOCUMENTED] |
| Audit/attestation | Audit logs: Enterprise tier, ~30-min batched JSON to S3, control-plane scope (H8 sweep row) | [DOCUMENTED] docs.pinecone.io/guides/production/security-overview |
| Deployment | Managed SaaS only | [DOCUMENTED] |
| **License (gate)** | Proprietary service — **fork/extend gate FAILS** | [DOCUMENTED] pinecone.io terms |
| §9 note | Namespace = closest managed analog to scope-by-construction (one namespace per query), BUT namespace selection is still a per-call argument → the 7b omission class applies to the default namespace | — |

#### Weaviate (open-source server)
| dimension | finding | class + source |
|---|---|---|
| Architecture | Go server; per-shard HNSW + colocated inverted index; LSM-style buckets per filterable property | [DOCUMENTED] docs.weaviate.io/weaviate/concepts/data; weaviate.io/blog/weaviate-multi-tenancy-architecture-explained |
| Filtering | **Pre-filtering**: inverted index builds an allow-list, passed into HNSW traversal (only allow-listed ids enter results); two strategies: `sweeping` and ACORN-based; small filters routed to brute force via `flatSearchCutOff` — i.e. Weaviate ALSO has a cardinality-routed exact fallback (planner-class) | [DOCUMENTED] docs.weaviate.io/weaviate/concepts/filtering; weaviate.io/blog/speed-up-filtered-vector-search |
| Multi-tenancy | **Native, shard-per-tenant**: "each tenant is stored on a separate shard… data in one tenant is not visible to another"; tenant *key required on every CRUD op* (not a filter); per-tenant dedicated vector index; tenant states ACTIVE/INACTIVE/OFFLOADED; 50k+ shards/node claimed | [DOCUMENTED] docs.weaviate.io/weaviate/manage-collections/multi-tenancy; /concepts/data |
| Deletion | Object deletes; **tenant deletion = shard deletion** ("compliant deletes" — all tenant data goes with the shard) | [DOCUMENTED] /concepts/data; weaviate.io/blog/multi-tenancy-vector-search |
| Temporal | None native; optional `indexTimestamps` inverted index on internal timestamps | [DOCUMENTED] docs.weaviate.io/weaviate/config-refs/collections |
| Audit/attestation | RBAC authorization-decision logs (H8 sweep row); no receipts/certs found | [DOCUMENTED] docs.weaviate.io/deploy/configuration/logging |
| Deployment | Self-host / Weaviate Cloud | [DOCUMENTED] |
| **License (gate)** | BSD-3-Clause core — **gate passes** | [DOCUMENTED] github.com/weaviate/weaviate LICENSE |
| §9 note | **The market's strongest answer to our 7b finding**: shard-per-tenant with mandatory tenant key per operation is structurally closer to scope-by-construction than any filter-convention engine. (Verified: an omitted tenant key throws a strict error; it does not silently default.) |

#### Milvus / Zilliz (open-source server / managed)
| dimension | finding | class + source |
|---|---|---|
| Architecture | Distributed; segments; multiple index types (HNSW, IVF, DiskANN) | [DOCUMENTED] milvus.io/docs |
| Filtering | Filtered search with boolean expressions over scalar fields; per-segment | [DOCUMENTED] milvus.io/docs/use-partition-key.md |
| Multi-tenancy | **Four documented levels**: database- (≤64 tenants, "enterprise-grade isolation", per-tenant RBAC), collection-, partition-, and **partition-key**-oriented (tenant field as partition key; Partition Key Isolation builds a separate index per key group and restricts search scope to it) | [DOCUMENTED] milvus.io/docs/multi_tenancy.md; /use-partition-key.md |
| Deletion | Delete by filter expr; mark-delete + compaction (vendor advises partition-key-scoped deletes to reduce "write amplification during compaction") — the deferred-reclaim class, like Qdrant | [DOCUMENTED] /use-partition-key.md (compaction note); mechanism page [DOCUMENTED] milvus.io/docs/delete-entities.md |
| Temporal | None native; Milvus has internal `timestamp`/time-travel features historically (deprecated in 2.3+): **verified — record-level time travel shipped, then deprecated in v2.3.0** ("due to its inactivity and the challenges it poses to the architecture design"); residual SuffixSnapshot layer removed in v2.6.15. A documented case of a vector engine retiring native temporality — citable beside §5.5's conclusion. Retention also collided with compaction (issue #18748) — RQ6's temporal-vs-deletion tension in the wild. | [DOCUMENTED] milvus.io/docs/v2.3.x/release_notes.md; milvus.io/docs/release_notes.md (v2.6.15); github.com/milvus-io/milvus/issues/18748 — re-verified assistant 2026-06-12 |
| Audit/attestation | Milvus access logs; Zilliz Cloud audit logs (Enterprise) (H8 sweep rows) | [DOCUMENTED] milvus.io/docs/configure_access_logs.md; docs.zilliz.com/docs/audit-logs |
| Deployment | Self-host (standalone/cluster) / Zilliz Cloud | [DOCUMENTED] |
| **License (gate)** | Apache-2.0 — **gate passes** | [DOCUMENTED] github.com/milvus-io/milvus LICENSE |
| §9 note | Partition-Key Isolation = a third structural answer to scoped search (index-per-tenant-group), between filter-convention and shard-per-tenant. |

#### Vespa (open-source server)
| dimension | finding | class + source |
|---|---|---|
| Architecture | Java/C++; content nodes; HNSW for indexed mode; document model with tensors | [DOCUMENTED] docs.vespa.ai |
| Filtering | **Pre-filtering default**: filter-matching doc-ID list constrains HNSW traversal; **automatic fallback to exact search when the filter hit-ratio is below `approximate-threshold`** (cardinality-routed planner, like Qdrant/Weaviate); post-filtering available and tunable | [DOCUMENTED] blog.vespa.ai/constrained-approximate-nearest-neighbor-search/ |
| Multi-tenancy | **Streaming mode**: user/group id is part of the document id; data co-located per user on disk; queries scoped to the group are **exact brute-force over the user's subset, no ANN index at all** — vendor's argument: ANN is unsuited for personal-data search (strong filters, can't-miss recall) | [DOCUMENTED] docs.vespa.ai/en/streaming-search.html; blog.vespa.ai/announcing-vector-streaming-search/ |
| Deletion | Document removes; streaming mode has no index residue by construction (no index) | [DOCUMENTED]/[DOCUMENTED] |
| Temporal | None native | [DOCUMENTED] |
| Audit/attestation | Access logging; nothing attestation-class found (H8 Part B) | owner to confirm |
| Deployment | Self-host / Vespa Cloud | [DOCUMENTED] |
| **License (gate)** | Apache-2.0 — **gate passes** | [DOCUMENTED] github.com/vespa-engine/vespa |
| §9 note | Streaming mode is the market's *third architecture class for governed memory*: scope-first, exact-always, index-free — philosophically the closest existing system to "memory queries are small, scoped, and must be exact". Directly citable against our F-S-4/F-S-7 finding that exact search wins at scoped cardinalities. |

### Light rows (filtering / deletion-or-tenancy / license)

| engine | filtering architecture | deletion / tenancy note | license (gate) |
|---|---|---|---|
| Chroma (embedded/server) | metadata `where` filters + document filters over HNSW | collection-scoped; delete by id/where | Apache-2.0 — passes [DOCUMENTED] |
| Turbopuffer (managed) | exact attribute indexes, ANN-aware "native filtering" for high-recall filtered queries [DOCUMENTED turbopuffer.com/docs/concepts] | **namespace = object-storage prefix** (namespace-per-tenant/-codebase pattern, e.g. Cursor); durable writes to object storage; documented staleness windows (~100 ms failover; up to ~1 h after >128 MiB outstanding writes) [DOCUMENTED /docs/architecture, /docs/guarantees] | Proprietary SaaS — FAILS |
| LanceDB / Lance (embedded) | scalar-filtered ANN over Lance columnar format | **dataset-level versioning/time-travel in Lance format** — nearest existing thing to temporal, but dataset-granular, not record-level bi-temporal | Apache-2.0 — passes [DOCUMENTED] |
| sqlite-vec (embedded) | brute-force exact scan (vec0); metadata via aux columns/partition keys; no ANN index | embedded single-file; deletion = SQL delete | Apache-2.0/MIT dual — passes [DOCUMENTED] |
| DuckDB-VSS (embedded) | experimental HNSW extension | **persistence caveat CURRENT**: HNSW limited to in-memory DBs unless `hnsw_enable_experimental_persistence`; WAL recovery unimplemented for custom indexes (crash ⇒ possible data loss/index corruption). Also lazy deletion — DELETE marks entries, removal via manual `PRAGMA hnsw_compact_index` (deferred-reclaim class). [DOCUMENTED] duckdb.org/docs/current/core_extensions/vss — re-verified assistant 2026-06-12 | MIT — passes [DOCUMENTED] |
| Elastic vector (server) | Lucene HNSW; filtered kNN (filter constrains graph search); min-similarity option | mark-delete via Lucene segments + merge | **SSPL/Elastic License (AGPL option since 2024) — gate RESTRICTED/fails for proprietary extension** [DOCUMENTED — license history widely documented; REPORTED oneuptime.com comparison] |
| OpenSearch k-NN (server) | Lucene/Faiss engines support filtered kNN; NMSLIB engine does not | as Elastic (Lucene) | Apache-2.0 — passes [REPORTED] |
| FAISS / hnswlib / usearch (libraries, baselines) | library-level; no scoping primitives — filtering is the CALLER'S problem (ID-selector/predicate callbacks at best) | remove_ids/mark_deleted; no tenancy, no temporal — by design out of scope | MIT / Apache-2.0 / Apache-2.0 — pass [DOCUMENTED] |
| SQL/cloud secondary tier (one line) | Azure AI Search exposes `vectorFilterMode` = preFilter/postFilter/strictPostFilter per query [DOCUMENTED learn.microsoft.com/azure/search/vector-search-filters]; AlloyDB Omni's optimizer cost-routes pre/post/inline filtering [DOCUMENTED cloud.google.com AlloyDB docs] — i.e., the pre/post/planner axis is now a first-class, user-visible knob in cloud SQL offerings | — | n/a (managed) |

### Descoped (with reason)

**mem0, Zep, MemCP, LangGraph/LlamaIndex memory stores:** adjacent memory
*layers*, not engines — they sit on the DBs above and inherit those
guarantees while adding their own scoping/summarization/forgetting failure
surface. Untested here; named in the paper (§8/§9) as the likeliest habitat
of claims-but-leaks in the wild and explicit future work. Running the 7a/7b
suite against them is the designated follow-on study.

### Cross-cutting observation for §9 (the sweep's one synthesis)

Every server-class engine swept has converged on some form of
**cardinality-routed filtered search** — Qdrant's full_scan_threshold,
Weaviate's flatSearchCutOff + ACORN, Vespa's approximate-threshold exact
fallback, Milvus's partition-key index routing, Azure's explicit
vectorFilterMode — while pgvector (a general-purpose planner with ANN bolted
on) and the bare libraries leave the problem to the caller. Our two
instrumented engines are therefore fair representatives of the two poles of
a documented industry axis, and the planner-class behavior we measured on
Qdrant generalizes in kind (not in numbers) across the class. Tenancy
likewise spans a documented spectrum: filter-convention (pgvector, Qdrant,
Milvus-filter) → partition/namespace (Pinecone, Milvus partition-key,
Turbopuffer) → shard-per-tenant with mandatory key (Weaviate) →
scope-first index-free (Vespa streaming). The 7b omission class applies in
weakening degrees along that spectrum — a per-call scope argument exists in
all but the last.

**Post-signature completion note (2026-06-12):** of the cells upgraded at
signature, four carried search evidence in the verification session (LOCOMO,
ACORN, SIEVE refs; Weaviate omitted-tenant-key ⇒ strict error, no silent
default); the two content cells flagged "VERIFY current" (Milvus temporal,
DuckDB-VSS persistence) were re-verified by assistant against vendor docs the
same day (sources in their cells); remaining upgrades are repo-LICENSE
stable-fact cells cited to their LICENSE files.

**Done when:** owner spot-check pass over the [DOCUMENTED] cells (~10 URLs, ~30 min) + sign here: AG 2026-06-12

