# PROVENANCE — registered predictions and audit trail

This public artifact was cut from a private working repository at
commit `c9315c73d67e39010fb3a3e973d9817cc7823199` (2026-06-12). In that repository, every registered
prediction was committed BEFORE the run that adjudicated it. The
commits below pin that ordering; the private history can be opened
to any reviewer on request.

## Prediction / gate / adjudication commits
```
91ab651  2026-06-12  RQ7: H1 mechanism confirmed (plan text + probe + ledger agree); iterative_scan mitigation 0.25->0.94; CSV/console now expose ann-vs-plain per row
c0cab59  2026-06-12  N-sweep: H1 escape-hatch closes at 100k (F-S-1); mitigation price+ceiling (F-S-2); cross-engine contrast holds (F-S-3); per-segment threshold model after failed prediction (F-S-0)
fc79e58  2026-06-12  RQ8: H1-H10 revisit (exit criterion 4) + memo skeleton with gap table, pre-stated leans and falsifiers
0e45c43  2026-06-12  1e6: F-S-0 prediction CONFIRMED; mitigation non-scaling (F-S-6); pgvector dominated by exact at dim64 (F-S-7); 3.66x storage constant (F-S-8); G6 falsifier did not fire (F-S-9)
d47fb7e  2026-06-12  1e6: F-S-0 prediction CONFIRMED; mitigation non-scaling (F-S-6); pgvector dominated by exact at dim64 (F-S-7); 3.66x storage constant (F-S-8); G6 falsifier did not fire (F-S-9)
3e84791  2026-06-12  H4-stress instrument (supersession chains, near-duplicate adversarial versions); H8 sweep DRAFT (provisionally confirmed, pending verification)
75672ae  2026-06-12  H4-stress: twofold bi-temporal tax; forced filtered-HNSW collapse (P2 half-failed); G3 falsifier FIRED — epoch-partitioning probe is now the gating experiment
03c477e  2026-06-12  G3 gating probe: epoch-partitioned pgvector adapter (sentinel current-snapshot + per-epoch HNSW, adapter-side routing); gate GP1-GP3 registered
4a13473  2026-06-12  RQ8 MEMO: outcome (c) — gate fired, G3 closed at adapter layer (0.97@1.8ms vs 0.31 monolithic / 64ms fallback); recommendation H8-invariant; skeleton superseded, audit trail retained
8cacf4e  2026-06-12  Qdrant Q2 probe: rangeidx confound test (QP0) + collection-per-epoch partitioned variant (QP1/QP2)
f49befa  2026-06-12  Q2 resolved: adopt Qdrant (1.00@2ms rangeidx, F-Q2-2); H4 qdrant latency CONFOUND owned (F-Q2-0, memo erratum); partitioning moot on Qdrant
f12654f  2026-06-12  R0 exit pack: RQ1 scaffold (Tier-1 pre-filled OBSERVED), H8 sign-off checklist, exit tracker, Cloud flow-back context
78c78ce  2026-06-12  R0 EXITED (carry-forwards: RQ1→related-work, H8→pre-pub gate); paper outline: 'The Guarantees Hold, the Costs Diverge'
4d7a1ec  2026-06-12  Paper draft v0.1: §3 Method, §4 Guarantees, §5 Costs, §6 Confound, §8 Limitations skeleton + scoping guide & journal rerun spec
7ed0349  2026-06-12  H8 VERIFIED: confirmed — audit logs everywhere, attestation nowhere
681621c  2026-06-12  H8 verified docs corrected; hypotheses scorecard final; manuscript §1-§10 complete
b48c4b0  2026-06-12  Numbers audit v2.1: 28/28 — every paper figure resolved to a hashed ledger row
d7860f5  2026-06-12  R0 FORMALLY EXITED: RQ1 signed + 2 flagged cells re-verified; exit recorded; public-artifact cut script
```

## Full history shape
```
dfec9e0  2026-06-12  R0: charter, RQ9 cost-ledger harness + spec + observed results
7b78ab3  2026-06-12  Silence spurious Apple-Silicon BLAS FP warnings; os.cpu_count fallback; widen ledger column
a321e04  2026-06-12  RQ7 engine 1 (pgvector): findings + canonical ledger; Qdrant path
ad4b6af  2026-06-12  RQ7: H1 under-retrieval observed (F-PG-6); fix Qdrant indexing threshold; pin pg planner; H1 diagnostic
91ab651  2026-06-12  RQ7: H1 mechanism confirmed (plan text + probe + ledger agree); iterative_scan mitigation 0.25->0.94; CSV/console now expose ann-vs-plain per row
d039e12  2026-06-12  RQ7: Qdrant ANN confirmed (indexed=4000); H1 cross-engine contrast (F-QD-3); W6 honest on target architecture (F-QD-4); standing assessment favors outcome (e) pending scale
db8b7bb  2026-06-12  RQ9 N-sweep instrument: scale corpus/oracle, checkpointed driver, defer_index, full_scan_threshold diagnostic
c0cab59  2026-06-12  N-sweep: H1 escape-hatch closes at 100k (F-S-1); mitigation price+ceiling (F-S-2); cross-engine contrast holds (F-S-3); per-segment threshold model after failed prediction (F-S-0)
fc79e58  2026-06-12  RQ8: H1-H10 revisit (exit criterion 4) + memo skeleton with gap table, pre-stated leans and falsifiers
0e45c43  2026-06-12  1e6: F-S-0 prediction CONFIRMED; mitigation non-scaling (F-S-6); pgvector dominated by exact at dim64 (F-S-7); 3.66x storage constant (F-S-8); G6 falsifier did not fire (F-S-9)
d47fb7e  2026-06-12  1e6: F-S-0 prediction CONFIRMED; mitigation non-scaling (F-S-6); pgvector dominated by exact at dim64 (F-S-7); 3.66x storage constant (F-S-8); G6 falsifier did not fire (F-S-9)
3e84791  2026-06-12  H4-stress instrument (supersession chains, near-duplicate adversarial versions); H8 sweep DRAFT (provisionally confirmed, pending verification)
75672ae  2026-06-12  H4-stress: twofold bi-temporal tax; forced filtered-HNSW collapse (P2 half-failed); G3 falsifier FIRED — epoch-partitioning probe is now the gating experiment
03c477e  2026-06-12  G3 gating probe: epoch-partitioned pgvector adapter (sentinel current-snapshot + per-epoch HNSW, adapter-side routing); gate GP1-GP3 registered
4a13473  2026-06-12  RQ8 MEMO: outcome (c) — gate fired, G3 closed at adapter layer (0.97@1.8ms vs 0.31 monolithic / 64ms fallback); recommendation H8-invariant; skeleton superseded, audit trail retained
8cacf4e  2026-06-12  Qdrant Q2 probe: rangeidx confound test (QP0) + collection-per-epoch partitioned variant (QP1/QP2)
f49befa  2026-06-12  Q2 resolved: adopt Qdrant (1.00@2ms rangeidx, F-Q2-2); H4 qdrant latency CONFOUND owned (F-Q2-0, memo erratum); partitioning moot on Qdrant
f12654f  2026-06-12  R0 exit pack: RQ1 scaffold (Tier-1 pre-filled OBSERVED), H8 sign-off checklist, exit tracker, Cloud flow-back context
78c78ce  2026-06-12  R0 EXITED (carry-forwards: RQ1→related-work, H8→pre-pub gate); paper outline: 'The Guarantees Hold, the Costs Diverge'
4d7a1ec  2026-06-12  Paper draft v0.1: §3 Method, §4 Guarantees, §5 Costs, §6 Confound, §8 Limitations skeleton + scoping guide & journal rerun spec
2d271f0  2026-06-12  Paper draft v0.2: abstract finalized, §1 Introduction, §7 Implications — manuscript now §1, §3–§8 complete
9f0b3e8  2026-06-12  RQ1 Tier-2 swept: 4 full rows + 9 light rows + descope, sources cited; owner spot-check pending
7ed0349  2026-06-12  H8 VERIFIED: confirmed — audit logs everywhere, attestation nowhere
681621c  2026-06-12  H8 verified docs corrected; hypotheses scorecard final; manuscript §1-§10 complete
d458897  2026-06-12  gitignore: scratch + caches
36352fa  2026-06-12  untrack scratch out/
b48c4b0  2026-06-12  Numbers audit v2.1: 28/28 — every paper figure resolved to a hashed ledger row
1a0fa2c  2026-06-12  fix gitignore (inline comment broke pattern); untrack scratch out/
890690d  2026-06-12  Fairness pass (PASS, zero edits) + working bibliography
e19aaad  2026-06-12  RQ1 VERIFIED: completed spot-check, verified references, countersigned fairness pass
d7860f5  2026-06-12  R0 FORMALLY EXITED: RQ1 signed + 2 flagged cells re-verified; exit recorded; public-artifact cut script
c9315c7  2026-06-12  License: Apache-2.0 + NOTICE; cut script carries them into the public artifact
```
