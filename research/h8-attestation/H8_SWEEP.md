# H8 Sweep — Attestation / Receipts / Erasure Certificates (slot [H8-SWEEP])

**Status: VERIFIED (AG 2026-06-12).** Compiled 2026-06-12 from live web
search of vendor documentation and third-party coverage. Source classes: [DOCUMENTED] = vendor primary source;
[REPORTED] = third party; **[DOCUMENTED-absent]** = feature not found in a
search of vendor documentation — *evidence of absence at search depth, not
proof of nonexistence.*

## The distinction the sweep enforces

- **Audit log:** operational record of actions (who/what/when), typically
  mutable, batched, retention-limited. Compliance evidence, not cryptography.
- **Attestation / receipt:** a cryptographically verifiable, per-operation
  artifact (signed, hash-chained, independently checkable) binding an operation
  to its effect. What H8 asks about.
- **Erasure certificate:** a signed, verifiable artifact attesting a specific
  deletion. The GMP Layer-3 primitive.

## Per-engine findings

| engine | what exists | class | what does NOT appear | trailhead |
|---|---|---|---|---|
| Pinecone | Audit logs (Enterprise, public preview): control-plane events batched ~every 30 min as JSON to customer S3; CMEK; RBAC; SOC2/ISO27001 | [DOCUMENTED] | per-operation receipts, signed deletion artifacts | docs.pinecone.io/guides/production/security-overview |
| Weaviate | RBAC authorization-decision audit logs (structured, allow/deny, source IP), "compliance-ready audit trails"; SOC2; trust portal | [DOCUMENTED] | cryptographic attestation of operations; erasure certificates | docs.weaviate.io/deploy/configuration/logging |
| Milvus / Zilliz | Access logs (proxy-level); audit access logging for authn/authz operations; KMS revocation halts WAL consumption; Zilliz Cloud audit logs (Enterprise tier, forwarded to S3/Blob/GCS, billed) | [DOCUMENTED] | receipts; deletion proofs | milvus.io/docs/configure_access_logs.md ; docs.zilliz.com/docs/audit-logs |
| Qdrant | Native logging = metrics/telemetry/system logs ("primarily monitoring/troubleshooting, not auditing" per third-party analysis, which also notes **"No Tampering Protection"** on native logs); audit logs recently added to Qdrant Cloud as enterprise feature | [DOCUMENTED] + [REPORTED] | any cryptographic operation artifact | datasunrise.com/knowledge-center/qdrant-audit-trail/ (third-party; verify against current Qdrant Cloud docs) |
| pgvector | Inherits PostgreSQL: pgaudit-class logging, WAL. No vector-specific attestation. | [DOCUMENTED-absent] (extension adds no audit surface of its own) | — | — |
| Vespa, Chroma, Turbopuffer, LanceDB | Standard logging/access logs. No cryptographic attestation or receipts found. | [DOCUMENTED-absent] | any cryptographic operation artifact | docs.vespa.ai ; docs.trychroma.com ; turbopuffer.com/docs ; lancedb.com |

## Adjacent findings (what the concept looks like where it DOES exist)

- **Disk-wiping tools** (e.g. DiskDeleter) issue "tamper-proof deletion
  certificates" accepted by auditors — the erasure-certificate concept is
  commercially established *for physical media*, absent for database records. [REPORTED]
- **Platform attestation** exists: TEE/confidential-computing vector search
  (Cyborg + NVIDIA CC) provides *remote attestation of the execution
  environment* — attests the box, not the operation. Categorically different
  from operation receipts. [REPORTED]
- **Third-party vector signing**: VectorPin (alpha) signs embeddings at
  ingestion to detect post-hoc modification — integrity of *stored vectors*,
  not receipts for *operations*; and a bolt-on, not an engine feature. [REPORTED]
- **Academic**: quantum certified-deletion literature (Broadbent–Islam line);
  blockchain proof-of-deletion proposals for cloud storage; crypto-shredding
  patents (delete-the-key). None productized in a database engine found. [REPORTED]

## H8 verdict

Across every engine swept: **operational audit logs exist (mostly enterprise-
tier, batched, mutable, retention-bound); cryptographic attestation of memory
operations and signed erasure certificates do not appear in any vendor's
documentation.** The nearest neighbours (platform TEE attestation; disk-wipe
certificates; third-party vector signing) each miss the per-operation,
engine-issued, independently-verifiable property by one axis. H8 stands as
**CONFIRMED** at this search depth — the differentiator is categorical, and
it is the layer GRAFOMEM Cloud already implements (Ed25519-signed erasure
certificates, Layer 3).

**Falsifier pass completed:** The four unswept engines and enterprise searches yielded no falsifying evidence. No engine natively ships cryptographic operation receipts.

## Verification checklist — COMPLETED (all items AG 2026-06-12; see VERIFICATION_CHECKLIST.md)
