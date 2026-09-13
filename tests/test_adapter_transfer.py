"""Memory-transfer text adapter — parsing rules, determinism, rendering, and the shared
cross-SDK fixture (``Conformance/fixtures/transfer/``)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from portable_memory import BundleExporter
from portable_memory.adapters.transfer import TransferTextAdapter
from portable_memory.inmemory import InMemoryStore

FIXED = datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)
FIXTURES = Path(__file__).resolve().parents[1] / "Conformance" / "fixtures" / "transfer"
SAMPLE = (FIXTURES / "sample-export.txt").read_text(encoding="utf-8")


def parse(text: str = SAMPLE, **kw):
    return TransferTextAdapter.parse_episodes(text, now=FIXED, **kw)


def by_line(eps):
    return {int(e.metadata["transfer_line"]): e for e in eps}


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


# ── Shape ─────────────────────────────────────────────────────────────────────────────

def test_sample_shape_and_identity():
    eps = parse(source="chatgpt")
    # 8 entries before the first header + 3 under headers; the duplicate last line collapses.
    assert len(eps) == 11
    assert all(e.id.startswith("tx_") and len(e.id) == 27 for e in eps)
    assert all(e.source_type == "note" and e.speaker is None for e in eps)
    assert all(e.metadata["transfer_source"] == "chatgpt" for e in eps)
    assert all(e.ingestion_time == FIXED for e in eps)
    assert len({e.id for e in eps}) == len(eps)


def test_dates_separators_and_raw_preservation():
    b = by_line(parse())
    assert b[1].event_time == utc(2025, 11, 3)
    assert b[1].details == "Prefers concise answers: code first, explanation second."
    assert b[1].metadata["transfer_date_raw"] == "2025-11-03"
    assert b[2].details.startswith("Works as Director")          # en dash separator
    assert b[3].details.startswith('Leads "Portable Memory"')    # em dash separator
    assert b[4].event_time == utc(2026, 1, 1)                     # [Jan 2026]
    assert b[4].metadata["transfer_date_raw"] == "Jan 2026"
    assert b[5].event_time == FIXED                               # [date unknown] → undated → now
    assert b[5].metadata["transfer_date_raw"] == "date unknown"
    assert "Київ" in b[5].details                                 # raw UTF-8 survives
    assert b[8].event_time == utc(2026, 2, 2)                     # bare ISO date + separator
    assert b[8].metadata["transfer_date_raw"] == "2026-02-02"


def test_bullets_numbers_headers_and_continuations():
    b = by_line(parse())
    assert b[6].details == "Prefers metric units and 24-hour time."   # "- " stripped
    assert "transfer_date_raw" not in b[6].metadata
    assert b[7].details == "Has a dog named Bit."                      # "1. " stripped
    assert b[11].categories == ["Communication preferences"]
    assert b[11].metadata["transfer_section"] == "Communication preferences"
    assert b[11].details == "Tone: direct, no filler, no emoji.\nException: emoji are fine in casual chats."
    assert b[11].summary == "Tone: direct, no filler, no emoji."
    assert b[13].categories == ["Communication preferences"]
    assert b[16].categories == ["INSTRUCTIONS"]
    assert b[1].categories == []
    assert 10 not in b and 15 not in b                                 # headers are not entries


def test_prose_outside_fence_ignored_and_duplicates_collapse():
    eps = parse()
    assert not any("complete set" in e.details or "everything I have stored" in e.details for e in eps)
    assert 17 not in by_line(eps)          # exact repeat of line 1 → no second episode
    assert by_line(eps)[1].id == TransferTextAdapter.parse_episodes(
        "[2025-11-03] - Prefers concise answers: code first, explanation second.", now=FIXED
    )[0].id


def test_ids_are_deterministic_and_independent_of_now():
    a = TransferTextAdapter.parse_episodes(SAMPLE, now=FIXED)
    b = TransferTextAdapter.parse_episodes(SAMPLE, now=utc(2030, 1, 1))
    assert [e.id for e in a] == [e.id for e in b]
    assert [e.id for e in a] == [e.id for e in TransferTextAdapter.parse_episodes(SAMPLE.encode("utf-8"), now=FIXED)]


# ── Variants ──────────────────────────────────────────────────────────────────────────

def test_plain_text_without_fence_and_colon_separator():
    eps = parse("[2026-01-01] - a\n[2026-01-02]: b\n[2026-01-03]c\n")
    assert [e.details for e in eps] == ["a", "b", "c"]
    assert [e.event_time.day for e in eps] == [1, 2, 3]


def test_prose_paragraph_mode():
    text = "You are a senior engineer who prefers\nterse answers.\n\n\nYou live in Kyiv and work on memory systems.\n"
    eps = parse(text)
    assert [e.details for e in eps] == [
        "You are a senior engineer who prefers\nterse answers.",
        "You live in Kyiv and work on memory systems.",
    ]
    assert [e.metadata["transfer_line"] for e in eps] == ["1", "5"]
    assert all(e.event_time == FIXED for e in eps)


def test_header_variants():
    text = "## Projects\n[2026-01-01] - a\n**Tools**:\n- b\nPreferences:\n1. c\nGOALS\n2026-03-03 - d\n(2) e\n"
    eps = parse(text)
    assert [e.details for e in eps] == ["a", "b", "c", "d", "e"]
    assert [e.categories[0] for e in eps] == ["Projects", "Tools", "Preferences", "GOALS", "GOALS"]


def test_lines_that_look_like_headers_but_are_not():
    eps = parse("- Favorite editor: Vim\nTone: direct, no filler\n[2026-01-01] - Uses: Python, Swift\n")
    assert [e.details for e in eps] == ["Favorite editor: Vim", "Tone: direct, no filler", "Uses: Python, Swift"]
    assert all(e.categories == [] for e in eps)


def test_month_name_and_partial_dates():
    text = (
        "[March 3rd, 2026] - a\n[3 March 2026] - b\n[Sept 2025] - c\n[2024] - d\n[2025-06] - e\n"
        "[2026-01-15T10:20:30Z] - f\n[2026-02-30] - g\n[yesterday] - h\n[] - i\n"
    )
    eps = by_line(parse(text))
    assert eps[1].event_time == utc(2026, 3, 3)
    assert eps[2].event_time == utc(2026, 3, 3)
    assert eps[3].event_time == utc(2025, 9, 1)
    assert eps[4].event_time == utc(2024, 1, 1)
    assert eps[5].event_time == utc(2025, 6, 1)
    assert eps[6].event_time == utc(2026, 1, 15, 10, 20, 30)
    assert eps[7].event_time == FIXED and eps[7].metadata["transfer_date_raw"] == "2026-02-30"  # invalid → undated, raw kept
    assert eps[8].event_time == FIXED and eps[8].metadata["transfer_date_raw"] == "yesterday"
    assert eps[9].event_time == FIXED and "transfer_date_raw" not in eps[9].metadata          # "[]" → no raw
    # Ids: same content on the same day collapses across spellings ("March 3rd, 2026" == "3 March 2026" only if content equal).
    assert eps[1].id != eps[2].id  # different content


def test_empty_and_noise():
    assert parse("") == []
    assert parse("```\n```\n") == []
    assert parse("[2026-01-01]\n\n   \n") == []   # bracket with no content → nothing
    assert parse("Here you go:\n```\n- only\n```\n")[0].details == "only"


# ── Rendering ─────────────────────────────────────────────────────────────────────────

def test_render_round_trip():
    eps = parse(source="chatgpt")
    text = TransferTextAdapter.render_text(eps)
    lines = text.splitlines()
    assert lines[0] == "[2025-11-03] - Prefers concise answers: code first, explanation second."
    assert "  Exception: emoji are fine in casual chats." in lines       # continuation indented
    assert text.endswith("\n")
    again = TransferTextAdapter.parse_episodes(text, now=FIXED)
    assert [e.details for e in again] == [e.details for e in eps]
    # Dated entries keep their identity through a round trip; undated ones gain the render date.
    dated = {e.id for e in eps if e.event_time != FIXED}
    assert dated <= {e.id for e in again}


def test_render_grouped_by_section_and_empty():
    text = TransferTextAdapter.render_text(parse(), group_by_section=True)
    assert "## Communication preferences" in text and "## INSTRUCTIONS" in text
    assert text.index("[2025-11-03] - Prefers") < text.index("## Communication preferences")
    assert TransferTextAdapter.render_text([]) == ""


# ── Cross-SDK parity ──────────────────────────────────────────────────────────────────

def test_fixture_parity_with_swift(tmp_path):
    """Both SDKs must turn sample-export.txt into byte-identical items/episode.jsonl —
    the Swift suite asserts the very same expected file."""
    store = InMemoryStore(generator="test/1.0")
    for e in parse(source="chatgpt"):
        store.import_episode(e, None)
    BundleExporter().export(store, tmp_path / "t.mem")
    got = (tmp_path / "t.mem" / "items" / "episode.jsonl").read_bytes()
    assert got == (FIXTURES / "expected-episode.jsonl").read_bytes()
    assert got.count(b"\n") == 11
