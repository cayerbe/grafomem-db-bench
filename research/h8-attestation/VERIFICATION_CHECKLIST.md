# H8 Verification Checklist (closes the last RQ8 slot)

Verify the DRAFT sweep (`H8_SWEEP.md`). Each item gets initials + date.
Search terms per engine: *audit, attestation, receipt, signed, certificate,
deletion proof, compliance, tamper*. Remember the distinction: audit LOG
(operational, mutable) ≠ cryptographic ATTESTATION (per-operation, verifiable).

## A. Verify the drafted rows (open each trailhead, confirm against current text)

- [x] Pinecone — docs.pinecone.io/guides/production/security-overview
      (audit logs: Enterprise, ~30-min batched JSON→S3, control-plane). AG 2026-06-12
- [x] Weaviate — docs.weaviate.io/deploy/configuration/logging
      (RBAC authorization-decision logs). AG 2026-06-12
- [x] Milvus — milvus.io/docs/configure_access_logs.md ; Zilliz —
      docs.zilliz.com/docs/audit-logs (Enterprise, object-storage forward). AG 2026-06-12
- [x] Qdrant — verify Cloud audit-log feature against CURRENT Qdrant docs
      (drafted row leans on a third party, DataSunrise). AG 2026-06-12

## B. Sweep the four missing engines (any attestation-class feature?)

- [x] Vespa AG 2026-06-12   - [x] Chroma AG 2026-06-12   - [x] Turbopuffer AG 2026-06-12   - [x] LanceDB AG 2026-06-12

## C. The falsifier pass

- [x] Check enterprise/sales-gated feature sheets where public docs are thin
      (attestation sometimes lives behind "contact sales"). AG 2026-06-12
- [x] One generic search: "vector database" + "signed deletion" / "operation
      receipt" / "cryptographic audit" — anything new since 2026-06. AG 2026-06-12

## D. Verdict

- [x] If NOTHING ships per-operation receipts or signed erasure certificates:
      mark H8 **CONFIRMED** in HYPOTHESES_REVISIT.md, remove the (DRAFT) tag,
      note date + initials. [CONFIRMED AG 2026-06-12] RQ8 memo §4 already covers this branch.
- [ ] If ANY engine ships them: H8 **REFUTED** — record which/where; per memo
      §4 the recommendation is unchanged (no categorical gap → still (c)), but
      the moat framing in flow-back B must drop the "nobody ships this" line.

Closing this checklist + the RQ1 Tier-2 rows = **formal R0 exit** (charter §9).
