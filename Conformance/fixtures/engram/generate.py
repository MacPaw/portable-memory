#!/usr/bin/env python3
"""Regenerate the engram fixture's expected files with the Python reference SDK.

    python3 Conformance/fixtures/engram/generate.py

* ``expected-episode.jsonl`` — ``items/episode.jsonl`` after parsing ``engrams.yaml``,
  ``pack.yaml`` and ``episodes.yaml`` (in that order) with ``now = 1700000000`` and
  exporting through a store that returns episodes sorted by id.
* ``expected-render.yaml`` — ``EngramAdapter.render_yaml`` of the engrams parsed from
  ``engrams.yaml`` + ``pack.yaml`` (bare-list root).

Both reference SDKs must reproduce both files byte-for-byte. Regenerate ONLY when the
parsing or emission rules change deliberately, and copy the results to the sibling
repository so the two fixtures stay byte-identical.
"""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from portable_memory import BundleExporter  # noqa: E402
from portable_memory.adapters.engram import EngramAdapter  # noqa: E402
from portable_memory.inmemory import InMemoryStore  # noqa: E402

FIXED_NOW = datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)  # 2023-11-14T22:13:20Z
INPUTS = ("engrams.yaml", "pack.yaml", "episodes.yaml")


def main() -> None:
    episodes = []
    for name in INPUTS:
        episodes.extend(EngramAdapter.parse_episodes((HERE / name).read_text(encoding="utf-8"), now=FIXED_NOW))
    store = InMemoryStore(generator="test/1.0")
    for e in episodes:
        store.import_episode(e, None)
    with tempfile.TemporaryDirectory() as tmp:
        BundleExporter().export(store, Path(tmp) / "t.mem")
        data = (Path(tmp) / "t.mem" / "items" / "episode.jsonl").read_bytes()
    (HERE / "expected-episode.jsonl").write_bytes(data)

    engrams = [e for e in episodes if e.metadata.get("engram_record") == "engram"]
    rendered = EngramAdapter.render_yaml(engrams)
    (HERE / "expected-render.yaml").write_text(rendered, encoding="utf-8")
    print(f"wrote expected-episode.jsonl ({len(episodes)} episodes, {len(data)} bytes) "
          f"and expected-render.yaml ({len(engrams)} engrams, {len(rendered)} chars)")


if __name__ == "__main__":
    main()
