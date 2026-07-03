"""Conformance-vector loader: proves this SDK reproduces the shared, language-neutral
vectors in Conformance/vectors/ (byte-identical to the Swift repo). If a canonicalization
rule ever drifts, this fails immediately — the vectors are the cross-implementation oracle."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from portable_memory import (BundleValidator, PortableSigning, PortableSigningKey,
                             PortableVerifyingKey, canonical_json, sha256_hex)

VECTORS = Path(__file__).resolve().parents[1] / "Conformance" / "vectors"


def _load(name):
    return json.load(open(VECTORS / name, encoding="utf-8"))


def test_canonical_json_vectors():
    doc = _load("canonical-json.json")
    assert doc["vectors"], "no vectors loaded"
    for v in doc["vectors"]:
        got = canonical_json(v["input"])
        assert got == v["canonical"], f"{v['name']}: {got!r} != {v['canonical']!r}"
        assert sha256_hex(got.encode("utf-8")) == v["sha256"], v["name"]


def test_signed_fixture_verifies_and_rejects():
    key = _load("signing-test-key.json")
    trusted = PortableVerifyingKey(raw_representation=bytes.fromhex(key["publicKeyHex"]))
    wrong = PortableSigningKey().verifying_key
    signed = VECTORS / "signed.mem"

    assert BundleValidator().validate(signed, trusted_keys=[trusted]).ok
    assert not BundleValidator().validate(signed, trusted_keys=[wrong]).ok


def test_signed_fixture_sign_verify_roundtrip():
    key = _load("signing-test-key.json")
    signing = PortableSigningKey(raw_representation=bytes.fromhex(key["privateKeyHex"]))
    # The reconstructed key's public half matches the published one.
    assert signing.verifying_key.hex == key["publicKeyHex"]
    manifest = (VECTORS / "signed.mem" / "manifest.json").read_bytes()
    token = PortableSigning.detached_token(manifest, signing)
    trusted = PortableVerifyingKey(raw_representation=bytes.fromhex(key["publicKeyHex"]))
    assert PortableSigning.verify(token, manifest, [trusted])
