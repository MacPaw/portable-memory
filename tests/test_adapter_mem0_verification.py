"""mem0 adapter verification against mem0's DOCUMENTED shapes.

Fixture fields come from mem0's docs/source: the platform's paginated envelope
(count/next/previous/results), OSS `isoformat()` timestamps (microseconds + offset),
the OSS promoted per-memory keys (user_id/agent_id/run_id/actor_id/role/attributed_to/
expiration_date, date-only "YYYY-MM-DD"), and extra top-level fields (score, immutable,
memory_type) that must survive via the lossless sweep. Metadata string literals are
asserted exactly — the Swift suite asserts the same bytes."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from portable_memory.adapters.mem0 import Mem0Adapter

DOC_EXPORT = {
    # Platform GET /v1/memories/ envelope (paginated).
    "count": 2,
    "next": None,
    "previous": None,
    "results": [
        {
            "id": "f4cbdb08-7062-4f3e-8eb2-9f5c80dfe64c",
            "memory": "Alex is planning a trip to San Francisco",
            # OSS format: datetime.now(timezone.utc).isoformat() — microseconds + offset.
            "created_at": "2024-01-15T10:30:45.123456+00:00",
            "updated_at": "2024-07-01T12:00:00Z",
            "user_id": "alex",
            "attributed_to": "alex",
            "expiration_date": "2024-08-01",       # normalized date-only
            "immutable": True,                       # swept
            "score": 0.42,                           # swept (search results)
            "memory_type": "procedural_memory",      # swept
            "metadata": {"nested": {"score": 0.7}},
            "categories": ["travel"],
        },
        {
            "id": "0e5b8f0f-95a7-4c8a-9f6e-1b2c3d4e5f60",
            "memory": "Prefers window seats",
            "created_at": "2024-07-01T12:00:00Z",
            "expiration_date": None,                 # platform emits null — must be skipped
        },
    ],
}


def test_mem0_doc_shaped_export():
    eps = Mem0Adapter.parse_episodes(json.dumps(DOC_EXPORT))
    assert len(eps) == 2
    e = eps[0]

    # OSS microsecond+offset timestamp parses to the exact instant.
    assert e.event_time == datetime(2024, 1, 15, 10, 30, 45, 123456, tzinfo=timezone.utc)
    assert e.mention_time == datetime(2024, 7, 1, 12, 0, 0, tzinfo=timezone.utc)

    # Promoted keys: expiration_date maps to the episode field (midnight UTC)...
    assert e.expiration_date == datetime(2024, 8, 1, tzinfo=timezone.utc)
    # ...and the raw strings are preserved as provenance.
    assert e.metadata["mem0_expiration_date"] == "2024-08-01"
    assert e.metadata["mem0_attributed_to"] == "alex"

    # Lossless sweep of unrecognized top-level keys (exact literals == Swift's).
    assert e.metadata["mem0_immutable"] == "1"
    assert e.metadata["mem0_score"] == "0.42"
    assert e.metadata["mem0_memory_type"] == "procedural_memory"

    # Container metadata values serialize canonically (byte-identical to Swift).
    assert e.metadata["nested"] == '{"score":0.7}'

    # Envelope pagination keys are ignored, not treated as memories.
    assert e.categories == ["travel"]

    # Null expiration_date is skipped entirely.
    e2 = eps[1]
    assert e2.expiration_date is None
    assert "mem0_expiration_date" not in e2.metadata


def test_mem0_sweep_never_overwrites_user_metadata():
    export = [{
        "id": "m1", "memory": "hi",
        "created_at": "2024-07-01T12:00:00Z",
        "score": 0.9,
        # A user metadata key that collides with a swept name keeps the user value.
        "metadata": {"mem0_score": "user-owned"},
    }]
    e = Mem0Adapter.parse_episodes(json.dumps(export))[0]
    assert e.metadata["mem0_score"] == "user-owned"
