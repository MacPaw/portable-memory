"""SHA-256 content hashing + checksums (stdlib ``hashlib``; no dependency).

Lowercase-hex SHA-256 over the canonical bytes of a record gives a stable content hash;
over a file's bytes it gives the ``CHECKSUMS`` / ``manifest.files[].sha256`` integrity
value. Same bytes everywhere -> same hash everywhere.
"""
from __future__ import annotations

import hashlib


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_hex_str(text: str) -> str:
    return sha256_hex(text.encode("utf-8"))


def embedding_cache_key(model: str, text: str) -> str:
    """sha256(model ∥ NUL ∥ text) — the conventional embedding-cache key, restated so a
    deletion can reconstruct and evict the exact entries a piece of content produced
    (deletion propagation, spec §5)."""
    h = hashlib.sha256()
    h.update(model.encode("utf-8"))
    h.update(b"\x00")
    h.update(text.encode("utf-8"))
    return h.hexdigest()
