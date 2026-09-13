"""A minimal in-memory :class:`PortableMemoryStore`.

The smallest possible host: dictionaries for episodes, entities, edges and passthrough
streams, plus a tombstone list. It exercises the whole format/protocol with zero
infrastructure — the ``mem`` command line uses it to turn adapter output into a bundle
and to read a bundle back — and it is the shape an adopter's own store takes: override
only the kinds you support, and the base class supplies empty reads / no-op writes for
the rest.

Mirrors the test harness store of the Swift reference SDK (an ``actor`` there; a plain
object here because this SDK is synchronous).
"""
from __future__ import annotations

from datetime import datetime

from . import __version__
from .records import PortableEdge, PortableEntity, PortableEpisode
from .store import PortableMemoryStore, StoreInfo
from .tombstone import Tombstone

__all__ = ["InMemoryStore"]


class InMemoryStore(PortableMemoryStore):
    """Episodes, entities, edges, tombstones and passthrough streams — all in memory."""

    def __init__(self, generator: str | None = None) -> None:
        self.generator = generator or f"portable-memory/{__version__}"
        self.episodes: dict[str, PortableEpisode] = {}
        self.episode_ext: dict[str, str] = {}
        self.entities: dict[str, PortableEntity] = {}
        self.edges: dict[str, PortableEdge] = {}
        self.tombstones: list[Tombstone] = []
        self.tombstoned_ids: set[str] = set()
        self.passthrough: dict[str, list[str]] = {}

    # ── Identity ──
    def store_info(self) -> StoreInfo:
        return StoreInfo(generator=self.generator)

    # ── Export readers (sorted by id, so output is deterministic) ──
    def export_episodes(self) -> list[PortableEpisode]:
        return [self.episodes[k] for k in sorted(self.episodes)]

    def export_episode_ext(self) -> dict[str, str]:
        return dict(self.episode_ext)

    def export_entities(self) -> list[PortableEntity]:
        return [self.entities[k] for k in sorted(self.entities)]

    def export_edges(self) -> list[PortableEdge]:
        return [self.edges[k] for k in sorted(self.edges)]

    def export_tombstones(self, since: datetime | None) -> list[Tombstone]:
        return [t for t in self.tombstones if since is None or t.deleted_at >= since]

    def export_passthrough_kinds(self) -> list[str]:
        return sorted(self.passthrough)

    def export_passthrough_lines(self, kind: str) -> list[str]:
        return list(self.passthrough.get(kind, []))

    # ── Import writers ──
    def tombstoned_target_ids(self) -> set[str]:
        return set(self.tombstoned_ids)

    def apply_tombstone(self, t: Tombstone) -> None:
        # Kind-agnostic: drop the target from whichever collection holds it and remember
        # the id so a later merge can never resurrect it (spec §5).
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
        self.passthrough[kind] = list(lines)
