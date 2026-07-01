"""Cross-implementation byte-interop against the shipped Swift fixture.

The fixture ``Conformance/fixtures/sample.mem`` is a byte-for-byte copy of the bundle the
Swift reference SDK produces (its own ``testConformanceFixtureValidates`` guards it against
drift). This module proves the Python SDK is INTEROPERABLE with those exact bytes, not
merely internally consistent:

  1. ``BundleValidator().validate`` accepts the Swift-authored bundle (checksums, byte
     counts, no unlisted files, known-kind decodability).
  2. Every known record — episode / entity / edge / tombstone — decoded from the fixture
     and RE-SERIALIZED through the Python canonical codec reproduces the original line
     byte-for-byte (canonical JSON agrees across implementations).
  3. Re-hashing each listed file reproduces the ``sha256`` the Swift-written manifest
     declares (the two implementations compute identical content bytes and digests).

If any of these fail, a bundle written by one implementation would not verify in the
other — the guarantee the whole standard rests on (spec §1.1).
"""
from __future__ import annotations

import json
from pathlib import Path

from portable_memory import (
    BundleValidator,
    PortableEdge,
    PortableEntity,
    PortableEpisode,
    Tombstone,
    from_wire,
    to_line,
)
from portable_memory.hashing import sha256_hex
from portable_memory.interop import extract_episode_ext, merge_episode_ext

_FIXTURE = Path(__file__).resolve().parent.parent / "Conformance" / "fixtures" / "sample.mem"


def _lines(rel: str) -> list[str]:
    """Non-empty JSONL lines of a fixture file, in file order (NOT re-sorted)."""
    text = (_FIXTURE / rel).read_bytes().decode("utf-8")
    return [line for line in text.split("\n") if line.strip()]


def test_fixture_validates() -> None:
    res = BundleValidator().validate(str(_FIXTURE))
    assert res.ok, f"Swift-authored fixture must validate in Python: {res.issues}"


def test_episode_lines_reserialize_byte_identical() -> None:
    # The second fixture episode carries a foreign field (``vendorScore``). To reproduce
    # the original line, foreign keys must be extracted and merged back — exactly what the
    # exporter does — since the DTO alone drops them.
    for line in _lines("items/episode.jsonl"):
        episode = from_wire(PortableEpisode, json.loads(line))
        native = to_line(episode).encode("utf-8")
        ext = extract_episode_ext(line)
        merged = merge_episode_ext(native, ext).decode("utf-8")
        assert merged == line, "episode line is not byte-identical after re-serialization"


def test_entity_lines_reserialize_byte_identical() -> None:
    for line in _lines("items/entity.jsonl"):
        entity = from_wire(PortableEntity, json.loads(line))
        assert to_line(entity) == line, "entity line is not byte-identical"


def test_edge_lines_reserialize_byte_identical() -> None:
    for line in _lines("items/edge.jsonl"):
        edge = from_wire(PortableEdge, json.loads(line))
        assert to_line(edge) == line, "edge line is not byte-identical"


def test_tombstone_lines_reserialize_byte_identical() -> None:
    for line in _lines("audit/tombstones.jsonl"):
        tombstone = from_wire(Tombstone, json.loads(line))
        assert to_line(tombstone) == line, "tombstone line is not byte-identical"


def test_file_hashes_match_manifest() -> None:
    """Re-hash every listed file and confirm it matches the manifest's declared sha256 —
    proving the Python digest agrees with the Swift-written manifest byte-for-byte."""
    manifest = json.loads((_FIXTURE / "manifest.json").read_bytes())
    files = manifest["files"]
    assert files, "fixture manifest must list files"
    for entry in files:
        data = (_FIXTURE / entry["path"]).read_bytes()
        assert sha256_hex(data) == entry["sha256"], f"hash mismatch for {entry['path']}"
        assert len(data) == entry["bytes"], f"byte-count mismatch for {entry['path']}"
