#!/usr/bin/env python3
"""Regenerate the conformance vectors + signed fixture, deterministically.

Run from anywhere:  python3 Conformance/vectors/generate.py
Rebuilds `canonical-json.json`, `signed.mem/`, and `signing-test-key.json` in this
directory from the reference encoder and a fixed test seed. README.md is hand-maintained
and left untouched. After running, confirm both SDK test suites stay green and copy the
regenerated files into the Swift repo byte-for-byte.
"""
import json
import os
import shutil
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

from portable_memory import (BundleExporter, BundleValidator, PortableEntity,  # noqa: E402
                             PortableEpisode, PortableMemoryStore, PortableSigningKey,
                             PortableVerifyingKey, StoreInfo, canonical_json, sha256_hex)
import portable_memory.exporter as _ex  # noqa: E402

# ---- canonical-json vectors -------------------------------------------------
# (name, input value). Floats stay floats in the file, so 1.0 differs from 1 for
# implementations that carry the distinction. See README for scope / residuals.
CASES = [
    ("number: whole-valued float -> integer",            {"a": 1.0}),
    ("number: whole-valued float 3.0 -> 3",              {"a": 3.0}),
    ("number: negative zero normalizes to 0",            {"a": -0.0}),
    ("number: fractional shortest form 0.7",             {"a": 0.7}),
    ("number: fractional shortest form 0.92",            {"a": 0.92}),
    ("number: 0.1+0.2 shortest form",                    {"a": 0.30000000000000004}),
    ("number: large integral double < 1e16 as digits",  {"a": 8000000000000000.0}),
    ("number: 2^53 exact",                               {"a": 9007199254740992.0}),
    ("number: plain integer",                            {"a": 100}),
    ("number: 2^53+1 integer exact",                     {"a": 9007199254740993}),
    ("number: Int64.max exact",                          {"a": 9223372036854775807}),
    ("number: UInt64.max exact (bigint field)",          {"a": 18446744073709551615}),
    ("number: mixed magnitudes",                         {"a": 123.456, "b": 0}),
    ("bool/null: preserved",                             {"t": True, "f": False, "n": None}),
    ("string: forward slash NOT escaped",                {"s": "a/b/c"}),
    ("string: non-ASCII emitted raw (not \\u)",          {"s": "café — 日本語 😀"}),
    ("string: short escape forms for tab/newline/quote/backslash",
                                                         {"s": "x\ty\nz\"q\\w"}),
    ("string: control char < 0x20 -> lowercase \\u00xx", {"s": ""}),
    ("string: empty string value",                       {"s": ""}),
    ("keys: sorted ascending (BMP)",                     {"z": 1, "a": 2, "m": 3}),
    ("keys: digit < uppercase < lowercase by code point", {"b": 1, "B": 2, "1": 3}),
    ("keys: sorted recursively in nested object",        {"z": {"y": 1, "x": 2}, "a": 3}),
    ("array: element order preserved (NOT sorted)",      {"a": [3, 1, 2]}),
    ("containers: empty object and array",               {"o": {}, "a": []}),
    ("top-level array",                                  [3, 1, 2]),
    ("top-level empty object",                           {}),
]

vectors = [{"name": n, "input": v, "canonical": canonical_json(v),
            "sha256": sha256_hex(canonical_json(v).encode("utf-8"))} for n, v in CASES]

doc = {
    "description": (
        "Portable Memory canonical-JSON conformance vectors (spec §1.1). For each entry, "
        "serializing `input` in Canonical JSON MUST equal `canonical` byte-for-byte, and "
        "sha256(utf8(canonical)) MUST equal `sha256`. Integer fields beyond 2^53 require a "
        "bigint-aware JSON parser. See README.md for scope and known residuals."),
    "formatVersion": "1.0.0",
    "vectors": vectors,
}
with open(os.path.join(HERE, "canonical-json.json"), "w", encoding="utf-8") as f:
    json.dump(doc, f, ensure_ascii=False, indent=2)
    f.write("\n")

# ---- deterministic signed fixture -------------------------------------------
SEED = bytes(range(32))                       # 00 01 .. 1f  — a TEST key, not a secret
key = PortableSigningKey(raw_representation=SEED)
T = datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)


def _ep(id_, summary, confidence, importance):
    return PortableEpisode(
        id=id_, event_time=T, mention_time=T, ingestion_time=T, source_type="note",
        actors=[], summary=summary, details=summary, sensitivity="low", metadata={},
        categories=[], importance=importance, confidence=confidence,
        lifecycle_state="HOT", extraction_state="done", access_count=0, pinned=False,
        vault_refs=[])


class _Store(PortableMemoryStore):
    def store_info(self):
        return StoreInfo(generator="portable-memory-vectors/1.0", schema_version=1)

    def export_episodes(self):
        # ep_0001 carries whole-valued floats + a 64-bit ext int, so the fixture also
        # witnesses the number-canonicalization guarantees.
        return [_ep("ep_0001", "Signed fixture episode.", 1.0, 3.0),
                _ep("ep_0002", "Second episode.", 0.7, 0.5)]

    def export_episode_ext(self):
        return {"ep_0001": json.dumps({"vendorScore": 0.92, "vendorId": 18446744073709551615})}

    def export_entities(self):
        return [PortableEntity(id="ent_0001", entity_type="person", canonical_name="Ada",
                               aliases=[], summary="", sensitivity="low", updated_at=T)]


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 7, 2, 0, 0, 0, tzinfo=timezone.utc)


shutil.rmtree(os.path.join(HERE, "signed.mem"), ignore_errors=True)
_ex.datetime = _FrozenDatetime
try:
    BundleExporter().export(_Store(), os.path.join(HERE, "signed.mem"), signing_key=key)
finally:
    _ex.datetime = datetime

with open(os.path.join(HERE, "signing-test-key.json"), "w") as f:
    json.dump({
        "_comment": "TEST KEY ONLY — not a real secret. Fixed 32-byte seed 00..1f.",
        "algorithm": "ed25519",
        "publicKeyHex": key.verifying_key.hex,
        "privateKeyHex": SEED.hex(),
    }, f, indent=2)
    f.write("\n")

vk = PortableVerifyingKey(raw_representation=bytes.fromhex(key.verifying_key.hex))
res = BundleValidator().validate(os.path.join(HERE, "signed.mem"), trusted_keys=[vk])
assert res.ok, res.issues
print(f"regenerated {len(vectors)} vectors + signed.mem (pub {key.verifying_key.hex})")
