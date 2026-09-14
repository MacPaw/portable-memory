"""Portable Memory format primitives — kinds, manifest, path safety, limits.

An open, vendor-neutral container for carrying AI memory across apps, devices, and
vendors. A bundle is a plain directory of JSONL streams plus a manifest and a checksum
file; no server is needed to read, verify, or transfer it. Full spec:
``Spec/portable-memory-spec.md``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class MemFormat:
    #: Semantic version of the on-disk format. Importers negotiate by this + capabilities.
    #: 1.1.0 added the optional manifest fields ``specURL``, ``coverage``, ``scopes`` and
    #: ``bundleDigest``; 1.0 bundles remain valid (same major).
    VERSION = "1.1.0"
    #: Where the specification this bundle follows lives (``manifest.specURL``).
    SPEC_URL = "https://github.com/MacPaw/portable-memory/blob/main/Spec/portable-memory-spec.md"
    #: Conventional bundle directory suffix.
    BUNDLE_SUFFIX = "mem"


class MemKind(str, Enum):
    EPISODE = "episode"          # a timestamped event — the atomic, cross-vendor unit
    ENTITY = "entity"            # a semantic graph node
    EDGE = "edge"                # a bi-temporal relation
    FACT = "fact"                # a derived subject–predicate–object triple
    FACT_LINK = "factLink"       # evidence_of / refines link between facts
    EPISODE_LINK = "episodeLink" # cross-link between episodes
    RESOURCE = "resource"        # a file/doc reference, parent of chunks
    CHUNK = "chunk"              # a resource fragment
    CORE = "core"                # an always-injected profile block
    PROCEDURE = "procedure"      # a user-defined routine
    CONTEXT = "context"          # a scoping/tag node
    COMMUNITY = "community"      # a graph community
    CATEGORY = "category"        # a memory category
    PREFERENCE = "preference"    # a durable user key/value setting
    SECRET_REF = "secretRef"     # a reference to a vault secret — NEVER plaintext


#: Stable import order: parents before children so references resolve.
IMPORT_ORDER: list[MemKind] = [
    MemKind.CONTEXT, MemKind.CATEGORY, MemKind.PREFERENCE, MemKind.CORE,
    MemKind.ENTITY, MemKind.EPISODE, MemKind.RESOURCE, MemKind.CHUNK,
    MemKind.EDGE, MemKind.FACT, MemKind.FACT_LINK, MemKind.EPISODE_LINK,
    MemKind.PROCEDURE, MemKind.COMMUNITY, MemKind.SECRET_REF,
]


class ExportMode(str, Enum):
    FULL = "full"
    INCREMENTAL = "incremental"


class ConformanceLevel(str, Enum):
    L0 = "L0"  # Read / Export — a valid, checksum-clean bundle
    L1 = "L1"  # Import / Merge — lossless, idempotent, bi-temporal merge
    L2 = "L2"  # Deletion propagation — honors tombstones across all artifacts (BADGE)
    L3 = "L3"  # Governed — full audit trail, Evidence Pack, signed tombstones


@dataclass(kw_only=True)
class MemFileEntry:
    """One file's integrity record, mirrored in ``manifest.files`` and ``CHECKSUMS``."""
    path: str = field(metadata={"json": "path"})        # bundle-relative, e.g. items/episode.jsonl
    sha256: str = field(metadata={"json": "sha256"})    # lowercase hex
    bytes: int = field(metadata={"json": "bytes"})


@dataclass(kw_only=True)
class MemCoverage:
    """The time span of the memories in a bundle — the earliest and latest episode
    ``eventTime`` (format 1.1). Lets a reader answer "what period does this archive
    cover?" without opening a stream."""
    from_: datetime = field(metadata={"json": "from"})
    to: datetime = field(metadata={"json": "to"})


@dataclass(kw_only=True)
class MemManifest:
    """Declares everything an importer needs to negotiate capabilities and verify integrity."""
    format: str = field(metadata={"json": "format"})
    generator: str = field(metadata={"json": "generator"})
    conformance_level: ConformanceLevel = field(metadata={"json": "conformanceLevel"})
    created_at: datetime = field(metadata={"json": "createdAt"})
    export_mode: ExportMode = field(metadata={"json": "exportMode"})
    schema_version: int = field(metadata={"json": "schemaVersion"})
    embedding_model: str = field(metadata={"json": "embeddingModel"})
    embedding_dim: int = field(metadata={"json": "embeddingDim"})
    embeddings_included: bool = field(metadata={"json": "embeddingsIncluded"})
    capabilities: list[str] = field(metadata={"json": "capabilities"})
    counts: dict[str, int] = field(metadata={"json": "counts"})
    files: list[MemFileEntry] = field(metadata={"json": "files"})
    since: datetime | None = field(default=None, metadata={"json": "since"})
    # ── Format 1.1 additions. Optional on read: a 1.0 bundle has none of them. ──
    #: URL of the specification the bundle follows.
    spec_url: str | None = field(default=None, metadata={"json": "specURL"})
    #: Earliest/latest episode ``eventTime`` in the bundle; absent when it has no episodes.
    coverage: MemCoverage | None = field(default=None, metadata={"json": "coverage"})
    #: Sorted, unique scope (context) ids the exported records reference; absent when none.
    scopes: list[str] | None = field(default=None, metadata={"json": "scopes"})
    #: Lowercase-hex SHA-256 of the exact ``CHECKSUMS`` bytes — one hash for the whole
    #: archive. Validators recompute it when present.
    bundle_digest: str | None = field(default=None, metadata={"json": "bundleDigest"})


class MemLimits:
    """Bounds for reading untrusted bundles. A ``.mem`` may come from anywhere and the
    reference reader loads files into memory, so a size cap prevents a hostile or
    accidental multi-gigabyte file from exhausting memory."""
    #: Maximum bytes for any single bundle file (default 256 MiB). Tunable by adopters.
    max_file_bytes = 256 * 1024 * 1024

    @staticmethod
    def file_size(path: str | os.PathLike) -> int | None:
        try:
            return os.path.getsize(path)
        except OSError:
            return None


class BundlePath:
    """A ``.mem`` is untrusted input. A crafted ``manifest.json`` could list a path with
    an absolute root, ``..`` segments, or a symlink to make a reader touch files OUTSIDE
    the bundle. Validate every manifest-declared path before resolving it."""

    @staticmethod
    def is_safe(relative_path: str) -> bool:
        if not relative_path or relative_path.startswith("/") or relative_path.startswith("~"):
            return False
        # Reject Windows-style roots / drive letters and backslash separators too.
        if "\\" in relative_path or ":" in relative_path:
            return False
        for part in relative_path.split("/"):
            if part in ("..", "."):
                return False
        return True

    @staticmethod
    def safe_path(relative_path: str, root: str | os.PathLike) -> str | None:
        """Resolve ``relative_path`` under ``root``, returning it only if it is string-safe
        AND does not, after symlink resolution, escape the bundle. Returns ``None`` if the
        entry is itself a symlink or resolves outside the root."""
        if not BundlePath.is_safe(relative_path):
            return None
        root_s = os.fspath(root)
        joined = os.path.join(root_s, relative_path)
        if os.path.islink(joined):
            return None
        root_real = os.path.realpath(root_s)
        resolved = os.path.realpath(joined)
        if resolved != root_real and not resolved.startswith(root_real + os.sep):
            return None
        return joined
