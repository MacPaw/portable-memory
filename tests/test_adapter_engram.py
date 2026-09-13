"""Engram (PLUR) adapter — mapping rules, losslessness, rendering, and the shared
cross-SDK fixture (``Conformance/fixtures/engram/``)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from portable_memory import BundleExporter, canonical_json, to_line
from portable_memory.adapters.engram import EngramAdapter
from portable_memory.inmemory import InMemoryStore

FIXED = datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)
FIXTURES = Path(__file__).resolve().parents[1] / "Conformance" / "fixtures" / "engram"
ENGRAMS = (FIXTURES / "engrams.yaml").read_text(encoding="utf-8")
PACK = (FIXTURES / "pack.yaml").read_text(encoding="utf-8")
EPISODES = (FIXTURES / "episodes.yaml").read_text(encoding="utf-8")


def parse(text, **kw):
    return EngramAdapter.parse_episodes(text, now=FIXED, **kw)


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


# ── The spec's own example ────────────────────────────────────────────────────────────

def test_spec_example_field_mapping():
    e = {x.id: x for x in parse(ENGRAMS)}["ENG-2026-0131-001"]
    assert e.details == (
        "Validate org-mode syntax before writing to .org files.\n"
        "Three incidents of malformed entries in January 2026 caused\n"
        "data loss. Always parse and validate before write.\n"
    )  # literal block scalar, clip chomping keeps one trailing newline
    assert e.summary == "Validate org-mode syntax before writing to .org files."
    assert e.event_time == utc(2026, 1, 31) and e.mention_time == utc(2026, 1, 31)   # temporal.learned_at
    assert e.ingestion_time == FIXED
    assert e.last_accessed == utc(2026, 1, 30)                                        # activation.last_accessed
    assert e.access_count == 5 and e.importance == 0.85                               # frequency, retrieval_strength
    assert e.confidence == 0.9                                                        # episodic.confidence 9 → 0.9
    assert e.categories == ["org-mode", "validation"]
    assert e.context_id == "agent:dip-preparer"
    assert e.lifecycle_state == "HOT" and e.source_type == "note" and e.pinned is False
    assert e.expiration_date is None and e.speaker is None


def test_spec_example_metadata_is_lossless_canonical():
    m = {x.id: x for x in parse(ENGRAMS)}["ENG-2026-0131-001"].metadata
    assert m["engram_record"] == "engram"
    assert m["engram_version"] == "2" and m["engram_status"] == "active" and m["engram_polarity"] == "do"
    assert m["engram_activation"] == canonical_json(
        {"retrieval_strength": 0.85, "storage_strength": 0.6, "frequency": 5, "last_accessed": "2026-01-30"}
    )
    assert m["engram_feedback_signals"] == '{"negative":0,"neutral":2,"positive":3}'
    assert m["engram_contraindications"] == '["Quick scratch notes that won\'t be parsed"]'
    assert m["engram_entities"] == '[{"name":"org-mode","type":"technology"}]'
    assert m["engram_source"] == "user/personal"
    assert "engram_id" not in m and "engram_statement" not in m


def test_second_and_third_entries():
    by_id = {x.id: x for x in parse(ENGRAMS)}
    cand = by_id["ENG-2026-0302-001"]
    assert cand.categories == ["portable-memory", "vocabulary"]          # sequence at the key's indent
    assert cand.expiration_date == utc(2027, 3, 2) and cand.event_time == utc(2026, 3, 2)
    assert cand.lifecycle_state == "HOT"                                 # candidate is live knowledge
    assert cand.metadata["engram_provenance"] == '{"chain":[],"license":"MIT","origin":"session","signature":null}'
    assert cand.metadata["engram_relations"] == '{"related":["ENG-2026-0131-001"]}'

    meta = by_id["META-2026-0401-001"]
    assert meta.details == "Memory that cannot be exported is not owned; prefer stores whose contents round-trip through an open format."
    assert meta.metadata["engram_rationale"] == "Vendor lock-in through memory is the strongest lock-in in software.\n"
    assert meta.event_time == utc(2026, 4, 1, 9, 30)                      # created_at (no learned_at)
    assert meta.mention_time == utc(2026, 4, 15, 16, 45, 30)              # updated_at, +02:00 → UTC
    assert meta.last_accessed == utc(2026, 4, 15)                         # quoted date in a flow mapping
    assert meta.lifecycle_state == "COLD" and meta.importance == 0.4
    assert meta.metadata["engram_activation"] == '{"frequency":0,"last_accessed":"2026-04-15","retrieval_strength":0.4,"storage_strength":1}'
    assert meta.metadata["engram_pinned"] == "false" and meta.metadata["engram_consolidated"] == "true"


# ── PLUR pack style and episodes ──────────────────────────────────────────────────────

def test_pack_wrapped_root_folded_scalars_and_unknown_keys():
    eps = parse(PACK)
    assert [e.id for e in eps] == ["ENG-PACK-PM-001", "ENG-PACK-PM-002"]
    a, b = eps
    assert a.details.startswith("Before switching assistants, export memory to a .mem bundle and validate it;")
    assert "\n" not in a.details                                          # >- folds and strips
    assert a.pinned is True and a.importance == 0.95 and a.last_accessed == utc(2026, 5, 4)
    assert a.metadata["engram_commitment"] == "locked"                    # unknown keys ride along
    assert json.loads(a.metadata["engram_dual_coding"])["analogy"].startswith("Like checking")
    assert b.details.endswith("Don't just remove the row.")               # apostrophe in a folded scalar
    assert b.metadata["engram_polarity"] == "dont" and b.access_count == 3
    assert a.event_time == FIXED                                          # no learned_at/created_at → now


def test_plur_episodes_map_to_event_episodes():
    eps = parse(EPISODES)
    assert [e.id for e in eps] == ["EP-2026-0201-001", "EP-2026-0201-002"]
    a, b = eps
    assert a.source_type == "event" and a.speaker == "claude-code" and a.context_id == "sess-7f3a"
    assert a.event_time == utc(2026, 2, 1, 10, 0, 0)
    assert a.metadata["engram_record"] == "episode" and a.metadata["engram_channel"] == "terminal"
    assert a.metadata["engram_timestamp"] == "2026-02-01T10:00:00Z"
    assert b.event_time == utc(2026, 2, 1, 16, 30, 0)                     # fraction dropped, +02:00 → UTC
    assert b.details == "Decided: tombstones are applied before additions on import.\nRationale: a stale bundle must never resurrect deleted content.\n"
    assert b.summary == "Decided: tombstones are applied before additions on import."


# ── Shapes, ids, robustness ───────────────────────────────────────────────────────────

def test_accepts_json_single_engram_wrapped_and_multidoc():
    single = {"id": "ENG-X", "status": "active", "type": "behavioral", "scope": "global", "statement": "s"}
    assert [e.id for e in parse(json.dumps(single))] == ["ENG-X"]
    assert [e.id for e in parse(json.dumps({"engrams": [single]}))] == ["ENG-X"]
    assert [e.id for e in parse(single)] == ["ENG-X"]
    assert [e.id for e in parse("---\n- id: A\n  statement: a\n---\n- id: B\n  statement: b\n")] == ["A", "B"]


def test_missing_id_is_deterministic_and_duplicates_collapse():
    eps = parse("- statement: same text\n- statement: same text\n- statement: other\n")
    assert len(eps) == 2
    assert eps[0].id.startswith("eng_") and len(eps[0].id) == 28
    assert eps[0].id == parse("- statement: same text\n")[0].id


def test_invalid_entries_are_skipped_and_values_clamped():
    eps = parse(
        "- id: A\n  statement: ok\n  activation: {retrieval_strength: 7, frequency: -2}\n  episodic: {confidence: 11}\n"
        "- statement: ''\n- 42\n- id: B\n  statement: [not, text]\n"
    )
    assert [e.id for e in eps] == ["A", "B"]
    assert eps[0].importance == 1.0 and eps[0].access_count == 0 and eps[0].confidence == 0.7
    assert eps[1].details == '["not","text"]'      # a non-string statement is kept as canonical JSON
    assert parse("") == [] and parse("just prose") == [] and parse("[]") == []


# ── Rendering: lossless both ways ─────────────────────────────────────────────────────

def _engram_dicts(text):
    """The engram objects as our own reader sees them — the reference for losslessness."""
    from portable_memory._yaml import load_yaml
    root = load_yaml(text)
    items = root["engrams"] if isinstance(root, dict) else root
    return {e["id"]: e for e in items}


def test_render_restores_engrams_exactly():
    from portable_memory._yaml import load_yaml
    for text in (ENGRAMS, PACK):
        eps = parse(text)
        rendered = EngramAdapter.render_yaml(eps)
        back = {e["id"]: e for e in load_yaml(rendered)}
        for eid, original in _engram_dicts(text).items():
            assert canonical_json(back[eid]) == canonical_json(original), eid
        # …and re-importing the rendered YAML reproduces the very same episodes (same `now`).
        assert [to_line(e) for e in parse(rendered)] == [to_line(e) for e in eps]


def test_render_synthesizes_valid_engrams_from_plain_episodes():
    from portable_memory._yaml import load_yaml
    from portable_memory.adapters.transfer import TransferTextAdapter
    plain = TransferTextAdapter.parse_episodes("## Preferences\n[2026-01-15] - Likes terse answers.\n", now=FIXED)
    doc = load_yaml(EngramAdapter.render_yaml(plain))
    (eng,) = doc
    assert {"id", "status", "type", "scope", "statement"} <= set(eng)
    assert eng["statement"] == "Likes terse answers." and eng["tags"] == ["Preferences"]
    assert eng["temporal"] == {"learned_at": "2026-01-15"} and eng["source"] == "portable-memory"
    assert eng["activation"]["frequency"] == 0


def test_render_episodes_kind_and_wrapped():
    eps = parse(EPISODES)
    from portable_memory._yaml import load_yaml
    doc = load_yaml(EngramAdapter.render_yaml(eps, kind="episodes"))
    assert doc[0] == {"id": "EP-2026-0201-001", "timestamp": "2026-02-01T10:00:00Z",
                      "summary": "Migrated the team's shared memory from mem0 to a .mem bundle; 412 episodes, checksums verified.",
                      "agent": "claude-code", "channel": "terminal", "session_id": "sess-7f3a"}
    wrapped = EngramAdapter.render_yaml(parse(PACK), wrapped=True)
    assert wrapped.startswith("engrams:\n  - id: \"ENG-PACK-PM-001\"\n")
    assert EngramAdapter.render_yaml([]) == "[]\n"
    # engrams.yaml rendering skips PLUR episodes; episodes.yaml rendering includes everything
    assert load_yaml(EngramAdapter.render_yaml(eps)) == []
    assert len(load_yaml(EngramAdapter.render_yaml(parse(ENGRAMS), kind="episodes"))) == 3


def test_render_is_deterministic_and_spec_ordered():
    a = EngramAdapter.render_yaml(parse(ENGRAMS))
    assert a == EngramAdapter.render_yaml(parse(ENGRAMS))
    # Spec key order, strings quoted, integers bare, multi-line statement as a literal block.
    assert a.startswith(
        '- id: "ENG-2026-0131-001"\n  version: 2\n  status: "active"\n  type: "behavioral"\n'
        '  scope: "agent:dip-preparer"\n  visibility: "private"\n  polarity: "do"\n  statement: |\n'
        "    Validate org-mode syntax before writing to .org files.\n"
    )
    assert "  feedback_signals:\n    negative: 0\n    neutral: 2\n    positive: 3\n" in a   # nested mappings sorted
    assert '  tags: ["org-mode", "validation"]\n' in a                                     # scalar lists inline
    assert "  activation:\n    frequency: 5\n    last_accessed: \"2026-01-30\"\n    retrieval_strength: 0.85\n    storage_strength: 0.6\n" in a


# ── Cross-SDK parity ──────────────────────────────────────────────────────────────────

def test_fixture_parity_with_swift(tmp_path):
    episodes = []
    for name in ("engrams.yaml", "pack.yaml", "episodes.yaml"):
        episodes.extend(parse((FIXTURES / name).read_text(encoding="utf-8")))
    store = InMemoryStore(generator="test/1.0")
    for e in episodes:
        store.import_episode(e, None)
    BundleExporter().export(store, tmp_path / "t.mem")
    got = (tmp_path / "t.mem" / "items" / "episode.jsonl").read_bytes()
    assert got == (FIXTURES / "expected-episode.jsonl").read_bytes()
    assert got.count(b"\n") == 7

    engrams = [e for e in episodes if e.metadata.get("engram_record") == "engram"]
    assert EngramAdapter.render_yaml(engrams) == (FIXTURES / "expected-render.yaml").read_text(encoding="utf-8")
