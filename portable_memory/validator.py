"""Bundle validation — the L0 conformance check and a pre-flight any adopter can run.

Validates a ``.mem`` bundle WITHOUT importing it: the manifest parses, the major format
matches, every listed file resolves safely and matches its checksum + byte count, no
unlisted data files were injected under ``items/``/``audit``/``embeddings``, and every
known-kind stream decodes. Optionally it also checks AUTHENTICITY — when ``trusted_keys``
is non-empty, a valid ``manifest.sig`` signed by one of those keys is required.

Faithful port of the Swift ``BundleValidator`` (``BundleValidator.swift``): it collects
every issue rather than throwing on the first, so a caller sees the full picture in one
pass. Integrity is always checked; authenticity only when trusted keys are supplied.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from ._codec import from_wire
from .format import BundlePath, MemFormat, MemKind, MemLimits, MemManifest
from .hashing import sha256_hex
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
from .signing import PortableSigning, PortableVerifyingKey

#: One dataclass per known kind. A known-kind stream must decode into its type; unknown
#: kinds (foreign ``items/<vendorKind>.jsonl``) are intentionally opaque and skipped here.
_RECORD_TYPES: dict[MemKind, type] = {
    MemKind.EPISODE: PortableEpisode,
    MemKind.ENTITY: PortableEntity,
    MemKind.EDGE: PortableEdge,
    MemKind.FACT: PortableFact,
    MemKind.FACT_LINK: PortableFactLink,
    MemKind.EPISODE_LINK: PortableEpisodeLink,
    MemKind.RESOURCE: PortableResource,
    MemKind.CHUNK: PortableChunk,
    MemKind.CORE: PortableCore,
    MemKind.PROCEDURE: PortableProcedure,
    MemKind.CONTEXT: PortableContext,
    MemKind.COMMUNITY: PortableCommunity,
    MemKind.CATEGORY: PortableCategory,
    MemKind.PREFERENCE: PortablePreference,
    MemKind.SECRET_REF: PortableSecretRef,
}


@dataclass
class ValidationResult:
    """Outcome of a validation pass. ``ok`` is derived — a clean bundle has no issues."""
    manifest: MemManifest | None = None
    issues: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.issues == []


class BundleValidator:
    """Validates a ``.mem`` bundle without importing it.

    Verifies the manifest parses, every listed file matches its checksum, no unlisted data
    files were injected, and known-kind streams decode. Returns a :class:`ValidationResult`
    carrying any issues rather than throwing on the first problem.
    """

    def validate(
        self,
        bundle: str | os.PathLike,
        trusted_keys: list[PortableVerifyingKey] = (),
    ) -> ValidationResult:
        """Validate the bundle rooted at ``bundle``.

        When ``trusted_keys`` is non-empty, a valid ``manifest.sig`` signed by one of those
        keys is also required (authenticity); otherwise only integrity (checksums, byte
        counts, no unlisted files, decodability) is checked.
        """
        issues: list[str] = []
        root = os.fspath(bundle)

        manifest_path = os.path.join(root, "manifest.json")
        try:
            with open(manifest_path, "rb") as fh:
                manifest_bytes = fh.read()
        except OSError:
            return ValidationResult(manifest=None, issues=["manifest.json missing"])

        # A malformed manifest — bad JSON, missing/typed-wrong fields, unknown enum value —
        # all funnel into a single "does not parse" issue, matching Swift's decode guard.
        try:
            manifest = from_wire(MemManifest, json.loads(manifest_bytes))
        except Exception:
            return ValidationResult(manifest=None, issues=["manifest.json does not parse"])

        # Major-version compatibility: only the leading component of the semantic version
        # gates readability. A differing minor/patch is forward/backward compatible.
        if manifest.format.split(".")[0] != MemFormat.VERSION.split(".")[0]:
            issues.append(
                f"major format mismatch: bundle {manifest.format} vs reader {MemFormat.VERSION}"
            )

        # ── Authenticity (only when the caller supplies trusted keys). ──
        # The signature covers the EXACT manifest.json bytes on disk, which transitively
        # authenticate every file via its sha256; so we verify over `manifest_bytes`.
        if trusted_keys:
            sig_path = os.path.join(root, "manifest.sig")
            token = self._read_sig_token(sig_path)
            if token is None:
                issues.append("manifest.sig missing (signature required)")
            elif not PortableSigning.verify(token, manifest_bytes, trusted_keys):
                issues.append("manifest signature invalid or not signed by a trusted key")

        # ── Integrity: every listed file resolves safely, fits the size cap, and matches
        #    its checksum + byte count. ──
        listed = {f.path for f in manifest.files}
        for f in manifest.files:
            file_path = BundlePath.safe_path(f.path, root)
            if file_path is None:
                issues.append(f"path escapes the bundle: {f.path}")
                continue
            size = MemLimits.file_size(file_path)
            # A missing file yields size=None here; skip the cap check and let the read
            # below report it as "listed file missing" (mirrors Swift's `if let size`).
            if size is not None and size > MemLimits.max_file_bytes:
                issues.append(f"file exceeds size limit: {f.path}")
                continue
            try:
                with open(file_path, "rb") as fh:
                    data = fh.read()
            except OSError:
                issues.append(f"listed file missing: {f.path}")
                continue
            if sha256_hex(data) != f.sha256:
                issues.append(f"checksum mismatch: {f.path}")
            if len(data) != f.bytes:
                issues.append(f"byte-count mismatch: {f.path}")

        # ── No unlisted data files smuggled into the standard bundle subdirectories. ──
        for sub in ("items", "audit", "embeddings"):
            try:
                entries = os.listdir(os.path.join(root, sub))
            except OSError:
                continue  # subdir absent — nothing to police.
            for name in entries:
                if f"{sub}/{name}" not in listed:
                    issues.append(f"unlisted file present: {sub}/{name}")

        # ── Known-kind streams must decode (unknown kinds are intentionally opaque). ──
        for kind, record_type in _RECORD_TYPES.items():
            stream_path = os.path.join(root, "items", f"{kind.value}.jsonl")
            try:
                with open(stream_path, "rb") as fh:
                    stream = fh.read()
            except OSError:
                continue  # stream absent — that kind simply carries no records.
            text = stream.decode("utf-8", errors="replace")
            # Skip blank lines; report at most one malformed record per kind (Swift breaks
            # on the first failure so a corrupt stream doesn't flood the issue list).
            for line in text.split("\n"):
                s = line.strip()
                if not s:
                    continue
                if not self._decodes(record_type, s):
                    issues.append(f"malformed {kind.value} record")
                    break

        return ValidationResult(manifest=manifest, issues=issues)

    @staticmethod
    def _read_sig_token(path: str) -> str | None:
        """Read a detached ``manifest.sig`` and return its trimmed UTF-8 token, or ``None``
        when the file is missing or not valid UTF-8 (both treated as "no signature")."""
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
        except OSError:
            return None
        try:
            return raw.decode("utf-8").strip()
        except UnicodeDecodeError:
            return None

    @staticmethod
    def _decodes(record_type: type, line: str) -> bool:
        """True iff one JSONL line decodes into ``record_type`` through the canonical codec."""
        try:
            from_wire(record_type, json.loads(line))
            return True
        except Exception:
            return False
