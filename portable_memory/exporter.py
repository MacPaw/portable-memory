"""Bundle exporter — write a ``.mem`` bundle from any ``PortableMemoryStore``.

Port of the Swift ``BundleExporter`` (``Sources/PortableMemory/BundleExporter.swift``).
Streams are deterministic — episodes ordered by id, all other kinds ordered by their
canonical line bytes, fields sorted — so a bundle is byte-reproducible regardless of the
order the host returns rows in. Every file is checksummed, and embeddings are not inlined
(source text is the portable truth; the receiver re-embeds). Full or ``since`` incremental.

The Swift SDK is ``async`` only because its store is an actor; the Python store does
local file I/O synchronously, so this port is fully synchronous.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from ._codec import to_line
from .format import (
    ConformanceLevel,
    ExportMode,
    MemCoverage,
    MemFileEntry,
    MemFormat,
    MemKind,
    MemManifest,
)
from .hashing import sha256_hex
from .interop import merge_episode_ext
from .signing import PortableSigning, PortableSigningKey
from .store import PortableMemoryStore, StoreInfo

# Known bundle subpaths cleared before a (re-)export so stale, unlisted files can never
# linger and later fail "present but not listed" verification (or be re-ingested).
_BUNDLE_SUBPATHS = (
    "items",
    "audit",
    "embeddings",
    "provenance",
    "manifest.json",
    "manifest.sig",
    "CHECKSUMS",
)


class BundleExporter:
    """Writes a ``.mem`` bundle from any :class:`PortableMemoryStore` (spec §1, §4)."""

    def export(
        self,
        store: PortableMemoryStore,
        dir: str | os.PathLike,
        mode: ExportMode = ExportMode.FULL,
        since: datetime | None = None,
        level: ConformanceLevel = ConformanceLevel.L2,
        signing_key: PortableSigningKey | None = None,
    ) -> MemManifest:
        root = os.fspath(dir)
        # Clear any prior bundle contents first, so stale items/audit/embeddings files
        # can't linger and later fail "present but not listed" verification (or be
        # re-ingested). Only known bundle subpaths are removed — unrelated files the
        # caller may keep in the directory are left alone.
        self._clear_bundle(root)
        os.makedirs(root, exist_ok=True)
        os.makedirs(os.path.join(root, "items"), exist_ok=True)
        os.makedirs(os.path.join(root, "audit"), exist_ok=True)

        info = store.store_info()
        files: list[MemFileEntry] = []
        counts: dict[str, int] = {}
        incremental = mode == ExportMode.INCREMENTAL
        # A cursor only applies to an incremental export. Ignore a stray `since` on a
        # full export so it can never silently omit older tombstones/audit rows or write
        # a `since` into a full manifest (which would contradict the schema).
        cutoff = since if incremental else None

        def keep(ts: datetime) -> bool:
            return not incremental or cutoff is None or ts >= cutoff

        # ── Bulky, append-mostly kinds: since delta-filtered. Episodes merge `ext`. ──
        ext_map = store.export_episode_ext()
        episodes = [e for e in store.export_episodes() if keep(e.ingestion_time)]
        counts[MemKind.EPISODE.value] = self._write_episodes(
            episodes, ext_map, "items/episode.jsonl", root, files
        )

        facts = [f for f in store.export_facts() if keep(f.created_at)]
        counts[MemKind.FACT.value] = self._write_jsonl(facts, "items/fact.jsonl", root, files)

        fact_links = [l for l in store.export_fact_links() if keep(l.created_at)]
        counts[MemKind.FACT_LINK.value] = self._write_jsonl(
            fact_links, "items/factLink.jsonl", root, files
        )

        resources = [r for r in store.export_resources() if keep(r.created)]
        counts[MemKind.RESOURCE.value] = self._write_jsonl(
            resources, "items/resource.jsonl", root, files
        )

        # Chunks have no own cursor; in incremental mode emit only those whose parent
        # resource is in the delta, so a newly-ingested resource's chunks travel with it.
        all_chunks = store.export_chunks()
        delta_resource_ids = {r.id for r in resources}
        chunks = (
            [c for c in all_chunks if c.resource_id in delta_resource_ids]
            if incremental
            else all_chunks
        )
        counts[MemKind.CHUNK.value] = self._write_jsonl(chunks, "items/chunk.jsonl", root, files)

        # ── Structural / graph / profile kinds: ALWAYS emitted in full (even incremental).
        #    Small, no reliable change cursor; skipping them would orphan edges/facts that
        #    reference a new entity, drop links/profile, or miss a supersession that mutates
        #    an OLD edge. Full emission + idempotent merge-by-id keeps imports complete. ──
        counts[MemKind.ENTITY.value] = self._write_jsonl(
            store.export_entities(), "items/entity.jsonl", root, files
        )
        counts[MemKind.EDGE.value] = self._write_jsonl(
            store.export_edges(), "items/edge.jsonl", root, files
        )
        counts[MemKind.EPISODE_LINK.value] = self._write_jsonl(
            store.export_episode_links(), "items/episodeLink.jsonl", root, files
        )
        counts[MemKind.CORE.value] = self._write_jsonl(
            store.export_core_blocks(), "items/core.jsonl", root, files
        )
        counts[MemKind.PROCEDURE.value] = self._write_jsonl(
            store.export_procedures(), "items/procedure.jsonl", root, files
        )
        contexts = store.export_contexts()
        counts[MemKind.CONTEXT.value] = self._write_jsonl(
            contexts, "items/context.jsonl", root, files
        )
        counts[MemKind.COMMUNITY.value] = self._write_jsonl(
            store.export_communities(), "items/community.jsonl", root, files
        )
        counts[MemKind.CATEGORY.value] = self._write_jsonl(
            store.export_categories(), "items/category.jsonl", root, files
        )
        counts[MemKind.PREFERENCE.value] = self._write_jsonl(
            store.export_preferences(), "items/preference.jsonl", root, files
        )
        counts[MemKind.SECRET_REF.value] = self._write_jsonl(
            store.export_secret_refs(), "items/secretRef.jsonl", root, files
        )

        # ── Unknown-kind passthrough — re-emit foreign record kinds verbatim (§10). ──
        known_kinds = {k.value for k in MemKind}
        for kind in store.export_passthrough_kinds():
            if kind in known_kinds:
                continue
            lines = store.export_passthrough_lines(kind)
            if not lines:
                continue
            data = ("\n".join(lines) + "\n").encode("utf-8")
            rel = f"items/{kind}.jsonl"
            self._write_bytes(data, rel, root)
            files.append(MemFileEntry(path=rel, sha256=sha256_hex(data), bytes=len(data)))
            counts[kind] = len(lines)

        # ── audit/tombstones.jsonl — applied FIRST on import (§5). ──
        tombstones = store.export_tombstones(cutoff)
        counts["tombstone"] = self._write_jsonl(
            tombstones, "audit/tombstones.jsonl", root, files
        )

        # ── audit/log.jsonl — the portable mutation trail (L1+). ──
        if level != ConformanceLevel.L0:
            audit = store.export_audit_log(cutoff)
            counts["audit"] = self._write_jsonl(audit, "audit/log.jsonl", root, files)

        checksums = self._write_checksums(files, root)
        capabilities = [
            "bitemporal",
            "tombstones",
            "redaction",
            "evidence-pack",
            "ext",
            "passthrough",
        ]
        if signing_key is not None:
            capabilities.append("signed")
        manifest = self._make_manifest(
            info=info,
            level=level,
            mode=mode,
            since=cutoff,
            counts=counts,
            files=files,
            capabilities=capabilities,
            coverage=_coverage_of(episodes),
            scopes=_scopes_of(episodes, contexts),
            bundle_digest=sha256_hex(checksums),
        )
        self._write_manifest(manifest, root, signing_key)
        return manifest

    def export_evidence_pack(
        self,
        store: PortableMemoryStore,
        dir: str | os.PathLike,
        since: datetime | None = None,
        signing_key: PortableSigningKey | None = None,
    ) -> MemManifest:
        """The Memory Evidence Pack (spec §6): audit + tombstones (proof-of-deletion) +
        provenance (edge → evidence episodes). Procurement-grade; conformance L3."""
        root = os.fspath(dir)
        self._clear_bundle(root)
        os.makedirs(os.path.join(root, "audit"), exist_ok=True)
        os.makedirs(os.path.join(root, "provenance"), exist_ok=True)
        info = store.store_info()
        files: list[MemFileEntry] = []
        counts: dict[str, int] = {}
        counts["audit"] = self._write_jsonl(
            store.export_audit_log(since), "audit/log.jsonl", root, files
        )
        counts["tombstone"] = self._write_jsonl(
            store.export_tombstones(since), "audit/tombstones.jsonl", root, files
        )
        counts["provenanceEdge"] = self._write_jsonl(
            store.export_edges(), "provenance/edges.jsonl", root, files
        )
        checksums = self._write_checksums(files, root)
        capabilities = ["evidence-pack", "proof-of-deletion", "audit", "provenance"]
        if signing_key is not None:
            capabilities.append("signed")
        manifest = self._make_manifest(
            info=info,
            level=ConformanceLevel.L3,
            mode=ExportMode.FULL if since is None else ExportMode.INCREMENTAL,
            since=since,
            counts=counts,
            files=files,
            capabilities=capabilities,
            bundle_digest=sha256_hex(checksums),
        )
        self._write_manifest(manifest, root, signing_key)
        return manifest

    # MARK: - Internals

    @staticmethod
    def _clear_bundle(root: str) -> None:
        """Remove a prior bundle's known subpaths (``items/``, ``audit/``, ``embeddings/``,
        ``provenance/``, ``manifest.json``, ``manifest.sig``, ``CHECKSUMS``) so a re-export
        to the same directory never leaves stale, unlisted files behind. Unrelated files
        are left alone."""
        for sub in _BUNDLE_SUBPATHS:
            target = os.path.join(root, sub)
            try:
                # Match Swift's FileManager.removeItem: dispatch on file vs. directory.
                if os.path.isdir(target) and not os.path.islink(target):
                    _rmtree(target)
                else:
                    os.remove(target)
            except OSError:
                # Absent (or unremovable) — nothing to clear, mirror Swift's `try?`.
                pass

    def _write_manifest(
        self, manifest: MemManifest, root: str, signing_key: PortableSigningKey | None
    ) -> None:
        """Write ``manifest.json`` and, when a signing key is supplied, a detached
        ``manifest.sig`` (spec §1.2) over the exact manifest bytes — which transitively
        authenticate every file via its ``sha256``."""
        data = to_line(manifest).encode("utf-8")
        self._write_bytes(data, "manifest.json", root)
        if signing_key is not None:
            token = PortableSigning.detached_token(data, signing_key)
            self._write_bytes((token + "\n").encode("utf-8"), "manifest.sig", root)

    def _make_manifest(
        self,
        *,
        info: StoreInfo,
        level: ConformanceLevel,
        mode: ExportMode,
        since: datetime | None,
        counts: dict[str, int],
        files: list[MemFileEntry],
        capabilities: list[str],
        coverage: MemCoverage | None = None,
        scopes: list[str] | None = None,
        bundle_digest: str | None = None,
    ) -> MemManifest:
        return MemManifest(
            format=MemFormat.VERSION,
            spec_url=MemFormat.SPEC_URL,
            coverage=coverage,
            scopes=scopes,
            bundle_digest=bundle_digest,
            generator=info.generator,
            conformance_level=level,
            # Aware UTC — a naive datetime.now() is LOCAL time, and the codec would
            # stamp it "Z" as-is, shifting createdAt by the machine's UTC offset.
            created_at=datetime.now(timezone.utc),
            export_mode=mode,
            since=since,
            schema_version=info.schema_version,
            embedding_model=info.embedding_model,
            embedding_dim=info.embedding_dim,
            embeddings_included=False,
            capabilities=capabilities,
            # Drop zero-valued kinds so an empty stream leaves no misleading count.
            counts={k: v for k, v in counts.items() if v > 0},
            files=sorted(files, key=lambda f: f.path),
        )

    def _write_checksums(self, files: list[MemFileEntry], root: str) -> bytes:
        """Write ``CHECKSUMS`` in ``sha256sum`` format (``<hex>  <path>``), sorted by path
        with a trailing newline. Two spaces separate hash and path per the tool's format.
        Returns the exact bytes written — the manifest's ``bundleDigest`` hashes them."""
        ordered = sorted(files, key=lambda f: f.path)
        lines = [f"{f.sha256}  {f.path}" for f in ordered]
        data = ("\n".join(lines) + "\n").encode("utf-8")
        self._write_bytes(data, "CHECKSUMS", root)
        return data

    def _write_episodes(
        self,
        episodes: list,
        ext_map: dict[str, str],
        rel_path: str,
        root: str,
        files: list[MemFileEntry],
    ) -> int:
        if not episodes:
            return 0
        lines: list[str] = []
        for e in sorted(episodes, key=lambda ep: ep.id):
            native = to_line(e).encode("utf-8")
            # Merge any foreign (`ext`) fields back onto the native JSON without overriding
            # native keys; byte-identical to Swift's Interop.mergeEpisodeExt.
            merged = merge_episode_ext(native, ext_map.get(e.id))
            lines.append(merged.decode("utf-8"))
        data = ("\n".join(lines) + "\n").encode("utf-8")
        self._write_bytes(data, rel_path, root)
        files.append(MemFileEntry(path=rel_path, sha256=sha256_hex(data), bytes=len(data)))
        return len(episodes)

    def _write_jsonl(
        self, rows: list, rel_path: str, root: str, files: list[MemFileEntry]
    ) -> int:
        if not rows:
            return 0
        # Sort by canonical line bytes so the stream is deterministic even when the host
        # returns rows in an arbitrary order (and for the id-less kinds like factLink /
        # preference that have no natural id to sort on).
        lines = sorted(to_line(row) for row in rows)
        data = ("\n".join(lines) + "\n").encode("utf-8")
        self._write_bytes(data, rel_path, root)
        files.append(MemFileEntry(path=rel_path, sha256=sha256_hex(data), bytes=len(data)))
        return len(rows)

    @staticmethod
    def _write_bytes(data: bytes, rel_path: str, root: str) -> None:
        """Write ``data`` to ``root/rel_path`` (binary, exact bytes). ``rel_path`` is
        exporter-owned (never derived from untrusted manifest input), so no path guard is
        needed here."""
        path = os.path.join(root, *rel_path.split("/"))
        with open(path, "wb") as fh:
            fh.write(data)


def _rmtree(path: str) -> None:
    """Recursively remove a directory tree using only ``os``/``os.path`` (no ``shutil``).

    Symlinked entries are unlinked, not followed, so clearing a stale bundle never
    escapes it."""
    for entry in os.listdir(path):
        child = os.path.join(path, entry)
        if os.path.isdir(child) and not os.path.islink(child):
            _rmtree(child)
        else:
            os.remove(child)
    os.rmdir(path)


# ── Format 1.1 manifest summaries (spec §3.1) ─────────────────────────────────────────

def _coverage_of(episodes: list) -> MemCoverage | None:
    """Earliest and latest ``eventTime`` among the episodes *in this bundle*; None when
    the bundle carries no episodes."""
    if not episodes:
        return None
    times = [e.event_time for e in episodes]
    return MemCoverage(from_=min(times), to=max(times))


def _scopes_of(episodes: list, contexts: list) -> list[str] | None:
    """Sorted (by code point), de-duplicated scope ids: every episode ``contextID`` plus
    the id of every exported ``context`` record; None when empty."""
    ids = {e.context_id for e in episodes if e.context_id}
    ids.update(c.id for c in contexts)
    return sorted(ids) or None
