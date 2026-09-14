#!/usr/bin/env python3
"""Regenerate ``Conformance/fixtures/sample-1.1.mem`` — the format-1.1 cross-SDK fixture.

    python3 Conformance/fixtures/generate_sample_1_1.py

Content (deterministic): the eleven episodes of the transfer-text fixture parsed with
``now = 1700000000`` and ``source = "chatgpt"``, three of them scoped to contexts by their
section, plus three ``context`` records (one referenced only by a context record, so the
manifest's ``scopes`` proves it unions episode ``contextID``s with exported contexts). The
manifest therefore carries every 1.1 field: ``specURL``, ``coverage``, ``scopes`` and
``bundleDigest``. ``createdAt`` is the generation time and is not asserted by tests.

Both reference SDKs must validate the bundle (recomputing the Python-written
``bundleDigest``), import it, and re-export byte-identical streams + CHECKSUMS. Copy the
regenerated directory to the sibling repository so the fixtures stay byte-identical.
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from portable_memory import BundleExporter, PortableContext  # noqa: E402
from portable_memory.adapters.transfer import TransferTextAdapter  # noqa: E402
from portable_memory.inmemory import InMemoryStore  # noqa: E402

FIXED_NOW = datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)  # 2023-11-14T22:13:20Z
SECTION_TO_CONTEXT = {"Communication preferences": "ctx_comms", "INSTRUCTIONS": "ctx_instructions"}


class FixtureStore(InMemoryStore):
    def __init__(self) -> None:
        super().__init__(generator="portable-memory-fixture/1.1")
        self.contexts: list[PortableContext] = []

    def export_contexts(self) -> list[PortableContext]:
        return sorted(self.contexts, key=lambda c: c.id)


def build_store() -> FixtureStore:
    store = FixtureStore()
    text = (HERE / "transfer" / "sample-export.txt").read_text(encoding="utf-8")
    for e in TransferTextAdapter.parse_episodes(text, source="chatgpt", now=FIXED_NOW):
        e.context_id = SECTION_TO_CONTEXT.get(e.metadata.get("transfer_section", ""))
        store.import_episode(e, None)
    for cid, label, parent in (
        ("ctx_root", "Personal", None),
        ("ctx_comms", "Communication preferences", "ctx_root"),
        ("ctx_instructions", "Instructions", "ctx_root"),
    ):
        store.contexts.append(PortableContext(id=cid, label=label, archived=False, created_at=FIXED_NOW, parent_id=parent))
    return store


def main() -> None:
    out = HERE / "sample-1.1.mem"
    if out.exists():
        shutil.rmtree(out)
    m = BundleExporter().export(build_store(), out)
    print(f"wrote {out.name}: format {m.format}, counts {m.counts}, scopes {m.scopes}, "
          f"coverage {m.coverage.from_.isoformat()} → {m.coverage.to.isoformat()}, digest {m.bundle_digest[:16]}…")


if __name__ == "__main__":
    main()
