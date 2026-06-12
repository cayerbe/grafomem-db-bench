# Vendor-Fairness & Vocabulary Pass — 2026-06-12 (assistant; owner countersign: AG 2026-06-12)

Checklist from SCOPING_GUIDE §A, applied to DRAFT.md + TABLES.md.

| check | verdict | evidence |
|---|---|---|
| Architecture-class language, never "<vendor> is broken" | **PASS** | The one strong sentence — "Post-filtering under selective filters is not degraded at scale; it is broken" (§5.1) — predicates the *technique under stated conditions*, follows the three-instrument mechanism, and is paired with the engine's own mitigation being measured fairly. Subject is never a vendor. |
| Forced/non-default configs labeled at point of use | **PASS** | 17 occurrences; the OVER_RESTRICTS result and traversal collapse carry "deliberately non-default" in §4.4, §5.2, §8, and in T3/T4 row labels. |
| Confound-flagged rows visible | **PASS** | §6 full section; ⚑ flag rendered inside Table 4; Table 5 row labeled "(confound-flagged)"; HYPOTHESES H4 carries it. |
| No "first/only" without the survey qualifier | **PASS** | §1(i) and §9 both carry "to our knowledge", §9 adds "we make the claim no more strongly than that"; backed by the verified H8 sweep + RQ1 table. |
| tamper-evident never tamper-proof; no "mathematically certifies" | **PASS** | Zero occurrences of either banned form. |
| Two-sided framing (0.000 leak alone never a pass) | **PASS** | Stated in §2, §3.5, §4.4; encoded in the audit's loud-fail rule. |
| Latency claims scoped (fingerprint, transport, dim=64) | **PASS** | §3.6, §5.3, §8, and every table caption. |
| Engines get their strengths stated | **PASS** | pgvector: honest deletion, exact storage measurement, working mitigation at small N, partitioned fix hits gate. Qdrant: planner praised as load-bearing, temporal cost confound owned as OURS, default config defended (§5.2). |

**Borderline items reviewed and kept (with rationale):**
1. §5.2 "delivers neither recall nor speed at this scale and selectivity" — subject is the architecture description, claim is condition-scoped, and the same paragraph credits the same engine's planner design elsewhere. Kept.
2. §1 "honest stores driven by forgetful integrations" — rhetorical but accurate and vendor-favorable. Kept.

**Edits made: none required.** The draft was written under the rules; the pass confirms rather than repairs.
