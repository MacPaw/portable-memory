"""The format-1.1 cross-SDK fixture ``Conformance/fixtures/sample-1.1.mem``.

Written by the Python SDK (``Conformance/fixtures/generate_sample_1_1.py``); the Swift suite
validates the very same bytes — recomputing the Python-written ``bundleDigest`` — imports
them, and re-exports byte-identical streams. ``sample.mem`` stays at format 1.0 as the
backward-compatibility fixture."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

from portable_memory import BundleExporter, BundleImporter, BundleValidator, MemFormat, PortableContext, sha256_hex
from portable_memory.inmemory import InMemoryStore

FIXED = datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "Conformance" / "fixtures" / "sample-1.1.mem"
EXPECTED_SCOPES = ["ctx_comms", "ctx_instructions", "ctx_root"]


class ScopedStore(InMemoryStore):
    """The public in-memory store plus contexts, so the fixture round-trips completely."""

    def __init__(self) -> None:
        super().__init__(generator="test/1.0")
        self.contexts: dict[str, PortableContext] = {}

    def export_contexts(self) -> list[PortableContext]:
        return [self.contexts[k] for k in sorted(self.contexts)]

    def import_context(self, c: PortableContext) -> None:
        self.contexts[c.id] = c


def test_fixture_validates_and_declares_every_1_1_field():
    res = BundleValidator().validate(FIXTURE)
    assert res.ok, res.issues
    m = res.manifest
    assert m.format == "1.1.0" and m.spec_url == MemFormat.SPEC_URL
    assert m.scopes == EXPECTED_SCOPES                       # episode contextIDs ∪ context ids (ctx_root only via a context record)
    assert m.coverage.from_ == FIXED and m.coverage.to == datetime(2026, 3, 1, tzinfo=timezone.utc)
    assert m.bundle_digest == sha256_hex((FIXTURE / "CHECKSUMS").read_bytes())
    assert m.counts == {"context": 3, "episode": 11}


def test_fixture_file_hashes_match_manifest():
    manifest = json.loads((FIXTURE / "manifest.json").read_bytes())
    assert manifest["files"], "fixture manifest must list files"
    for entry in manifest["files"]:
        data = (FIXTURE / entry["path"]).read_bytes()
        assert sha256_hex(data) == entry["sha256"] and len(data) == entry["bytes"], entry["path"]


def test_fixture_imports_and_reexports_byte_identically(tmp_path):
    store = ScopedStore()
    BundleImporter().import_bundle(store, FIXTURE, reembed=False)
    assert len(store.episodes) == 11 and sorted(store.contexts) == EXPECTED_SCOPES
    assert {e.context_id for e in store.episodes.values() if e.context_id} == {"ctx_comms", "ctx_instructions"}
    m = BundleExporter().export(store, tmp_path / "re.mem")
    for name in ("items/episode.jsonl", "items/context.jsonl", "CHECKSUMS"):
        assert (tmp_path / "re.mem" / name).read_bytes() == (FIXTURE / name).read_bytes(), name
    original = json.loads((FIXTURE / "manifest.json").read_bytes())
    assert m.bundle_digest == original["bundleDigest"]          # same CHECKSUMS bytes → same archive digest
    assert m.scopes == original["scopes"]
    assert [m.coverage.from_.isoformat(), m.coverage.to.isoformat()] == [
        datetime.fromisoformat(original["coverage"][k].replace("Z", "+00:00")).isoformat() for k in ("from", "to")
    ]


def test_fixture_matches_its_generator(tmp_path):
    """Guards against fixture drift: rebuilding the generator's store reproduces the bytes."""
    spec = importlib.util.spec_from_file_location("gen11", ROOT / "Conformance" / "fixtures" / "generate_sample_1_1.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    m = BundleExporter().export(gen.build_store(), tmp_path / "g.mem")
    for name in ("items/episode.jsonl", "items/context.jsonl", "CHECKSUMS"):
        assert (tmp_path / "g.mem" / name).read_bytes() == (FIXTURE / name).read_bytes(), name
    assert m.bundle_digest == json.loads((FIXTURE / "manifest.json").read_bytes())["bundleDigest"]
