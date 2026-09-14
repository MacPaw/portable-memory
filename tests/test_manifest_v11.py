"""Format 1.1 manifest fields — ``specURL``, ``coverage``, ``scopes``, ``bundleDigest``
(spec §3.1) — plus backward compatibility with the shipped 1.0 fixtures."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from portable_memory import (
    BundleExporter, BundleImporter, BundleValidator, ExportMode, MemFormat, MemManifest,
    PortableContext, from_wire, sha256_hex, to_line,
)
from portable_memory.adapters.transfer import TransferTextAdapter
from portable_memory.inmemory import InMemoryStore

FIXED = datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)   # 2023-11-14T22:13:20Z
ROOT = Path(__file__).resolve().parents[1]
SAMPLE = (ROOT / "Conformance" / "fixtures" / "transfer" / "sample-export.txt").read_text(encoding="utf-8")
#: sha256 of the CHECKSUMS file of the transfer-fixture bundle — identical in the Swift suite.
PARITY_DIGEST = "1f7f0cdce93ef223537e6106b4713af03ff725e5ec07ab984cc805f719d6e401"


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def _store():
    s = InMemoryStore(generator="test/1.0")
    for e in TransferTextAdapter.parse_episodes(SAMPLE, source="chatgpt", now=FIXED):
        s.import_episode(e, None)
    return s


class ScopedStore(InMemoryStore):
    def __init__(self):
        super().__init__(generator="test/1.0")
        self.contexts: list[PortableContext] = []

    def export_contexts(self):
        return list(self.contexts)


def test_manifest_carries_format_1_1_fields(tmp_path):
    out = tmp_path / "b.mem"
    m = BundleExporter().export(_store(), out)
    assert m.format == "1.1.0" == MemFormat.VERSION
    assert m.spec_url == MemFormat.SPEC_URL
    # coverage = earliest/latest eventTime: undated entries take `now`; the latest dated entry is [2026-03-01].
    assert m.coverage.from_ == FIXED and m.coverage.to == utc(2026, 3, 1)
    assert m.scopes is None                                   # transfer entries reference no scopes
    checksums = (out / "CHECKSUMS").read_bytes()
    assert m.bundle_digest == sha256_hex(checksums) == PARITY_DIGEST

    on_disk = json.loads((out / "manifest.json").read_bytes())
    assert on_disk["format"] == "1.1.0" and on_disk["specURL"] == MemFormat.SPEC_URL
    assert on_disk["coverage"] == {"from": "2023-11-14T22:13:20Z", "to": "2026-03-01T00:00:00Z"}
    assert "scopes" not in on_disk                            # absent optional fields are omitted, never null
    assert on_disk["bundleDigest"] == m.bundle_digest
    assert BundleValidator().validate(out).ok
    assert from_wire(MemManifest, on_disk).coverage.to == utc(2026, 3, 1)   # round-trips through the codec


def test_scopes_enumerate_context_ids_sorted_and_unique(tmp_path):
    s = ScopedStore()
    for i, ctx in enumerate(["ctx_team", "ctx_personal", "ctx_team", None, ""]):
        (e,) = TransferTextAdapter.parse_episodes(f"[2026-01-0{i + 1}] - m{i}", now=FIXED)
        e.context_id = ctx
        s.import_episode(e, None)
    s.contexts.append(PortableContext(id="ctx_org", label="Org", archived=False, created_at=FIXED, parent_id=None))
    m = BundleExporter().export(s, tmp_path / "s.mem")
    assert m.scopes == ["ctx_org", "ctx_personal", "ctx_team"]  # sorted, de-duplicated, empty/None skipped
    assert m.coverage.from_ == utc(2026, 1, 1) and m.coverage.to == utc(2026, 1, 5)
    assert json.loads((tmp_path / "s.mem" / "manifest.json").read_bytes())["scopes"] == m.scopes


def test_incremental_coverage_describes_only_the_bundle(tmp_path):
    s = InMemoryStore(generator="test/1.0")
    old, new = TransferTextAdapter.parse_episodes("[2024-01-01] - old\n[2026-06-01] - new\n", now=FIXED)
    old.ingestion_time, new.ingestion_time = utc(2024, 1, 2), utc(2026, 6, 2)
    s.import_episode(old, None)
    s.import_episode(new, None)
    m = BundleExporter().export(s, tmp_path / "i.mem", mode=ExportMode.INCREMENTAL, since=utc(2025, 1, 1))
    assert m.counts.get("episode") == 1
    assert m.coverage.from_ == utc(2026, 6, 1) and m.coverage.to == utc(2026, 6, 1)


def test_empty_bundle_omits_coverage_and_scopes_but_has_digest(tmp_path):
    out = tmp_path / "e.mem"
    m = BundleExporter().export(InMemoryStore(generator="test/1.0"), out)
    assert m.coverage is None and m.scopes is None
    assert m.bundle_digest == sha256_hex((out / "CHECKSUMS").read_bytes())
    assert BundleValidator().validate(out).ok


def test_validator_verifies_bundle_digest(tmp_path):
    out = tmp_path / "t.mem"
    BundleExporter().export(_store(), out)
    with open(out / "CHECKSUMS", "ab") as fh:                 # a line smuggled into CHECKSUMS
        fh.write(b"0" * 64 + b"  items/evil.jsonl\n")
    issues = BundleValidator().validate(out).issues
    assert any("bundleDigest mismatch" in i for i in issues), issues

    BundleExporter().export(_store(), out)
    m = from_wire(MemManifest, json.loads((out / "manifest.json").read_bytes()))
    m.bundle_digest = "f" * 64                                  # manifest claims a digest that isn't true
    (out / "manifest.json").write_bytes(to_line(m).encode("utf-8"))
    assert any("bundleDigest mismatch" in i for i in BundleValidator().validate(out).issues)

    BundleExporter().export(_store(), out)
    (out / "CHECKSUMS").unlink()
    assert any("CHECKSUMS is missing" in i for i in BundleValidator().validate(out).issues)


def test_1_0_bundles_remain_valid_and_importable():
    """The shipped 1.0.0 fixtures have none of the 1.1 fields — a 1.1 reader must accept them."""
    fixture = ROOT / "Conformance" / "fixtures" / "sample.mem"
    res = BundleValidator().validate(fixture)
    assert res.ok, res.issues
    assert res.manifest.format.startswith("1.0") and res.manifest.spec_url is None
    assert res.manifest.coverage is None and res.manifest.scopes is None and res.manifest.bundle_digest is None
    store = InMemoryStore()
    report = BundleImporter().import_bundle(store, fixture, reembed=False)
    assert len(store.episodes) == res.manifest.counts.get("episode", 0) - report.skipped_tombstoned or len(store.episodes) > 0


def test_manifest_matches_json_schema(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    out = tmp_path / "v.mem"
    BundleExporter().export(_store(), out)
    schema = json.loads((ROOT / "Schemas" / "manifest.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(json.loads((out / "manifest.json").read_bytes()))


def test_evidence_pack_manifest_carries_digest(tmp_path):
    out = tmp_path / "ev.mem"
    m = BundleExporter().export_evidence_pack(_store(), out)
    assert m.spec_url == MemFormat.SPEC_URL
    assert m.bundle_digest == sha256_hex((out / "CHECKSUMS").read_bytes())
    assert m.coverage is None and m.scopes is None                 # an evidence pack carries no episodes


def test_incremental_scopes_union_delta_episodes_with_all_contexts(tmp_path):
    s = ScopedStore()
    old, new = TransferTextAdapter.parse_episodes("[2024-01-01] - old\n[2026-06-01] - new\n", now=FIXED)
    old.ingestion_time, old.context_id = utc(2024, 1, 2), "ctx_old"
    new.ingestion_time, new.context_id = utc(2026, 6, 2), "ctx_new"
    s.import_episode(old, None)
    s.import_episode(new, None)
    s.contexts.append(PortableContext(id="ctx_always", label="Always", archived=False, created_at=FIXED, parent_id=None))
    m = BundleExporter().export(s, tmp_path / "i.mem", mode=ExportMode.INCREMENTAL, since=utc(2025, 1, 1))
    assert m.scopes == ["ctx_always", "ctx_new"]                     # delta episodes only; contexts are always emitted in full


def test_forward_compat_unknown_manifest_keys_are_ignored(tmp_path):
    """A future (1.2) bundle may carry manifest keys this reader has never heard of."""
    out = tmp_path / "fwd.mem"
    BundleExporter().export(_store(), out)
    manifest = json.loads((out / "manifest.json").read_bytes())
    manifest["futureField"] = {"x": 1}
    manifest["visibility"] = {"private": 3}
    (out / "manifest.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    res = BundleValidator().validate(out)
    assert res.ok, res.issues
    assert res.manifest.bundle_digest == manifest["bundleDigest"]
    store = InMemoryStore()
    BundleImporter().import_bundle(store, out, reembed=False)
    assert len(store.episodes) == 11


def test_coverage_and_scopes_properties_random(tmp_path):
    """coverage == (min, max) eventTime; scopes == sorted unique context ids; digest == sha256(CHECKSUMS)."""
    import random
    rng = random.Random(20260914)
    pool = ["ctx_a", "ctx_b", "ctx_c", "ctx_д"]                      # a non-ASCII id exercises code-point ordering
    for rnd in range(25):
        s = ScopedStore()
        k = rng.randint(1, 9)
        text = "".join(f"[{rng.randint(2000, 2030):04d}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}] - m{rnd}-{i}\n" for i in range(k))
        eps = TransferTextAdapter.parse_episodes(text, now=FIXED)
        expected_ids: set[str] = set()
        for e in eps:
            if rng.random() < 0.5:
                e.context_id = rng.choice(pool)
                expected_ids.add(e.context_id)
            s.import_episode(e, None)
        if rng.random() < 0.5:
            s.contexts.append(PortableContext(id="ctx_only", label="L", archived=False, created_at=FIXED, parent_id=None))
            expected_ids.add("ctx_only")
        out = tmp_path / f"p{rnd}.mem"
        m = BundleExporter().export(s, out)
        times = [e.event_time for e in eps]
        assert (m.coverage.from_, m.coverage.to) == (min(times), max(times))
        assert m.scopes == (sorted(expected_ids) or None)
        assert m.bundle_digest == sha256_hex((out / "CHECKSUMS").read_bytes())
        assert BundleValidator().validate(out).ok
