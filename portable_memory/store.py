"""The store seam between the portable FORMAT and a host's PERSISTENCE.

This is the single boundary an adopter implements. Everything *format-shaped* lives
on the package side of the seam and is NOT the host's concern:

    * bundle I/O (the directory of JSONL streams), the manifest, and the ``CHECKSUMS``
      integrity file;
    * deterministic, canonical JSONL (sorted keys, compact separators, whole-second UTC
      ``Z`` timestamps) — see :mod:`portable_memory._codec`;
    * tombstone-first import ordering, so a stale row in the same bundle can never
      resurrect deleted content (spec §5);
    * ``--since`` incremental filtering; and
    * the ``ext`` foreign-field carrier for episodes and generic ``passthrough`` streams
      for kinds this SDK does not model natively (spec §8).

Everything *store-shaped* lives on the host's side: mapping the vendor's own tables to
and from the portable DTOs, and re-deriving host-local artifacts (full-text indexes,
sentence indexes, embeddings, …) after an import. The package re-derives nothing itself;
:meth:`PortableMemoryStore.finalize_import` is the hook where the host does that.

:class:`BundleExporter` reads a store through this class; :class:`BundleImporter` writes
through it. Every method has a default — an empty read or a no-op write — so an adopter
overrides ONLY the kinds it actually supports. A vendor that stores just episodes
subclasses this and implements two methods, not thirty; the rest keep returning empty and
the exporter simply emits nothing for those kinds.

Unlike the Swift reference SDK, which uses ``async`` throughout for actor isolation, this
Python SDK is fully synchronous: it performs local file I/O directly, so there is nothing
to await. Semantics are otherwise identical.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .format import MemFormat
from .records import (
    PortableCategory,
    PortableChunk,
    PortableCommunity,
    PortableContext,
    PortableCore,
    PortableEdge,
    PortableEntity,
    PortableEpisode,
    PortableEpisodeLink,
    PortableFact,
    PortableFactLink,
    PortablePreference,
    PortableProcedure,
    PortableResource,
    PortableSecretRef,
)
from .tombstone import PortableAuditRecord, Tombstone


@dataclass
class StoreInfo:
    """Identity + embedding metadata a host stamps into the manifest.

    ``generator`` is a ``"<vendor>/<version>"`` string. ``embedding_model`` and
    ``embedding_dim`` describe the vectors the host would produce so a receiver can
    decide whether it needs to re-embed on import; they are informational only, because
    the bundle never inlines vectors (the receiver re-embeds from the portable text,
    spec §2).
    """

    generator: str
    schema_version: int = 0
    embedding_model: str = ""
    embedding_dim: int = 0


class PortableMemoryStore:
    """Base class an adopter subclasses to bridge its store to the portable format.

    This is a plain (non-abstract) class: every method below has a working default, so
    subclassing it and overriding nothing yields a valid — if empty — store. Override
    only the readers/writers for the kinds the host supports.
    """

    def store_info(self) -> StoreInfo:
        """Identity + embedding metadata for the manifest. Default: a bare generator
        stamp with no schema version or embedding info."""
        return StoreInfo(generator=f"portable-memory/{MemFormat.VERSION}")

    # -- Export readers -------------------------------------------------------------
    # These return FULL snapshots of each kind. The exporter, not the store, applies
    # ``--since`` filtering, so a store implementation stays simple: hand over everything
    # and let the package decide what a given export mode needs.

    def export_episodes(self) -> list[PortableEpisode]:
        return []

    def export_episode_ext(self) -> dict[str, str]:
        """Episode id → foreign-field JSON. This is the ``ext`` carrier: fields the host
        stores on an episode that have no place in :class:`PortableEpisode` ride along as
        an opaque JSON object keyed by episode id, and are merged back verbatim on
        import (spec §8). Default: nothing to carry."""
        return {}

    def export_entities(self) -> list[PortableEntity]:
        return []

    def export_edges(self) -> list[PortableEdge]:
        return []

    def export_facts(self) -> list[PortableFact]:
        return []

    def export_fact_links(self) -> list[PortableFactLink]:
        return []

    def export_episode_links(self) -> list[PortableEpisodeLink]:
        return []

    def export_resources(self) -> list[PortableResource]:
        return []

    def export_chunks(self) -> list[PortableChunk]:
        return []

    def export_core_blocks(self) -> list[PortableCore]:
        return []

    def export_procedures(self) -> list[PortableProcedure]:
        return []

    def export_contexts(self) -> list[PortableContext]:
        return []

    def export_communities(self) -> list[PortableCommunity]:
        return []

    def export_categories(self) -> list[PortableCategory]:
        return []

    def export_preferences(self) -> list[PortablePreference]:
        return []

    def export_secret_refs(self) -> list[PortableSecretRef]:
        return []

    def export_tombstones(self, since: datetime | None) -> list[Tombstone]:
        """Portable deletion records. ``since`` narrows to tombstones created after that
        instant for an incremental export; ``None`` means the full history. The host
        applies the filter here because only it knows a tombstone's creation time."""
        return []

    def export_audit_log(self, since: datetime | None) -> list[PortableAuditRecord]:
        """Portable audit trail (spec §6). ``since`` narrows to records after that
        instant; ``None`` means the whole log."""
        return []

    def export_passthrough_kinds(self) -> list[str]:
        """Names of vendor-specific streams this store carries that are NOT modelled by
        the SDK's kinds. Each name resolves to a ``passthrough/<kind>.jsonl`` stream whose
        lines are copied verbatim (spec §8). Default: none."""
        return []

    def export_passthrough_lines(self, kind: str) -> list[str]:
        """The already-serialized JSONL lines for a passthrough ``kind``. These are
        emitted verbatim — the package does not re-canonicalize foreign lines, since it
        does not own their schema."""
        return []

    # -- Import writers -------------------------------------------------------------
    # The importer drives these in dependency order (parents before children). All are
    # no-ops by default, so a store silently ignores any kind it does not support while
    # the importer still counts and reports it.

    def tombstoned_target_ids(self) -> set[str]:
        """Ids the store already considers deleted. The importer consults this so a
        record whose id is tombstoned is never (re-)created by a merge — the deletion
        wins even against a newer-looking row in the incoming bundle. Default: none."""
        return set()

    def apply_tombstone(self, t: Tombstone) -> None:
        """Apply a portable deletion (spec §5). The package guarantees a tombstoned id is
        never resurrected by a later merge; the host implements the actual removal and
        MUST branch on ``t.op``: ``DELETE`` removes the target and every derived artifact;
        ``REDACT`` additionally purges the target's content text while keeping the
        tombstone (and a minimal skeleton), so the deletion stays provable. The id must
        also be reported by :meth:`tombstoned_target_ids`."""

    def import_episode(self, e: PortableEpisode, ext: str | None) -> None:
        """Upsert an episode. ``ext`` is the foreign-field JSON captured by
        :meth:`export_episode_ext`, to be merged back onto the host's row verbatim; it is
        ``None`` when the bundle carried no extras for this episode."""

    def import_entity(self, e: PortableEntity) -> None:
        pass

    def import_edge(self, e: PortableEdge) -> None:
        pass

    def import_fact(self, f: PortableFact) -> None:
        pass

    def import_fact_link(self, l: PortableFactLink) -> None:
        pass

    def import_episode_link(self, l: PortableEpisodeLink) -> None:
        pass

    def import_resource(self, r: PortableResource) -> None:
        pass

    def import_chunk(self, c: PortableChunk) -> None:
        pass

    def import_core_block(self, c: PortableCore) -> None:
        pass

    def import_procedure(self, p: PortableProcedure) -> None:
        pass

    def import_context(self, c: PortableContext) -> None:
        pass

    def import_community(self, c: PortableCommunity) -> None:
        pass

    def import_category(self, c: PortableCategory) -> None:
        pass

    def import_preference(self, p: PortablePreference) -> None:
        pass

    def import_secret_ref(self, r: PortableSecretRef) -> None:
        """Restore a secret REFERENCE's metadata skeleton (label, sensitivity, category,
        preview, encryption metadata) — NEVER the value/ciphertext, which is not in the
        bundle (spec §7). Default no-op: a store that can't represent a dangling ref
        simply skips it (the importer still reports it)."""

    def store_passthrough(self, kind: str, lines: list[str]) -> None:
        """Persist verbatim JSONL ``lines`` for a vendor-specific ``kind`` the SDK does
        not model. A host that recognizes its own passthrough kind can round-trip it;
        others ignore it. Default no-op."""

    def finalize_import(self, reembed_episode_ids: list[str], reembed: bool) -> int:
        """Re-derive host-local artifacts for the imported episodes (FTS, sentence index,
        and — when ``reembed`` and an embedder is available — vectors). Returns the number
        of episodes embedded. The package re-derives nothing itself; this is the host's
        hook. Default: derive nothing and report 0."""
        return 0

    def sync(self) -> None:
        """Converge any synced replica (a deletion/merge target too). No-op when none."""
