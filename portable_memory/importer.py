"""Bundle importer — reads a ``.mem`` bundle into a :class:`PortableMemoryStore`.

Mirrors the Swift ``BundleImporter`` (``Sources/PortableMemory/BundleImporter.swift``)
one-for-one, but synchronously: the Swift SDK uses ``async`` only for actor isolation
of the store; local file I/O in Python is done synchronously. The MERGE SEMANTICS are
identical — same ordering, same integrity checks, same tombstone no-resurrection guard.

Guarantees implemented here (spec §4, §5, §10):
  * Idempotent, merge-by-id import.
  * Tombstones applied FIRST, then every merge is guarded so a tombstoned id can never
    be resurrected — for ANY kind (the L2 guarantee).
  * Integrity is verified for the WHOLE bundle before a single write happens.
  * Foreign fields (episode ``ext``) and foreign kinds (unknown ``items/*.jsonl``)
    round-trip losslessly.
  * The host re-derives its own artifacts (FTS, embeddings, …) in ``finalize_import``.

Standard library only. Signature verification lives in ``signing.py`` (which lazily
imports ``cryptography``); this module touches signing only through ``PortableSigning``.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from enum import Enum
from typing import Iterable, Sequence

from ._codec import from_wire
from .format import BundlePath, MemKind, MemLimits, MemManifest
from .hashing import sha256_hex
from .interop import extract_episode_ext
from .records import (
    MemImportReport,
    PortableChunk,
    PortableCategory,
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
from .signing import PortableSigning, PortableVerifyingKey
from .store import PortableMemoryStore
from .tombstone import Tombstone


class _MemImportErrorKind(str, Enum):
    """The discriminant behind :class:`MemImportError` (mirrors the Swift enum cases)."""
    MANIFEST_MISSING = "manifest_missing"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    DIMENSION_MISMATCH = "dimension_mismatch"
    SIGNATURE_INVALID = "signature_invalid"


class MemImportError(Exception):
    """A fatal error raised before/while importing a bundle.

    One exception type with a ``kind`` discriminant, mirroring the Swift
    ``MemImportError`` enum. The four constructors below produce the same human-readable
    messages as the Swift ``description`` so tooling and tests can rely on identical text.
    """

    def __init__(self, kind: _MemImportErrorKind, message: str):
        self.kind = kind
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:  # noqa: D401 - matches Swift `description`
        return self.message

    # Factory constructors — one per Swift case, so callers read `MemImportError.manifest_missing(p)`.
    @classmethod
    def manifest_missing(cls, path: str) -> "MemImportError":
        return cls(_MemImportErrorKind.MANIFEST_MISSING, f"manifest not found at {path}")

    @classmethod
    def checksum_mismatch(cls, file: str) -> "MemImportError":
        return cls(
            _MemImportErrorKind.CHECKSUM_MISMATCH,
            f"checksum mismatch for {file} — bundle is corrupt (integrity failure)",
        )

    @classmethod
    def dimension_mismatch(cls, expected: int, got: int) -> "MemImportError":
        return cls(
            _MemImportErrorKind.DIMENSION_MISMATCH,
            f"embedding dimension mismatch: bundle={got}, store={expected}.",
        )

    @classmethod
    def signature_invalid(cls, message: str) -> "MemImportError":
        return cls(
            _MemImportErrorKind.SIGNATURE_INVALID,
            f"bundle signature verification failed: {message}",
        )


class BundleImporter:
    """Reads a ``.mem`` bundle into any :class:`PortableMemoryStore` (spec §4).

    Idempotent and merge-by-id; tombstones applied FIRST (no resurrection); integrity
    verified before any write; foreign fields (``ext``) and foreign kinds preserved; the
    host re-derives its own artifacts in ``finalize_import``.
    """

    def import_bundle(
        self,
        store: PortableMemoryStore,
        dir: str | os.PathLike,
        reembed: bool = True,
        dry_run: bool = False,
        trusted_keys: Sequence[PortableVerifyingKey] = (),
    ) -> MemImportReport:
        """Import a bundle.

        When ``trusted_keys`` is non-empty the bundle MUST carry a valid ``manifest.sig``
        signed by one of those keys (authenticity, spec §1.2); otherwise import raises.
        An empty sequence skips signature checking (integrity via checksums still always
        runs).
        """
        bundle_dir = os.fspath(dir)

        # 1. Manifest + authenticity + integrity.
        manifest_path = os.path.join(bundle_dir, "manifest.json")
        manifest_data = self._read_bytes(manifest_path)
        if manifest_data is None:
            raise MemImportError.manifest_missing(manifest_path)
        manifest = from_wire(MemManifest, json.loads(manifest_data))
        if trusted_keys:
            self._verify_manifest_signature(bundle_dir, manifest_data, trusted_keys)
        self._verify_checksums(bundle_dir, manifest)
        info = store.store_info()
        # Only meaningful when the bundle actually ships vectors AND the store declares a
        # dimension; a store that does not embed (dim 0) accepts any bundle and re-embeds.
        if manifest.embeddings_included and info.embedding_dim > 0 and manifest.embedding_dim != info.embedding_dim:
            raise MemImportError.dimension_mismatch(expected=info.embedding_dim, got=manifest.embedding_dim)

        report = MemImportReport()
        if dry_run:
            # Report the manifest's own counts for known kinds only (foreign kinds are not
            # projected here) — matching Swift, which filters counts by MemKind(rawValue:).
            report.applied = {k: v for k, v in manifest.counts.items() if _is_known_kind(k)}
            report.tombstones_applied = manifest.counts.get("tombstone", 0)
            return report

        # 2. Tombstones FIRST (§5).
        for t in self._read_jsonl(bundle_dir, "audit/tombstones.jsonl", Tombstone):
            store.apply_tombstone(t)
            report.tombstones_applied += 1
        tombstoned = set(store.tombstoned_target_ids())

        def bump(kind: MemKind, n: int = 1) -> None:
            report.applied[kind.value] = report.applied.get(kind.value, 0) + n

        # A tombstoned id must NEVER be resurrected by a later merge, for ANY kind — this
        # is the L2 guarantee (spec §5): even when a (stale) bundle still ships the row,
        # the earlier-applied tombstone wins. `gone` guards every merge-by-id call; a row
        # is refused when its own id — or a parent it cannot exist without — is
        # tombstoned. Guarding here (not per-kind, ad hoc) is what keeps the guarantee
        # complete as kinds are added.
        def gone(*ids: str | None) -> bool:
            if not any(i in tombstoned for i in ids):
                return False
            report.skipped_tombstoned += 1
            return True

        # 3. Merge items by id, dependency order.
        for c in self._read_jsonl(bundle_dir, "items/context.jsonl", PortableContext):
            if gone(c.id):
                continue
            store.import_context(c)
            bump(MemKind.CONTEXT)
        # category (keyed by name) and preference (keyed by key) carry no id and are not
        # id-targetable by a tombstone, so they merge unconditionally.
        for c in self._read_jsonl(bundle_dir, "items/category.jsonl", PortableCategory):
            store.import_category(c)
            bump(MemKind.CATEGORY)
        for p in self._read_jsonl(bundle_dir, "items/preference.jsonl", PortablePreference):
            store.import_preference(p)
            bump(MemKind.PREFERENCE)
        for c in self._read_jsonl(bundle_dir, "items/core.jsonl", PortableCore):
            if gone(c.id):
                continue
            store.import_core_block(c)
            bump(MemKind.CORE)
        for e in self._read_jsonl(bundle_dir, "items/entity.jsonl", PortableEntity):
            if gone(e.id):
                continue
            store.import_entity(e)
            bump(MemKind.ENTITY)

        imported_episode_ids: list[str] = []
        for line, e in self._read_episodes(bundle_dir, "items/episode.jsonl"):
            if gone(e.id):
                continue
            # Foreign (non-native) episode fields are pulled from the RAW line so they
            # round-trip; the store persists them opaquely as `ext` (spec §1, §10).
            store.import_episode(e, extract_episode_ext(line))
            imported_episode_ids.append(e.id)
            bump(MemKind.EPISODE)
        for r in self._read_jsonl(bundle_dir, "items/resource.jsonl", PortableResource):
            if gone(r.id):
                continue
            store.import_resource(r)
            bump(MemKind.RESOURCE)
        for c in self._read_jsonl(bundle_dir, "items/chunk.jsonl", PortableChunk):
            if gone(c.id, c.resource_id):
                continue
            store.import_chunk(c)
            bump(MemKind.CHUNK)
        for edge in self._read_jsonl(bundle_dir, "items/edge.jsonl", PortableEdge):
            if gone(edge.id, edge.src_entity_id, edge.dst_entity_id):
                continue
            store.import_edge(edge)
            bump(MemKind.EDGE)
        for f in self._read_jsonl(bundle_dir, "items/fact.jsonl", PortableFact):
            if gone(f.id, f.episode_id):
                continue
            store.import_fact(f)
            bump(MemKind.FACT)
        for fl in self._read_jsonl(bundle_dir, "items/factLink.jsonl", PortableFactLink):
            if gone(fl.src_fact_id, fl.dst_fact_id):
                continue
            store.import_fact_link(fl)
            bump(MemKind.FACT_LINK)
        for el in self._read_jsonl(bundle_dir, "items/episodeLink.jsonl", PortableEpisodeLink):
            if gone(el.src_episode_id, el.dst_episode_id):
                continue
            store.import_episode_link(el)
            bump(MemKind.EPISODE_LINK)
        for p in self._read_jsonl(bundle_dir, "items/procedure.jsonl", PortableProcedure):
            if gone(p.id):
                continue
            store.import_procedure(p)
            bump(MemKind.PROCEDURE)
        for c in self._read_jsonl(bundle_dir, "items/community.jsonl", PortableCommunity):
            if gone(c.id):
                continue
            store.import_community(c)
            bump(MemKind.COMMUNITY)
        restored_refs = 0
        for r in self._read_jsonl(bundle_dir, "items/secretRef.jsonl", PortableSecretRef):
            if gone(r.id):
                continue
            store.import_secret_ref(r)
            bump(MemKind.SECRET_REF)
            restored_refs += 1
        if restored_refs > 0:
            report.warnings.append(
                f"{restored_refs} secret reference(s): metadata skeleton restored, but the encrypted "
                "VALUE is not in the bundle — transfer it via an authorized encrypted channel (spec §7)."
            )

        # 4. Unknown-kind passthrough — store foreign kinds verbatim (§10). Already
        #    integrity-checked (listed in the manifest). Foreign records are opaque to
        #    this engine, so a tombstone targeting one cannot be enforced here; a store
        #    that natively models the kind is responsible for honoring it.
        known_files = {f"{kind.value}.jsonl" for kind in MemKind}
        items_dir = os.path.join(bundle_dir, "items")
        for name in self._list_dir(items_dir):
            if not name.endswith(".jsonl") or name in known_files:
                continue
            kind = name[: -len(".jsonl")]
            lines = self._raw_lines(os.path.join(items_dir, name))
            if not lines:
                continue
            store.store_passthrough(kind, lines)
            report.applied[kind] = report.applied.get(kind, 0) + len(lines)

        # 5. Host re-derives FTS/sentences/embeddings; then converge the replica.
        report.reembedded = store.finalize_import(imported_episode_ids, reembed)
        store.sync()
        return report

    # ------------------------------------------------------------------ Internals

    def _verify_manifest_signature(
        self, bundle_dir: str, manifest_data: bytes, trusted: Sequence[PortableVerifyingKey]
    ) -> None:
        """Require a ``manifest.sig`` token signed by a trusted key over the manifest bytes.

        The signature covers ``manifest.json`` verbatim, which transitively covers every
        file in the bundle via its listed sha256 — so a valid signature attests the whole
        bundle (spec §1.2).
        """
        sig_path = os.path.join(bundle_dir, "manifest.sig")
        sig_data = self._read_bytes(sig_path)
        if sig_data is None:
            raise MemImportError.signature_invalid("manifest.sig missing")
        token = sig_data.decode("utf-8", errors="replace").strip()
        if not PortableSigning.verify(token=token, data=manifest_data, trusted=trusted):
            raise MemImportError.signature_invalid("manifest.sig invalid or not signed by a trusted key")

    def _verify_checksums(self, bundle_dir: str, manifest: MemManifest) -> None:
        """Verify every listed file's sha256 and reject any unlisted data file.

        Runs before ANY write, so a corrupt or tampered bundle is rejected atomically.
        """
        listed = {f.path for f in manifest.files}
        for f in manifest.files:
            # A crafted manifest must not escape the bundle — via absolute/.. paths OR a
            # planted symlink whose target lies outside the bundle.
            file_path = BundlePath.safe_path(f.path, bundle_dir)
            if file_path is None:
                raise MemImportError.checksum_mismatch(f"{f.path} (path escapes the bundle)")
            size = MemLimits.file_size(file_path)
            if size is not None and size > MemLimits.max_file_bytes:
                raise MemImportError.checksum_mismatch(
                    f"{f.path} (exceeds {MemLimits.max_file_bytes}-byte limit)"
                )
            data = self._read_bytes(file_path)
            if data is None:
                raise MemImportError.checksum_mismatch(f"{f.path} (missing)")
            if sha256_hex(data) != f.sha256:
                raise MemImportError.checksum_mismatch(f.path)
        # No UNLISTED data file may be present — the importer reads items/ and audit/ by
        # fixed path, so an injected file would otherwise be ingested unverified.
        for sub in ("items", "audit", "embeddings"):
            sub_dir = os.path.join(bundle_dir, sub)
            for name in self._list_dir(sub_dir):
                rel = f"{sub}/{name}"
                if rel not in listed:
                    raise MemImportError.checksum_mismatch(f"{rel} (present but not listed in manifest)")

    def _read_episodes(self, bundle_dir: str, rel_path: str) -> list[tuple[bytes, PortableEpisode]]:
        """Read ``items/episode.jsonl`` as (raw line bytes, decoded episode) pairs.

        The raw bytes are kept so foreign fields can be extracted into ``ext`` after
        decoding (the decoder drops any key not on :class:`PortableEpisode`).
        """
        path = os.path.join(bundle_dir, rel_path)
        data = self._read_bytes(path)
        if data is None:
            return []
        out: list[tuple[bytes, PortableEpisode]] = []
        for raw in data.decode("utf-8").split("\n"):
            s = raw.strip()
            if not s:
                continue
            line = s.encode("utf-8")
            out.append((line, from_wire(PortableEpisode, json.loads(line))))
        return out

    def _raw_lines(self, path: str) -> list[str]:
        """Verbatim line content for unknown-kind passthrough.

        Does NOT trim, so each record's bytes survive a round-trip unchanged (only the
        ``\\n`` framing, inherent to JSONL, is normalized; empty lines carry no record and
        are dropped).
        """
        data = self._read_bytes(path)
        if data is None:
            return []
        return [line for line in data.decode("utf-8").split("\n") if line != ""]

    def _read_jsonl(self, bundle_dir: str, rel_path: str, cls: type) -> list:
        """Decode a JSONL file into a list of ``cls`` instances (skipping blank lines).

        Missing file → empty list, matching the Swift reader (a bundle need not carry a
        file for every kind).
        """
        path = os.path.join(bundle_dir, rel_path)
        data = self._read_bytes(path)
        if data is None:
            return []
        out: list = []
        for raw in data.decode("utf-8").split("\n"):
            s = raw.strip()
            if not s:
                continue
            out.append(from_wire(cls, json.loads(s)))
        return out

    @staticmethod
    def _read_bytes(path: str) -> bytes | None:
        """Read a file's bytes, size-bounded. Returns ``None`` when it does not exist.

        The size cap is enforced BEFORE the read so a hostile multi-gigabyte file can
        never be slurped into memory (untrusted-input safety). Files verified in
        ``_verify_checksums`` are already known to be within the cap; this second check
        covers the fixed-path reads (manifest, tombstones, episodes, …) that are not
        individually pre-checked there.
        """
        size = MemLimits.file_size(path)
        if size is None:
            return None  # missing / unstat-able
        if size > MemLimits.max_file_bytes:
            raise MemImportError.checksum_mismatch(
                f"{path} (exceeds {MemLimits.max_file_bytes}-byte limit)"
            )
        try:
            with open(path, "rb") as fh:
                return fh.read()
        except OSError:
            return None

    @staticmethod
    def _list_dir(path: str) -> list[str]:
        """Directory entry names, or an empty list when the directory is absent."""
        try:
            return os.listdir(path)
        except OSError:
            return []


def _is_known_kind(raw: str) -> bool:
    """True when ``raw`` is a known :class:`MemKind` value (used for dry-run count filtering)."""
    try:
        MemKind(raw)
        return True
    except ValueError:
        return False
