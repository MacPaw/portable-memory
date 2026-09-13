# Engram fixture

The cross-SDK parity fixture for the **Engram (PLUR) adapter** — `engrams.yaml` /
`episodes.yaml` as defined by the [Engram Specification v2.1](https://plur.ai/spec.html)
(PLUR, Apache-2.0) and as written by PLUR's own tooling.

| File | Purpose |
|---|---|
| `engrams.yaml` | Bare-list root (the spec's form). Entry 1 is the specification's own example verbatim: a literal block-scalar statement, flow lists and a flow mapping, nested activation/entities/temporal/episodic/usage/associations blocks, bare dates. Entry 2 adds a quoted id, a sequence at the same indent as its key, `valid_until`, and a `provenance` block with `null` and `[]`. Entry 3 adds `>-` / `>` folded scalars, RFC 3339 `created_at`/`updated_at` (one with a `+02:00` offset), a flow-style activation with a quoted date, `pinned`, `consolidated`, and `dormant` status. |
| `pack.yaml` | PLUR pack style: wrapped `engrams:` root, comment lines between items, `>-` statements, flow activation, `dual_coding`, `commitment`, `polarity: dont`, an apostrophe inside a folded scalar. |
| `episodes.yaml` | Two PLUR episodes (`EP-…`): a bare RFC 3339 `Z` timestamp and a quoted one with a fraction and offset; a literal block summary. |
| `expected-episode.jsonl` | The `items/episode.jsonl` both SDKs MUST produce from the three files (parsed in that order with `now = 2023-11-14T22:13:20Z`, epoch `1700000000`, exported through a store that returns episodes sorted by id). |
| `expected-render.yaml` | `render_yaml` of the five engrams (bare-list root) — pins the deterministic emitter. |
| `generate.py` | Regenerates both expected files with the Python SDK. |

What the fixture pins: the YAML-subset reader (block/flow/quoted/block-scalar/comments/
wrapped root), YAML 1.2 core typing (`2` int, `0.85` float, `1.0` → `1`, dates as strings,
`null`), the field mapping (`learned_at`/`created_at` → event time, `updated_at` → mention
time, activation → `lastAccessed`/`accessCount`/`importance`, `episodic.confidence` / 10,
tags → categories, scope → contextId, `valid_until` → expiration, status → lifecycle),
lossless `engram_*` metadata (strings raw, everything else canonical JSON), deterministic
ids for entries without one, and the spec-ordered emitter.

The Python test `tests/test_adapter_engram.py` and the Swift test `EngramAdapterTests`
both compare against the same bytes. This directory is byte-identical in both repositories.
