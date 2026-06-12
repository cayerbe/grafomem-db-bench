# RQ1 — Landscape inventory

Source-tagged table per engine (§5 of the charter): architecture, filtering
(pre/post/single-stage, index- vs app-level), multi-tenancy (logical/namespace/
physical), deletion semantics, temporal/versioning, consistency/concurrency,
attestation/audit, deployment, **license (a gate, not a cell)**. Every cell
carries [OBSERVED]/[DOCUMENTED]/[REPORTED]/[HYPOTHESIS].

Critical-path note: the 2-week estimate is optimistic ~2-3x; first pass should
cover the locally-runnable engines that feed RQ7 (pgvector, Qdrant), full breadth second.
