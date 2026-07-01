"""Port of the Swift ``PortableMemoryTests`` suite (17 tests).

Each test here mirrors, one-for-one, a Swift ``XCTestCase`` method in
``portable-memory-swift/Tests/PortableMemoryTests/PortableMemoryTests.swift`` — same
scenario, same assertions — but synchronously (the Python SDK is not ``async``). The
in-memory store and the ``ep`` episode factory live in :mod:`conftest`.

The conformance-fixture validation test that Swift keeps in this file
(``testConformanceFixtureValidates``) plus the cross-implementation byte-interop checks
live in the dedicated :mod:`test_interop_fixture` module.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from conftest import InMemoryStore, ep

from portable_memory import (
    BundleExporter,
    BundleImporter,
    BundleValidator,
    DerivedRefs,
    MemFileEntry,
    MemImportError,
    MemKind,
    MemLimits,
    MemManifest,
    PortableEdge,
    PortableEntity,
    Tombstone,
    TombstoneOp,
    from_wire,
    to_line,
)
from portable_memory.adapters.mem0 import Mem0Adapter

_NOW = datetime.now(timezone.utc)


def _read_text(path: str | os.PathLike) -> str:
    """Read a bundle file as UTF-8 text (episode.jsonl assertions compare on text)."""
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Round-trip: lossless + idempotent.
# ─────────────────────────────────────────────────────────────────────────────
def test_round_trip_lossless_and_idempotent(tmp_path: Path) -> None:
    a = InMemoryStore()
    a.seed_episode(ep("ep_a", "alpha"))
    a.seed_episode(ep("ep_b", "beta"))
    a.seed_entity(
        PortableEntity(
            id="ent_1", entity_type="person", canonical_name="Sarah",
            aliases=[], summary="", sensitivity="low", updated_at=_NOW,
        )
    )
    a.seed_edge(
        PortableEdge(
            id="edge_1", src_entity_id="ent_1", dst_entity_id="ent_1",
            edge_type="self", t_valid_from=_NOW, t_valid_to=None,
            ingestion_time=_NOW, confidence=0.9,
            evidence_episode_ids=["ep_a"], superseded_by=None,
        )
    )

    d = str(tmp_path / "rt.mem")
    m = BundleExporter().export(a, d)
    assert m.counts[MemKind.EPISODE.value] == 2
    assert m.counts[MemKind.ENTITY.value] == 1
    assert m.counts[MemKind.EDGE.value] == 1

    c = InMemoryStore()
    r = BundleImporter().import_bundle(c, d)
    assert r.applied[MemKind.EPISODE.value] == 2
    assert c.episode_count() == 2
    assert c.summary_for("ep_a") == "alpha"

    # Re-import is a no-op (idempotent merge-by-id).
    BundleImporter().import_bundle(c, d)
    assert c.episode_count() == 2


# ─────────────────────────────────────────────────────────────────────────────
# 2. Tombstone-first: no resurrection (episode).
# ─────────────────────────────────────────────────────────────────────────────
def test_tombstone_first_no_resurrection(tmp_path: Path) -> None:
    a = InMemoryStore()
    a.seed_episode(ep("ep_x", "secret"))
    a.seed_episode(ep("ep_y", "ordinary"))
    bundle_all = str(tmp_path / "all.mem")
    BundleExporter().export(a, bundle_all)

    a.seed_tombstone(
        Tombstone(
            id="tomb_1", op=TombstoneOp.DELETE, target_kind="episode",
            target_id="ep_x", deleted_at=_NOW, reason="erasure",
            actor="user", derived=DerivedRefs(),
        )
    )
    bundle_del = str(tmp_path / "del.mem")
    dm = BundleExporter().export(a, bundle_del)
    assert dm.counts["tombstone"] == 1

    d = InMemoryStore()
    BundleImporter().import_bundle(d, bundle_del)   # tombstone for X first
    r = BundleImporter().import_bundle(d, bundle_all)  # bundle still HAS X
    assert r.skipped_tombstoned >= 1                # X refused — tombstone wins
    ids = d.episode_ids()
    assert "ep_x" not in ids                        # X never resurrected
    assert "ep_y" in ids


# ─────────────────────────────────────────────────────────────────────────────
# 3. L2 for non-episode kinds: entity/edge (by id and by endpoint) not resurrected.
# ─────────────────────────────────────────────────────────────────────────────
def test_tombstone_non_episode_kinds_not_resurrected(tmp_path: Path) -> None:
    a = InMemoryStore()
    a.seed_entity(
        PortableEntity(id="ent_keep", entity_type="person", canonical_name="Keep",
                       aliases=[], summary="", sensitivity="low", updated_at=_NOW)
    )
    a.seed_entity(
        PortableEntity(id="ent_kill", entity_type="person", canonical_name="Kill",
                       aliases=[], summary="", sensitivity="low", updated_at=_NOW)
    )
    # edge_self references only ent_keep; edge_dep references the doomed ent_kill.
    a.seed_edge(
        PortableEdge(id="edge_self", src_entity_id="ent_keep", dst_entity_id="ent_keep",
                     edge_type="self", t_valid_from=_NOW, t_valid_to=None, ingestion_time=_NOW,
                     confidence=0.9, evidence_episode_ids=[], superseded_by=None)
    )
    a.seed_edge(
        PortableEdge(id="edge_dep", src_entity_id="ent_keep", dst_entity_id="ent_kill",
                     edge_type="knows", t_valid_from=_NOW, t_valid_to=None, ingestion_time=_NOW,
                     confidence=0.9, evidence_episode_ids=[], superseded_by=None)
    )
    a.seed_edge(
        PortableEdge(id="edge_kill", src_entity_id="ent_keep", dst_entity_id="ent_keep",
                     edge_type="self", t_valid_from=_NOW, t_valid_to=None, ingestion_time=_NOW,
                     confidence=0.9, evidence_episode_ids=[], superseded_by=None)
    )

    bundle_all = str(tmp_path / "ne-all.mem")
    BundleExporter().export(a, bundle_all)  # captured while everything exists

    # Delete an entity (ent_kill) and an edge by its own id (edge_kill).
    a.seed_tombstone(
        Tombstone(id="tb_ent", op=TombstoneOp.DELETE, target_kind="entity",
                  target_id="ent_kill", deleted_at=_NOW, reason="erasure",
                  actor="user", derived=DerivedRefs())
    )
    a.seed_tombstone(
        Tombstone(id="tb_edge", op=TombstoneOp.DELETE, target_kind="edge",
                  target_id="edge_kill", deleted_at=_NOW, reason="erasure",
                  actor="user", derived=DerivedRefs())
    )
    bundle_del = str(tmp_path / "ne-del.mem")
    BundleExporter().export(a, bundle_del)

    d = InMemoryStore()
    BundleImporter().import_bundle(d, bundle_del)     # tombstones first
    r = BundleImporter().import_bundle(d, bundle_all)  # stale bundle STILL ships the rows

    assert d.entity_ids() == ["ent_keep"]             # tombstoned entity not resurrected
    edges = d.edge_ids()
    assert "edge_kill" not in edges                    # edge tombstoned by id refused
    assert "edge_dep" not in edges                     # edge whose endpoint was deleted refused
    assert "edge_self" in edges                         # unrelated edge survives
    assert r.skipped_tombstoned >= 3                    # ent_kill + edge_kill + edge_dep


# ─────────────────────────────────────────────────────────────────────────────
# 4. ext numbers use canonical shortest form (no IEEE-754 precision leak).
# ─────────────────────────────────────────────────────────────────────────────
def test_ext_numbers_use_canonical_shortest_form(tmp_path: Path) -> None:
    a = InMemoryStore()
    # confidence is 0.7 natively (see ep); add a foreign float + int + bool.
    a.seed_episode(ep("ep_n", "s"),
                   ext='{"vendorScore":0.92,"vendorCount":3,"vendorFlag":true}')
    d = str(tmp_path / "num.mem")
    BundleExporter().export(a, d)
    line = _read_text(os.path.join(d, "items", "episode.jsonl"))
    assert '"confidence":0.7' in line     # native float stays shortest form
    assert '"vendorScore":0.92' in line   # foreign float stays shortest form
    assert '"vendorCount":3' in line      # foreign int stays an int
    assert '"vendorFlag":true' in line    # foreign bool stays a bool
    assert "9999999" not in line          # no IEEE-754 precision leak
    assert "0000000" not in line          # no IEEE-754 precision leak

    # Re-export must be byte-identical (determinism / idempotent round-trip).
    c = InMemoryStore()
    BundleImporter().import_bundle(c, d)
    d2 = str(tmp_path / "num2.mem")
    BundleExporter().export(c, d2)
    line2 = _read_text(os.path.join(d2, "items", "episode.jsonl"))
    assert line == line2                  # ext round-trip is byte-identical


# ─────────────────────────────────────────────────────────────────────────────
# 5. Foreign fields round-trip via ext.
# ─────────────────────────────────────────────────────────────────────────────
def test_foreign_fields_round_trip_via_ext(tmp_path: Path) -> None:
    a = InMemoryStore()
    a.seed_episode(ep("ep_e", "s"), ext='{"vendorScore":0.91,"vendorTag":"alpha"}')
    d = str(tmp_path / "ext.mem")
    BundleExporter().export(a, d)
    line = _read_text(os.path.join(d, "items", "episode.jsonl"))
    assert "vendorScore" in line

    c = InMemoryStore()
    BundleImporter().import_bundle(c, d)
    ext = c.ext_for("ep_e")
    assert ext is not None and "vendorTag" in ext   # foreign field persisted

    d2 = str(tmp_path / "ext2.mem")
    BundleExporter().export(c, d2)
    line2 = _read_text(os.path.join(d2, "items", "episode.jsonl"))
    assert "vendorScore" in line2                    # foreign field re-emitted


# ─────────────────────────────────────────────────────────────────────────────
# 6. Unknown kind round-trips verbatim (incl. surrounding whitespace).
# ─────────────────────────────────────────────────────────────────────────────
def test_unknown_kind_round_trips_verbatim(tmp_path: Path) -> None:
    a = InMemoryStore()
    a.seed_episode(ep("ep_k", "x"))
    # Include a whitespace-padded line to prove passthrough preserves content verbatim.
    foreign = ['{"id":"vt_1","blob":"opaque"}', '   {"id":"vt_2","pad":true}   ']
    a.seed_passthrough("vendorThing", foreign)
    d = str(tmp_path / "uk.mem")
    m = BundleExporter().export(a, d)
    assert m.counts["vendorThing"] == 2

    c = InMemoryStore()
    BundleImporter().import_bundle(c, d)
    lines = c.passthrough_for("vendorThing")
    assert lines == foreign   # unknown kind preserved verbatim, incl. surrounding whitespace


# ─────────────────────────────────────────────────────────────────────────────
# 7. Re-export clears stale files.
# ─────────────────────────────────────────────────────────────────────────────
def test_re_export_clears_stale_files(tmp_path: Path) -> None:
    a = InMemoryStore()
    a.seed_episode(ep("ep_s", "s"))
    d = str(tmp_path / "stale.mem")
    BundleExporter().export(a, d)
    # Plant a stale item file as if left by a prior, larger export.
    stale = os.path.join(d, "items", "episode_OLD.jsonl")
    with open(stale, "wb") as fh:
        fh.write(b"{}\n")
    # Re-export to the same directory — the stale file must be gone and the bundle must
    # validate clean (no "present but not listed").
    BundleExporter().export(a, d)
    assert not os.path.exists(stale)               # stale file cleared on re-export
    assert BundleValidator().validate(d).ok        # re-exported bundle is valid


# ─────────────────────────────────────────────────────────────────────────────
# 8. Manifest path-traversal rejected.
# ─────────────────────────────────────────────────────────────────────────────
def test_rejects_manifest_path_traversal(tmp_path: Path) -> None:
    a = InMemoryStore()
    a.seed_episode(ep("ep_p", "p"))
    d = str(tmp_path / "trav.mem")
    BundleExporter().export(a, d)

    # Tamper the manifest to declare a file path that escapes the bundle directory.
    manifest_path = os.path.join(d, "manifest.json")
    m = from_wire(MemManifest, _read_json(manifest_path))
    m.files.append(MemFileEntry(path="../../../../etc/passwd", sha256="0" * 64, bytes=0))
    _write_bytes(manifest_path, to_line(m).encode("utf-8"))

    assert not BundleValidator().validate(d).ok    # validator flags the escaping path
    c = InMemoryStore()
    with pytest.raises(MemImportError):
        BundleImporter().import_bundle(c, d)


# ─────────────────────────────────────────────────────────────────────────────
# 9. Validator detects tamper (and import rejects it).
# ─────────────────────────────────────────────────────────────────────────────
def test_validator_detects_tamper(tmp_path: Path) -> None:
    a = InMemoryStore()
    a.seed_episode(ep("ep_v", "z"))
    d = str(tmp_path / "val.mem")
    BundleExporter().export(a, d)
    assert BundleValidator().validate(d).ok        # freshly exported bundle is valid

    _write_bytes(os.path.join(d, "items", "episode.jsonl"), b'{"id":"ep_tampered"}')
    assert not BundleValidator().validate(d).ok    # tamper detected

    c = InMemoryStore()
    with pytest.raises(MemImportError):
        BundleImporter().import_bundle(c, d)


# ─────────────────────────────────────────────────────────────────────────────
# 10. mem0 adapter maps export losslessly.
# ─────────────────────────────────────────────────────────────────────────────
def test_mem0_adapter_maps_export_losslessly() -> None:
    j = """
    {"results":[
      {"id":"m1","memory":"User prefers dark mode","user_id":"ivan",
       "categories":["preferences"],"created_at":"2026-05-01T10:00:00.000Z","metadata":{"app":"editor"}},
      {"id":"m2","memory":"Assistant scheduled the demo","role":"assistant",
       "agent_id":"asst","run_id":"sess7","created_at":"2026-05-02T12:00:00Z"}
    ]}
    """
    eps = Mem0Adapter.parse_episodes(j.encode("utf-8"))
    assert len(eps) == 2
    assert eps[0].details == "User prefers dark mode"
    assert eps[0].source_type == "text"
    assert "ivan" in eps[0].actors
    assert eps[0].categories == ["preferences"]
    assert eps[0].metadata["mem0_id"] == "m1"
    assert eps[0].metadata["app"] == "editor"
    assert eps[1].speaker == "assistant"
    assert eps[1].source_type == "chat"
    assert eps[1].context_id == "sess7"


# ─────────────────────────────────────────────────────────────────────────────
# 11. Lenient date decode accepts fractional seconds.
# ─────────────────────────────────────────────────────────────────────────────
def test_lenient_date_decode_accepts_fractional_seconds() -> None:
    # A foreign bundle may emit fractional seconds; the reader must accept them
    # (canonical OUTPUT stays whole-second — spec §1.1).
    from portable_memory import PortableEpisode

    whole = to_line(ep("ep_d", "s"))
    with_fraction = whole.replace(":20Z", ":20.500Z")
    import json

    decoded = from_wire(PortableEpisode, json.loads(with_fraction))
    assert decoded.id == "ep_d"
    # Re-encoding normalizes back to whole-second canonical form.
    reencoded = to_line(decoded)
    assert ".500" not in reencoded                 # canonical output is whole-second


# ─────────────────────────────────────────────────────────────────────────────
# 12. Symlink escape is rejected (validator + importer).
# ─────────────────────────────────────────────────────────────────────────────
def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    a = InMemoryStore()
    a.seed_episode(ep("ep_l", "s"))
    d = str(tmp_path / "sym.mem")
    BundleExporter().export(a, d)

    # Place the SAME bytes outside the bundle, then replace the listed file with a symlink
    # pointing at them. Checksums would pass (same bytes) — only the symlink guard should
    # stop it.
    ep_path = os.path.join(d, "items", "episode.jsonl")
    payload = str(tmp_path / "payload.jsonl")
    with open(ep_path, "rb") as fh:
        data = fh.read()
    with open(payload, "wb") as fh:
        fh.write(data)
    os.remove(ep_path)
    os.symlink(payload, ep_path)

    assert not BundleValidator().validate(d).ok    # symlinked/escaping file rejected
    c = InMemoryStore()
    with pytest.raises(MemImportError):
        BundleImporter().import_bundle(c, d)


# ─────────────────────────────────────────────────────────────────────────────
# 13. File-size bound rejects an oversize file (validator + importer).
# ─────────────────────────────────────────────────────────────────────────────
def test_file_size_bound_rejects_oversize_file(tmp_path: Path) -> None:
    a = InMemoryStore()
    a.seed_episode(ep("ep_big", "s"))
    d = str(tmp_path / "big.mem")
    BundleExporter().export(a, d)

    saved = MemLimits.max_file_bytes
    MemLimits.max_file_bytes = 4                    # any real file exceeds this
    try:
        assert not BundleValidator().validate(d).ok  # oversize files flagged
        c = InMemoryStore()
        with pytest.raises(MemImportError):
            BundleImporter().import_bundle(c, d)
    finally:
        MemLimits.max_file_bytes = saved


# ─────────────────────────────────────────────────────────────────────────────
# 14. Manifest signing verifies and rejects untrusted (cryptography required).
# ─────────────────────────────────────────────────────────────────────────────
def test_manifest_signing_verifies_and_rejects_untrusted(tmp_path: Path) -> None:
    pytest.importorskip("cryptography")
    from portable_memory import PortableSigningKey

    a = InMemoryStore()
    a.seed_episode(ep("ep_sig", "s"))
    key = PortableSigningKey()
    other = PortableSigningKey()
    d = str(tmp_path / "sig.mem")
    BundleExporter().export(a, d, signing_key=key)

    # A signature file is written and the manifest advertises the capability.
    assert os.path.exists(os.path.join(d, "manifest.sig"))

    # Validate/import with the correct trusted key succeeds.
    assert BundleValidator().validate(d, trusted_keys=[key.verifying_key]).ok
    c = InMemoryStore()
    BundleImporter().import_bundle(c, d, trusted_keys=[key.verifying_key])
    assert c.episode_count() == 1

    # A different (untrusted) key is rejected by both validator and importer.
    assert not BundleValidator().validate(d, trusted_keys=[other.verifying_key]).ok
    e = InMemoryStore()
    with pytest.raises(MemImportError):
        BundleImporter().import_bundle(e, d, trusted_keys=[other.verifying_key])

    # No trusted keys → signature is not required (back-compat).
    assert BundleValidator().validate(d).ok


# ─────────────────────────────────────────────────────────────────────────────
# 15. Manifest signature rejects manifest tamper (cryptography required).
# ─────────────────────────────────────────────────────────────────────────────
def test_manifest_signature_rejects_manifest_tamper(tmp_path: Path) -> None:
    pytest.importorskip("cryptography")
    from portable_memory import PortableSigningKey

    a = InMemoryStore()
    a.seed_episode(ep("ep_t", "s"))
    key = PortableSigningKey()
    d = str(tmp_path / "sigt.mem")
    BundleExporter().export(a, d, signing_key=key)

    # Rewrite manifest.json bytes (trailing space keeps it valid JSON but breaks the
    # signature over the original bytes).
    manifest_path = os.path.join(d, "manifest.json")
    with open(manifest_path, "rb") as fh:
        raw = fh.read()
    _write_bytes(manifest_path, raw + b"\x20")

    res = BundleValidator().validate(d, trusted_keys=[key.verifying_key])
    assert not res.ok                              # tampered manifest fails signature check
    assert any("signature" in issue for issue in res.issues)


# ─────────────────────────────────────────────────────────────────────────────
# 16. Tombstone signature round-trip (cryptography required).
# ─────────────────────────────────────────────────────────────────────────────
def test_tombstone_signature_round_trip() -> None:
    pytest.importorskip("cryptography")
    from dataclasses import replace

    from portable_memory import PortableSigningKey
    from portable_memory.signing import sign_tombstone, tombstone_signature_valid

    key = PortableSigningKey()
    other = PortableSigningKey()
    t = Tombstone(
        id="tb_s", op=TombstoneOp.DELETE, target_kind="episode", target_id="ep_z",
        deleted_at=datetime.fromtimestamp(1_700_000_000, tz=timezone.utc),
        reason="erasure", actor="user", derived=DerivedRefs(),
    )
    signed = sign_tombstone(t, key)
    assert signed.signature is not None
    assert tombstone_signature_valid(signed, [key.verifying_key])
    assert not tombstone_signature_valid(signed, [other.verifying_key])   # untrusted rejected

    tampered = replace(signed, target_id="ep_other")
    assert not tombstone_signature_valid(tampered, [key.verifying_key])   # altered fails
    assert not tombstone_signature_valid(t, [key.verifying_key])          # unsigned is invalid


# ─────────────────────────────────────────────────────────────────────────────
# 17. Conformance fixture validates (also covered in test_interop_fixture with
#     the byte-interop assertions; kept here to mirror the Swift suite exactly).
# ─────────────────────────────────────────────────────────────────────────────
def test_conformance_fixture_validates() -> None:
    # Package root is two levels up from this test file (tests/ -> repo root).
    root = Path(__file__).resolve().parent.parent
    fixture = root / "Conformance" / "fixtures" / "sample.mem"
    res = BundleValidator().validate(str(fixture))
    assert res.ok, f"shipped conformance fixture must validate: {res.issues}"


# ─────────────────────────────────────────────────────────────────────────────
# Small file helpers (stdlib only; kept local to avoid a dependency on the SDK's
# private write helpers).
# ─────────────────────────────────────────────────────────────────────────────
def _read_json(path: str | os.PathLike) -> dict:
    import json

    with open(path, "rb") as fh:
        return json.loads(fh.read())


def _write_bytes(path: str | os.PathLike, data: bytes) -> None:
    with open(path, "wb") as fh:
        fh.write(data)
