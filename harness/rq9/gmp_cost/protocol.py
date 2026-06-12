"""
GMP cost-harness adapter protocol.

Mirrors the parent project's backend adapter contract
(write / supersede / delete / retrieve / audit / flush + capability flags)
so the same adapters used for the W5/W6 two-sided *correctness* suite can be
driven by the RQ9 *cost* harness without modification. The harness only TIMES
these calls and checks their results against an external oracle; it never judges
behaviour itself.

A vector is identified by an opaque string `rid`. The store is responsible for
nothing except honouring (or failing to honour) the operations below. Whether it
honours them is what the correctness suite decides; what it costs to honour them
is what this harness measures, and the two are reported on the same row.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence, runtime_checkable
import numpy as np

# Open-interval sentinel for valid_until ("still true"). This is H2 sentinel
# encoding in the literal sense the glossary fixes: an extreme constant so an
# open temporal interval is range-scannable. It is NOT a security property.
T_OPEN = 2**62


@dataclass(frozen=True)
class Record:
    rid: str
    vector: np.ndarray          # shape (dim,), float32
    tenant: str
    valid_from: int = 0         # transaction/logical time the fact became true
    valid_until: int = T_OPEN   # T_OPEN == still valid


@dataclass(frozen=True)
class Hit:
    rid: str
    score: float                # cosine similarity; higher = nearer


@dataclass(frozen=True)
class Capabilities:
    """What the adapter claims. Drives which scenarios are APPLICABLE.

    A claim here is [DOCUMENTED]/[HYPOTHESIS] only; the harness pairs it with the
    [OBSERVED] correctness verdict + cost. A backend may claim `hard_delete=True`
    and still leak (claims-but-leaks) -- that gap is the headline, not an error.
    """
    physical_tenant_isolation: bool = False   # separate keyspace per tenant
    hard_delete: bool = False                 # read-path excision, not tombstone-only
    native_bitemporal: bool = False           # first-class valid/transaction time
    consults_tombstone_on_read: bool = True   # False == the claims-but-leaks foil
    consults_tenant_on_read: bool = True       # False == the leaky-tenant foil


@runtime_checkable
class Backend(Protocol):
    name: str
    version: str
    index_config: dict          # e.g. {"index": "hnsw", "M": 16, "ef_search": 64}
    caps: Capabilities

    def write(self, recs: Sequence[Record]) -> None: ...
    def supersede(self, rid: str, new: Record, at: int) -> None: ...
    def delete(self, rids: Sequence[str]) -> None: ...
    def retrieve(self, query: np.ndarray, k: int, tenant: str | None,
                 as_of: int | None = None) -> list[Hit]: ...
    def audit(self, rid: str) -> dict: ...   # store's self-report about a record
    def flush(self) -> None: ...             # force any deferred work to settle
    # Optional: physical reclaim of tombstoned space. Backends that defer
    # reclamation expose it so the harness can price amortized vs worst-case.
    def compact(self) -> None: ...
    def storage_bytes(self) -> int: ...      # live + dead footprint, best-effort


@dataclass
class LedgerRow:
    """One source-tagged cell of the cost ledger, paired with a correctness ref."""
    engine: str
    version: str
    index_config: str
    scenario: str               # e.g. "retrieve.tenant_scoped"
    w_ref: str                  # correctness anchor, e.g. "W5"
    correctness: str            # PASS / LEAKS / OVER_RESTRICTS / N/A (from suite or oracle)
    recall_at_k: float | None
    leak_rate: float | None     # fraction of returned ids that must NOT have appeared
    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    max_ms: float | None
    throughput_ops_s: float | None
    storage_bytes: int | None
    delete_ack_ms: float | None        # time delete() returned
    unretrievable_ms: float | None     # wall time until truly gone from reads
    ops_until_gone: int | None         # retrieve() calls until gone (hw-independent)
    source_class: str = "OBSERVED"
    notes: str = ""
    extra: dict = field(default_factory=dict)
