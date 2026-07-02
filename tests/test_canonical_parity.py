"""Cross-implementation canonical-form parity (spec §1.1) — regression tests for the
divergences found in the launch audit. Every rule here was probed against the Swift
reference encoder; the two SDKs must emit identical bytes for identical values."""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

import pytest

from portable_memory import BundleExporter, canonical_json, from_wire
from portable_memory.adapters.mem0 import Mem0Adapter
from portable_memory.records import PortableEpisode

from conftest import InMemoryStore, ep


# ---------------------------------------------------------------- numbers (§1.1)

def test_whole_valued_floats_emit_as_integers():
    # The HIGH audit finding: Swift emits 1 for Double(1.0); Python must too.
    assert canonical_json({"a": 1.0}) == '{"a":1}'
    assert canonical_json({"a": 3.0}) == '{"a":3}'
    assert canonical_json({"a": -0.0}) == '{"a":0}'
    assert canonical_json({"a": 8e15}) == '{"a":8000000000000000}'   # < 1e16: plain digits
    assert canonical_json({"a": 9007199254740992.0}) == '{"a":9007199254740992}'  # 2^53
    # At/above 1e16 both reference encoders switch to exponent form.
    assert canonical_json({"a": 1e16}) == '{"a":1e+16}'
    assert canonical_json({"a": 1.5e16}) == '{"a":1.5e+16}'
    # Non-integral floats keep shortest round-trip form.
    assert canonical_json({"a": 0.7}) == '{"a":0.7}'
    assert canonical_json({"a": 0.92}) == '{"a":0.92}'
    # Bools are int subclasses but must never be touched by the float rule.
    assert canonical_json({"a": True}) == '{"a":true}'


def test_whole_float_export_is_canonical():
    store = InMemoryStore()
    e = ep("ep_one", "s")
    e.confidence = 1.0
    e.importance = 3.0
    store.episodes[e.id] = e
    exporter = BundleExporter()
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        exporter.export(store, d)
        line = open(f"{d}/items/episode.jsonl").read()
    assert '"confidence":1,' in line or '"confidence":1}' in line
    assert '"importance":3,' in line or '"importance":3}' in line
    assert '"confidence":1.0' not in line and '"importance":3.0' not in line


def test_nan_and_infinity_are_rejected():
    for bad in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError):
            canonical_json({"a": bad})


# ------------------------------------------------------- strict scalar decoding

def _episode_wire(**overrides):
    base = json.loads(
        '{"accessCount":0,"actors":[],"categories":[],"confidence":0.7,'
        '"details":"d","eventTime":"2023-11-14T22:13:20Z","extractionState":"done",'
        '"id":"ep_t","importance":0.5,"ingestionTime":"2023-11-14T22:13:20Z",'
        '"lifecycleState":"HOT","mentionTime":"2023-11-14T22:13:20Z","metadata":{},'
        '"pinned":false,"sensitivity":"low","sourceType":"note","summary":"s","vaultRefs":[]}'
    )
    base.update(overrides)
    return base


def test_wrong_typed_scalars_are_rejected():
    # The audit finding: Python silently accepted metadata:{"k":1} and importance:"0.5";
    # Swift's Codable rejects both. Parity requires rejection.
    with pytest.raises(TypeError):
        from_wire(PortableEpisode, _episode_wire(metadata={"k": 1}))
    with pytest.raises(TypeError):
        from_wire(PortableEpisode, _episode_wire(importance="0.5"))
    with pytest.raises(TypeError):
        from_wire(PortableEpisode, _episode_wire(pinned="yes"))
    with pytest.raises(TypeError):
        from_wire(PortableEpisode, _episode_wire(summary=42))
    with pytest.raises(TypeError):
        from_wire(PortableEpisode, _episode_wire(actors="alice"))


def test_lenient_integral_cross_typing_matches_swift():
    # Canonical form writes 1.0 as "1", so float fields accept int tokens — and Swift
    # decodes integral floats into Int fields, so we mirror that too.
    e = from_wire(PortableEpisode, _episode_wire(importance=1, accessCount=2.0))
    assert e.importance == 1.0 and isinstance(e.importance, float)
    assert e.access_count == 2 and isinstance(e.access_count, int)
    with pytest.raises(TypeError):
        from_wire(PortableEpisode, _episode_wire(accessCount=2.5))


# ----------------------------------------------------------------- manifest time

def test_manifest_created_at_is_true_utc():
    # The audit finding: naive datetime.now() stamped local time with a "Z".
    store = InMemoryStore()
    store.episodes["ep_a"] = ep("ep_a", "s")
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        manifest = BundleExporter().export(store, d)
    delta = abs(manifest.created_at - datetime.now(timezone.utc))
    assert delta < timedelta(minutes=5), f"createdAt off by {delta} — local-time leak"


# ----------------------------------------------------------------------- mem0

def test_mem0_categories_string_is_not_iterated():
    # A bare string must not explode into characters (['w','o','r','k']).
    data = {"results": [{"id": "m1", "memory": "hi", "created_at": "2026-01-01T00:00:00Z",
                         "categories": "work"}]}
    eps = Mem0Adapter.parse_episodes(json.dumps(data))
    assert eps[0].categories == []
    data["results"][0]["categories"] = ["work", "personal"]
    eps = Mem0Adapter.parse_episodes(json.dumps(data))
    assert eps[0].categories == ["work", "personal"]
