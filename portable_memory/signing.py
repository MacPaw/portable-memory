"""Ed25519 signing — bundle & tombstone authenticity (spec §1.2, §7, L3).

Checksums (``CHECKSUMS`` / ``manifest.files[].sha256``) give INTEGRITY — they detect
corruption in transit. They do NOT give AUTHENTICITY: anyone who can edit a file can
recompute its public SHA-256 and rewrite the manifest. Ed25519 signatures close that
gap. Signing the manifest (which transitively covers every file via its hash) proves the
WHOLE bundle came from a holder of the private key; signing a tombstone proves a specific
deletion is genuine. Keys are distributed out of band; this module provides only the
primitives + the wire format.

Signature token wire format:  ``ed25519:<publicKeyHex>:<signatureHex>``
The public key travels with the signature so a verifier can select which trusted key to
check against — but verification only succeeds when that key is in the caller's trusted
set, so a self-signed swap is rejected.

This is the one module that reaches outside the standard library: Ed25519 lives in the
optional ``cryptography`` package, imported lazily so the rest of the SDK stays
dependency-free. Install it with ``pip install portable-memory[signing]``.
"""
from __future__ import annotations

from dataclasses import replace

from ._codec import to_line
from .tombstone import Tombstone

__all__ = [
    "PortableSigningKey",
    "PortableVerifyingKey",
    "PortableSigning",
    "sign_tombstone",
    "tombstone_signature_valid",
]


def _ed25519():
    """Lazily import the Ed25519 primitives from the optional ``cryptography`` package.

    Kept in one place so every entry point raises the same actionable error when the
    dependency is missing, and so importing this module never fails on its own.
    """
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ImportError(
            "Ed25519 signing requires the 'cryptography' package. "
            "Install it with: pip install portable-memory[signing]"
        ) from exc
    return ed25519


class PortableSigningKey:
    """An Ed25519 private (signing) key, carried as its raw 32-byte representation.

    ``PortableSigningKey()`` generates a fresh key; ``PortableSigningKey(raw_representation=...)``
    reconstructs one from stored bytes.
    """

    __slots__ = ("raw_representation",)

    def __init__(self, raw_representation: bytes | None = None) -> None:
        ed25519 = _ed25519()
        if raw_representation is None:
            # Generate a fresh key and keep only its raw bytes, mirroring the Swift type
            # which stays value-like (Sendable) by never holding the live key object.
            key = ed25519.Ed25519PrivateKey.generate()
            raw_representation = key.private_bytes_raw()
        self.raw_representation: bytes = bytes(raw_representation)

    @property
    def verifying_key(self) -> "PortableVerifyingKey":
        ed25519 = _ed25519()
        key = ed25519.Ed25519PrivateKey.from_private_bytes(self.raw_representation)
        return PortableVerifyingKey(raw_representation=key.public_key().public_bytes_raw())

    def sign(self, data: bytes) -> bytes:
        ed25519 = _ed25519()
        key = ed25519.Ed25519PrivateKey.from_private_bytes(self.raw_representation)
        return key.sign(data)


class PortableVerifyingKey:
    """An Ed25519 public (verifying) key, carried as its raw 32-byte representation.

    Value-typed like the Swift counterpart: equality and hashing are over the raw bytes
    so a key can be looked up in a ``trusted`` list regardless of how it was constructed.
    """

    __slots__ = ("raw_representation",)

    def __init__(self, raw_representation: bytes) -> None:
        self.raw_representation: bytes = bytes(raw_representation)

    @property
    def hex(self) -> str:
        """Lowercase hex of the raw key bytes — matches Swift's ``Hex.encode`` output."""
        return self.raw_representation.hex()

    def is_valid(self, signature: bytes, data: bytes) -> bool:
        """True iff ``signature`` is a valid Ed25519 signature over ``data`` for this key.

        A malformed key or a bad signature raises inside ``cryptography``; we swallow that
        and fail closed, matching Swift's ``try?`` / ``isValidSignature`` semantics.
        """
        ed25519 = _ed25519()
        try:
            key = ed25519.Ed25519PublicKey.from_public_bytes(self.raw_representation)
            key.verify(signature, data)
        except Exception:
            return False
        return True

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PortableVerifyingKey):
            return NotImplemented
        return self.raw_representation == other.raw_representation

    def __hash__(self) -> int:
        return hash(self.raw_representation)


class PortableSigning:
    """Detached-signature token helpers (``ed25519:<pubHex>:<sigHex>``)."""

    @staticmethod
    def detached_token(data: bytes, key: PortableSigningKey) -> str:
        """Produce a detached signature TOKEN over ``data``.

        The token embeds the signer's public key so a verifier can pick which trusted key
        to check; both hex fields are lowercase to match the Swift wire format exactly.
        """
        sig = key.sign(data)
        return f"ed25519:{key.verifying_key.hex}:{sig.hex()}"

    @staticmethod
    def verify(token: str, data: bytes, trusted: list[PortableVerifyingKey]) -> bool:
        """Verify a detached signature token over ``data``.

        Succeeds only when the token's embedded public key is present in ``trusted`` AND
        the signature checks out. An empty ``trusted`` set fails closed — nothing is
        trusted, so nothing verifies.
        """
        # Do not drop empty subsequences, so a malformed token with extra ':' is rejected
        # by the exact-parts check rather than silently coalescing (matches Swift).
        parts = token.split(":")
        if len(parts) != 3 or parts[0] != "ed25519":
            return False
        try:
            pub = bytes.fromhex(parts[1])
            sig = bytes.fromhex(parts[2])
        except ValueError:
            return False
        vk = PortableVerifyingKey(raw_representation=pub)
        if vk not in trusted:
            return False
        return vk.is_valid(sig, data)


# MARK: - Tombstone signing (L3)
#
# The signature covers the tombstone's canonical bytes with the ``signature`` field
# itself absent. ``to_line`` omits ``None`` optionals, so clearing ``signature`` before
# encoding produces exactly the bytes Swift signs (``signature = nil`` -> field omitted).


def sign_tombstone(t: Tombstone, key: PortableSigningKey) -> Tombstone:
    """Return a copy of ``t`` carrying a detached signature over its unsigned canonical
    bytes. The input is not mutated."""
    unsigned = replace(t, signature=None)
    data = to_line(unsigned).encode("utf-8")
    token = PortableSigning.detached_token(data=data, key=key)
    return replace(t, signature=token)


def tombstone_signature_valid(t: Tombstone, trusted: list[PortableVerifyingKey]) -> bool:
    """True iff ``t`` carries a signature that verifies against ``trusted`` over its
    unsigned canonical bytes. An unsigned tombstone is invalid (fails closed)."""
    if t.signature is None:
        return False
    unsigned = replace(t, signature=None)
    data = to_line(unsigned).encode("utf-8")
    return PortableSigning.verify(token=t.signature, data=data, trusted=trusted)
