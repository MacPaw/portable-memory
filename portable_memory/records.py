"""Portable record DTOs (``items/<kind>.jsonl``).

One dataclass per kind. Enum-like fields (source_type, sensitivity, lifecycle_state,
entity type, …) are plain strings so a foreign vendor's value is never forced into
another engine's enum — vendor neutrality. Source text is the portable truth; embeddings
are not inlined (the receiver re-embeds, spec §2). Attributes are snake_case; the wire
key (camelCase, per the JSON Schemas) is carried in each field's ``metadata["json"]``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(kw_only=True)
class PortableEpisode:
    id: str = field(metadata={"json": "id"})
    event_time: datetime = field(metadata={"json": "eventTime"})
    mention_time: datetime = field(metadata={"json": "mentionTime"})
    ingestion_time: datetime = field(metadata={"json": "ingestionTime"})
    source_type: str = field(metadata={"json": "sourceType"})
    actors: list[str] = field(metadata={"json": "actors"})
    summary: str = field(metadata={"json": "summary"})
    details: str = field(metadata={"json": "details"})
    sensitivity: str = field(metadata={"json": "sensitivity"})
    metadata: dict[str, str] = field(metadata={"json": "metadata"})
    categories: list[str] = field(metadata={"json": "categories"})
    importance: float = field(metadata={"json": "importance"})
    confidence: float = field(metadata={"json": "confidence"})
    lifecycle_state: str = field(metadata={"json": "lifecycleState"})
    extraction_state: str = field(metadata={"json": "extractionState"})
    access_count: int = field(metadata={"json": "accessCount"})
    pinned: bool = field(metadata={"json": "pinned"})
    vault_refs: list[str] = field(metadata={"json": "vaultRefs"})
    source_id: str | None = field(default=None, metadata={"json": "sourceID"})
    deleted_at: datetime | None = field(default=None, metadata={"json": "deletedAt"})
    context_id: str | None = field(default=None, metadata={"json": "contextID"})
    last_accessed: datetime | None = field(default=None, metadata={"json": "lastAccessed"})
    expiration_date: datetime | None = field(default=None, metadata={"json": "expirationDate"})
    speaker: str | None = field(default=None, metadata={"json": "speaker"})


@dataclass(kw_only=True)
class PortableEntity:
    id: str = field(metadata={"json": "id"})
    entity_type: str = field(metadata={"json": "type"})
    canonical_name: str = field(metadata={"json": "canonicalName"})
    aliases: list[str] = field(metadata={"json": "aliases"})
    summary: str = field(metadata={"json": "summary"})
    sensitivity: str = field(metadata={"json": "sensitivity"})
    updated_at: datetime = field(metadata={"json": "updatedAt"})


@dataclass(kw_only=True)
class PortableEdge:
    id: str = field(metadata={"json": "id"})
    src_entity_id: str = field(metadata={"json": "srcEntityID"})
    dst_entity_id: str = field(metadata={"json": "dstEntityID"})
    edge_type: str = field(metadata={"json": "edgeType"})
    t_valid_from: datetime = field(metadata={"json": "tValidFrom"})
    ingestion_time: datetime = field(metadata={"json": "ingestionTime"})
    confidence: float = field(metadata={"json": "confidence"})
    evidence_episode_ids: list[str] = field(metadata={"json": "evidenceEpisodeIDs"})
    t_valid_to: datetime | None = field(default=None, metadata={"json": "tValidTo"})
    superseded_by: str | None = field(default=None, metadata={"json": "supersededBy"})


@dataclass(kw_only=True)
class PortableFact:
    id: str = field(metadata={"json": "id"})
    episode_id: str = field(metadata={"json": "episodeID"})
    subject: str = field(metadata={"json": "subject"})
    predicate: str = field(metadata={"json": "predicate"})
    obj: str = field(metadata={"json": "object"})
    text: str = field(metadata={"json": "text"})
    t_valid_from: datetime = field(metadata={"json": "tValidFrom"})
    confidence: float = field(metadata={"json": "confidence"})
    importance: float = field(metadata={"json": "importance"})
    created_at: datetime = field(metadata={"json": "createdAt"})
    event_time: datetime | None = field(default=None, metadata={"json": "eventTime"})
    t_valid_to: datetime | None = field(default=None, metadata={"json": "tValidTo"})
    superseded_by: str | None = field(default=None, metadata={"json": "supersededBy"})
    speaker: str | None = field(default=None, metadata={"json": "speaker"})
    reconciled_at: datetime | None = field(default=None, metadata={"json": "reconciledAt"})
    last_reinforced_at: datetime | None = field(default=None, metadata={"json": "lastReinforcedAt"})
    pruned_at: datetime | None = field(default=None, metadata={"json": "prunedAt"})


@dataclass(kw_only=True)
class PortableFactLink:
    src_fact_id: str = field(metadata={"json": "srcFactID"})
    dst_fact_id: str = field(metadata={"json": "dstFactID"})
    link_type: str = field(metadata={"json": "linkType"})
    created_at: datetime = field(metadata={"json": "createdAt"})


@dataclass(kw_only=True)
class PortableEpisodeLink:
    src_episode_id: str = field(metadata={"json": "srcEpisodeID"})
    dst_episode_id: str = field(metadata={"json": "dstEpisodeID"})
    link_type: str = field(metadata={"json": "linkType"})
    weight: float = field(metadata={"json": "weight"})


@dataclass(kw_only=True)
class PortableResource:
    id: str = field(metadata={"json": "id"})
    uri: str = field(metadata={"json": "uri"})
    mime_type: str = field(metadata={"json": "mimeType"})
    content_hash: str = field(metadata={"json": "contentHash"})
    title: str = field(metadata={"json": "title"})
    summary: str = field(metadata={"json": "summary"})
    created: datetime = field(metadata={"json": "created"})
    modified: datetime = field(metadata={"json": "modified"})


@dataclass(kw_only=True)
class PortableChunk:
    id: str = field(metadata={"json": "id"})
    resource_id: str = field(metadata={"json": "resourceID"})
    position: int = field(metadata={"json": "position"})
    text: str = field(metadata={"json": "text"})
    sensitivity: str = field(metadata={"json": "sensitivity"})
    context_prefix: str | None = field(default=None, metadata={"json": "contextPrefix"})


@dataclass(kw_only=True)
class PortableCore:
    id: str = field(metadata={"json": "id"})          # profile block id (human | persona)
    content: str = field(metadata={"json": "content"})
    char_budget: int = field(metadata={"json": "charBudget"})
    version: int = field(metadata={"json": "version"})


@dataclass(kw_only=True)
class PortableProcedure:
    id: str = field(metadata={"json": "id"})
    name: str = field(metadata={"json": "name"})
    trigger_pattern: str = field(metadata={"json": "triggerPattern"})
    steps: list[str] = field(metadata={"json": "steps"})
    success_count: int = field(metadata={"json": "successCount"})
    failure_count: int = field(metadata={"json": "failureCount"})
    enabled: bool = field(metadata={"json": "enabled"})
    last_used: datetime | None = field(default=None, metadata={"json": "lastUsed"})


@dataclass(kw_only=True)
class PortableContext:
    id: str = field(metadata={"json": "id"})
    label: str = field(metadata={"json": "label"})
    archived: bool = field(metadata={"json": "archived"})
    created_at: datetime = field(metadata={"json": "createdAt"})
    parent_id: str | None = field(default=None, metadata={"json": "parentID"})


@dataclass(kw_only=True)
class PortableCommunity:
    id: str = field(metadata={"json": "id"})
    label: str = field(metadata={"json": "label"})
    summary: str = field(metadata={"json": "summary"})
    member_entity_ids: list[str] = field(metadata={"json": "memberEntityIDs"})


@dataclass(kw_only=True)
class PortableCategory:
    name: str = field(metadata={"json": "name"})
    description: str = field(metadata={"json": "description"})


@dataclass(kw_only=True)
class PortablePreference:
    key: str = field(metadata={"json": "key"})
    value: str = field(metadata={"json": "value"})


@dataclass(kw_only=True)
class PortableSecretRef:
    """A reference to a vault secret. Carries encryption metadata so a receiver knows how
    the value is protected, but NEVER the plaintext or ciphertext (spec §7). ``preview``
    must be a masked hint only and MUST NOT contain recoverable secret material."""
    id: str = field(metadata={"json": "id"})
    label: str = field(metadata={"json": "label"})
    sensitivity: str = field(metadata={"json": "sensitivity"})
    category: str = field(metadata={"json": "category"})
    preview: str = field(metadata={"json": "preview"})
    encryption_metadata: str = field(metadata={"json": "encryptionMetadata"})
    created_at: datetime = field(metadata={"json": "createdAt"})
    last_accessed: datetime | None = field(default=None, metadata={"json": "lastAccessed"})


@dataclass
class MemImportReport:
    """Outcome of an import/merge."""
    tombstones_applied: int = 0
    applied: dict[str, int] = field(default_factory=dict)
    skipped_idempotent: int = 0
    skipped_tombstoned: int = 0
    reembedded: int = 0
    warnings: list[str] = field(default_factory=list)
