"""Shared test fixtures — a minimal in-memory store and an episode factory.

Mirrors the Swift test harness (``Tests/PortableMemoryTests/PortableMemoryTests.swift``):
``InMemoryStore`` is the smallest possible :class:`PortableMemoryStore` that exercises the
format/protocol with zero infrastructure — it is also the shape an adopter implements.
``ep`` builds a fully-populated :class:`PortableEpisode` with fixed timestamps so bundle
bytes are deterministic across runs and match the Swift fixture.

The Swift store is an ``actor``; the Python store is a plain object because the SDK is
fully synchronous. The behaviour is otherwise identical.
"""
from __future__ import annotations

from datetime import datetime, timezone

from portable_memory import (
    PortableEdge,
    PortableEntity,
    PortableEpisode,
    PortableMemoryStore,
    StoreInfo,
    Tombstone,
)

#: The Swift tests use ``Date(timeIntervalSince1970: 1_700_000_000)`` — 2023-11-14T22:13:20Z.
#: Reused for every episode field in ``ep`` so exported bytes are stable and diffable.
_FIXED_TIME = datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)


class InMemoryStore(PortableMemoryStore):
    """A minimal in-memory store: dicts for episodes/entities/edges/passthrough and a list
    of tombstones. Overrides only the kinds the Swift tests touch; every other kind falls
    back to the base-class default (empty read / no-op write)."""

    def __init__(self) -> None:
        self.episodes: dict[str, PortableEpisode] = {}
        self.episode_ext: dict[str, str] = {}
        self.entities: dict[str, PortableEntity] = {}
        self.edges: dict[str, PortableEdge] = {}
        self.tombstones: list[Tombstone] = []
        self.tombstoned_ids: set[str] = set()
        self.passthrough: dict[str, list[str]] = {}

    # ── Store identity ──
    def store_info(self) -> StoreInfo:
        return StoreInfo(
            generator="test/1.0",
            schema_version=1,
            embedding_model="test-embed",
            embedding_dim=8,
        )

    # ── Export readers (sorted by id for deterministic output) ──
    def export_episodes(self) -> list[PortableEpisode]:
        return [self.episodes[k] for k in sorted(self.episodes)]

    def export_episode_ext(self) -> dict[str, str]:
        return self.episode_ext

    def export_entities(self) -> list[PortableEntity]:
        return [self.entities[k] for k in sorted(self.entities)]

    def export_edges(self) -> list[PortableEdge]:
        return [self.edges[k] for k in sorted(self.edges)]

    def export_tombstones(self, since: datetime | None) -> list[Tombstone]:
        return [t for t in self.tombstones if since is None or t.deleted_at >= since]

    def export_passthrough_kinds(self) -> list[str]:
        return sorted(self.passthrough)

    def export_passthrough_lines(self, kind: str) -> list[str]:
        return self.passthrough.get(kind, [])

    # ── Import writers ──
    def tombstoned_target_ids(self) -> set[str]:
        return self.tombstoned_ids

    def apply_tombstone(self, t: Tombstone) -> None:
        # A tombstone is kind-agnostic here: remove the target from whichever collection
        # holds it, and record the id so a later merge can't resurrect it.
        self.episodes.pop(t.target_id, None)
        self.episode_ext.pop(t.target_id, None)
        self.entities.pop(t.target_id, None)
        self.edges.pop(t.target_id, None)
        self.tombstoned_ids.add(t.target_id)
        self.tombstones.append(t)

    def import_episode(self, e: PortableEpisode, ext: str | None) -> None:
        self.episodes[e.id] = e
        if ext is None:
            self.episode_ext.pop(e.id, None)
        else:
            self.episode_ext[e.id] = ext

    def import_entity(self, e: PortableEntity) -> None:
        self.entities[e.id] = e

    def import_edge(self, e: PortableEdge) -> None:
        self.edges[e.id] = e

    def store_passthrough(self, kind: str, lines: list[str]) -> None:
        self.passthrough[kind] = lines

    # ── Test-seam helpers (plain methods, not part of the store interface) ──
    def seed_episode(self, e: PortableEpisode, ext: str | None = None) -> None:
        self.episodes[e.id] = e
        if ext is not None:
            self.episode_ext[e.id] = ext

    def seed_entity(self, e: PortableEntity) -> None:
        self.entities[e.id] = e

    def seed_edge(self, e: PortableEdge) -> None:
        self.edges[e.id] = e

    def seed_tombstone(self, t: Tombstone) -> None:
        self.apply_tombstone(t)

    def seed_passthrough(self, kind: str, lines: list[str]) -> None:
        self.passthrough[kind] = lines

    def episode_count(self) -> int:
        return len(self.episodes)

    def episode_ids(self) -> list[str]:
        return sorted(self.episodes)

    def entity_ids(self) -> list[str]:
        return sorted(self.entities)

    def edge_ids(self) -> list[str]:
        return sorted(self.edges)

    def summary_for(self, id: str) -> str | None:
        e = self.episodes.get(id)
        return e.summary if e is not None else None

    def ext_for(self, id: str) -> str | None:
        return self.episode_ext.get(id)

    def passthrough_for(self, kind: str) -> list[str]:
        return self.passthrough.get(kind, [])


def ep(id: str, summary: str) -> PortableEpisode:
    """A fully-populated episode with fixed timestamps and ``confidence=0.7`` — the exact
    shape the Swift ``ep(_:_:)`` helper produces, so exported bytes match."""
    return PortableEpisode(
        id=id,
        event_time=_FIXED_TIME,
        mention_time=_FIXED_TIME,
        ingestion_time=_FIXED_TIME,
        source_type="note",
        source_id=None,
        actors=[],
        summary=summary,
        details=summary,
        sensitivity="low",
        deleted_at=None,
        metadata={},
        context_id=None,
        categories=[],
        importance=0.5,
        confidence=0.7,
        lifecycle_state="HOT",
        extraction_state="done",
        last_accessed=None,
        access_count=0,
        pinned=False,
        expiration_date=None,
        vault_refs=[],
        speaker=None,
    )
