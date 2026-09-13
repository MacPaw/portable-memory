"""Portable Memory — an open, vendor-neutral format for AI memory portability.

Python reference SDK. The on-disk format is defined by ``Spec/portable-memory-spec.md``
and the language-neutral ``Schemas/``; this package is byte-for-byte interoperable with
the Swift reference SDK (github.com/MacPaw/portable-memory-swift).
"""
from __future__ import annotations

from ._codec import (
    canonical_json,
    format_timestamp,
    from_wire,
    parse_timestamp,
    to_line,
    to_wire,
)
from .format import (
    IMPORT_ORDER,
    BundlePath,
    ConformanceLevel,
    ExportMode,
    MemFileEntry,
    MemFormat,
    MemKind,
    MemLimits,
    MemManifest,
)
from .hashing import embedding_cache_key, sha256_hex, sha256_hex_str
from .interop import KNOWN_EPISODE_KEYS, extract_episode_ext, merge_episode_ext
from .records import (
    MemImportReport,
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
from .tombstone import DerivedRefs, PortableAuditRecord, Tombstone, TombstoneOp

__version__ = "0.1.2"

# Logic modules.
from .store import PortableMemoryStore, StoreInfo  # noqa: E402
from .inmemory import InMemoryStore  # noqa: E402
from .signing import (  # noqa: E402
    PortableSigning,
    PortableSigningKey,
    PortableVerifyingKey,
)
from .validator import BundleValidator, ValidationResult  # noqa: E402
from .exporter import BundleExporter  # noqa: E402
from .importer import BundleImporter, MemImportError  # noqa: E402

__all__ = [
    "canonical_json", "format_timestamp", "parse_timestamp", "to_wire", "from_wire", "to_line",
    "MemFormat", "MemKind", "IMPORT_ORDER", "ExportMode", "ConformanceLevel",
    "MemFileEntry", "MemManifest", "MemLimits", "BundlePath",
    "sha256_hex", "sha256_hex_str", "embedding_cache_key",
    "KNOWN_EPISODE_KEYS", "extract_episode_ext", "merge_episode_ext",
    "PortableEpisode", "PortableEntity", "PortableEdge", "PortableFact", "PortableFactLink",
    "PortableEpisodeLink", "PortableResource", "PortableChunk", "PortableCore",
    "PortableProcedure", "PortableContext", "PortableCommunity", "PortableCategory",
    "PortablePreference", "PortableSecretRef", "MemImportReport",
    "DerivedRefs", "TombstoneOp", "Tombstone", "PortableAuditRecord",
    "PortableMemoryStore", "StoreInfo", "InMemoryStore",
    "PortableSigning", "PortableSigningKey", "PortableVerifyingKey",
    "BundleValidator", "ValidationResult",
    "BundleExporter", "BundleImporter", "MemImportError",
]
