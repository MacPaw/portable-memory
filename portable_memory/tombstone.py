"""Tombstones (spec §5 — the trust core).

A deletion is not a row removal; it is a first-class, portable, monotonic record (it
cannot be un-seen) that propagates everywhere the data — or anything derived from it —
ever went. The tombstone carries proof-of-reach: the ids of every derived artifact
removed and the cache keys evicted, so a deletion can be verified across replicas and
external adopters, not merely asserted. This is the guarantee the standard rests on and
the conformance gate (L2).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


@dataclass(kw_only=True)
class DerivedRefs:
    """Proof-of-reach: the derived artifacts a single deletion removed."""
    sentence_ids: list[str] = field(default_factory=list, metadata={"json": "sentenceIDs"})
    fact_ids: list[str] = field(default_factory=list, metadata={"json": "factIDs"})
    # edges deleted because their last evidence was removed
    edge_ids: list[str] = field(default_factory=list, metadata={"json": "edgeIDs"})
    # entities orphaned by those edge deletions
    entity_ids: list[str] = field(default_factory=list, metadata={"json": "entityIDs"})
    chunk_ids: list[str] = field(default_factory=list, metadata={"json": "chunkIDs"})
    episode_link_count: int = field(default=0, metadata={"json": "episodeLinkCount"})
    # sha256(model \0 text) keys evicted
    embedding_cache_keys: list[str] = field(default_factory=list, metadata={"json": "embeddingCacheKeys"})

    def merge(self, other: "DerivedRefs") -> None:
        self.sentence_ids += other.sentence_ids
        self.fact_ids += other.fact_ids
        self.edge_ids += other.edge_ids
        self.entity_ids += other.entity_ids
        self.chunk_ids += other.chunk_ids
        self.episode_link_count += other.episode_link_count
        self.embedding_cache_keys += other.embedding_cache_keys


class TombstoneOp(str, Enum):
    DELETE = "delete"   # remove the item and every derived artifact
    REDACT = "redact"   # additionally purge the content text (erasure / GDPR Art. 17)


@dataclass(kw_only=True)
class Tombstone:
    """The portable deletion record (``audit/tombstones.jsonl``). On import, tombstones
    are applied BEFORE any additions, so a bundle that also ships the (stale) rows can
    never resurrect deleted content, and redaction always wins."""
    id: str = field(metadata={"json": "id"})
    op: TombstoneOp = field(metadata={"json": "op"})
    target_kind: str = field(metadata={"json": "targetKind"})   # MemKind value of what was deleted
    target_id: str = field(metadata={"json": "targetID"})
    deleted_at: datetime = field(metadata={"json": "deletedAt"})
    actor: str = field(metadata={"json": "actor"})
    derived: DerivedRefs = field(default_factory=DerivedRefs, metadata={"json": "derived"})
    reason: str | None = field(default=None, metadata={"json": "reason"})
    signature: str | None = field(default=None, metadata={"json": "signature"})  # ed25519 (L3), §1.3


@dataclass(kw_only=True)
class PortableAuditRecord:
    """One row of the portable audit trail (``audit/log.jsonl``). The Evidence Pack
    (spec §6) is an exportable subset of these plus tombstones plus provenance."""
    ts: datetime = field(metadata={"json": "ts"})
    actor: str = field(metadata={"json": "actor"})
    op: str = field(metadata={"json": "op"})
    target_id: str = field(metadata={"json": "targetID"})
    reason: str | None = field(default=None, metadata={"json": "reason"})
