"""Seeded fuzz / robustness: the text-facing parsers must never raise, must be
deterministic, and must always yield episodes the codec can serialize.

Standard-library only (no hypothesis): a fixed-seed ``random.Random`` builds line soups
from tokens that resemble the inputs each parser accepts, plus raw unicode noise.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timezone

from portable_memory import to_line
from portable_memory._yaml import load_yaml
from portable_memory.adapters.engram import EngramAdapter
from portable_memory.adapters.transfer import TransferTextAdapter

FIXED = datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)
SEED = 20260913
ROUNDS = 250

TRANSFER_TOKENS = [
    "[2026-01-15]", "[Jan 2026]", "[date unknown]", "[]", "[2026-02-30]", "2026-03-03", "-", "–", "—", ":", "- ", "* ",
    "1. ", "(2) ", "## Section", "**Bold**:", "TOOLS", "```", "Tone: direct", "  indented", "\t", "Київ", "🙂", "\\", '"',
    "memory content", "prefers X", "#", "...", "---",
]
YAML_TOKENS = [
    "- id: A", "id: B", "statement: |", "statement: >-", "  text line", "tags: [a, b]", "tags:", "- x", "activation:",
    "  retrieval_strength: 0.9", "  frequency: 3", "{k: v}", "[1, 2,", "]", "}", "engrams:", "episodes:", "- summary: s",
    "  timestamp: 2026-02-01T10:00:00Z", "  agent: hermes", "'quoted", '"dq\\"', "# comment", "---", "...", "%YAML 1.2",
    "key: value: more", ": bad", "- - nested", "\ttab: 1", "null", "~", "true", "1e3", "0x1F", "Київ: 🙂", "",
]
NOISE = "abc:[]{}-#|>'\"\\ \n\t  й🙂"


def _soup(rng: random.Random, tokens: list[str]) -> str:
    n = rng.randint(0, 14)
    lines = []
    for _ in range(n):
        k = rng.randint(1, 4)
        parts = [rng.choice(tokens) for _ in range(k)]
        if rng.random() < 0.3:
            parts.append("".join(rng.choice(NOISE) for _ in range(rng.randint(1, 6))))
        lines.append(rng.choice(["", " ", "  ", "    "]) + " ".join(parts))
    return "\n".join(lines) + rng.choice(["", "\n", "\r\n"])


def _check_episodes(eps):
    ids = [e.id for e in eps]
    assert len(ids) == len(set(ids))
    for e in eps:
        line = to_line(e)                        # canonical JSON must serialize every field…
        assert json.loads(line)["id"] == e.id    # …and be valid JSON that round-trips
        assert e.details is not None and len(e.summary) <= 120
        assert all(isinstance(k, str) and isinstance(v, str) for k, v in e.metadata.items())


def test_transfer_parser_never_raises_and_is_deterministic():
    rng = random.Random(SEED)
    for _ in range(ROUNDS):
        text = _soup(rng, TRANSFER_TOKENS)
        a = TransferTextAdapter.parse_episodes(text, now=FIXED)
        b = TransferTextAdapter.parse_episodes(text, now=FIXED)
        assert [e.id for e in a] == [e.id for e in b]
        _check_episodes(a)
        TransferTextAdapter.parse_episodes(TransferTextAdapter.render_text(a), now=FIXED)


def test_yaml_reader_never_raises_and_is_deterministic():
    rng = random.Random(SEED + 1)
    for _ in range(ROUNDS):
        text = _soup(rng, YAML_TOKENS)
        assert load_yaml(text) == load_yaml(text)


def test_engram_parser_never_raises_and_round_trips():
    rng = random.Random(SEED + 2)
    for _ in range(ROUNDS):
        text = _soup(rng, YAML_TOKENS)
        a = EngramAdapter.parse_episodes(text, now=FIXED)
        b = EngramAdapter.parse_episodes(text, now=FIXED)
        assert [e.id for e in a] == [e.id for e in b]
        _check_episodes(a)
        rendered = EngramAdapter.render_yaml(a)
        again = EngramAdapter.parse_episodes(rendered, now=FIXED)
        assert [e.id for e in again] == [e.id for e in a if e.metadata.get("engram_record") != "episode"]
        EngramAdapter.parse_episodes(EngramAdapter.render_yaml(a, kind="episodes"), now=FIXED)


def test_binary_and_pathological_inputs():
    for text in ("\x00\x01\x02", "﻿- id: A\n  statement: bom", "a" * 20000, "[" * 500, "- " * 300, "|\n" * 50, "\n" * 1000):
        TransferTextAdapter.parse_episodes(text, now=FIXED)
        EngramAdapter.parse_episodes(text, now=FIXED)
        load_yaml(text)
