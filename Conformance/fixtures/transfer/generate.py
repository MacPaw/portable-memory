#!/usr/bin/env python3
"""Regenerate ``expected-episode.jsonl`` from ``sample-export.txt``.

Run from the repository root with the Python reference SDK on the path:

    python3 Conformance/fixtures/transfer/generate.py

Both reference SDKs must reproduce the expected bytes exactly (see the fixture README);
regenerate ONLY when the transfer-text parsing rules change deliberately, and copy the
result to the sibling repository so the two fixtures stay byte-identical.
"""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from portable_memory import BundleExporter  # noqa: E402
from portable_memory.adapters.transfer import TransferTextAdapter  # noqa: E402
from portable_memory.inmemory import InMemoryStore  # noqa: E402

FIXED_NOW = datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)  # 2023-11-14T22:13:20Z


def main() -> None:
    text = (HERE / "sample-export.txt").read_text(encoding="utf-8")
    episodes = TransferTextAdapter.parse_episodes(text, source="chatgpt", now=FIXED_NOW)
    store = InMemoryStore(generator="test/1.0")
    for e in episodes:
        store.import_episode(e, None)
    with tempfile.TemporaryDirectory() as tmp:
        BundleExporter().export(store, Path(tmp) / "t.mem")
        data = (Path(tmp) / "t.mem" / "items" / "episode.jsonl").read_bytes()
    (HERE / "expected-episode.jsonl").write_bytes(data)
    print(f"wrote expected-episode.jsonl: {len(episodes)} episodes, {len(data)} bytes")


if __name__ == "__main__":
    main()
