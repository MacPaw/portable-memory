# Conformance kit

How to claim a Portable Memory conformance level, and how to check a bundle.

## Levels

| Level | Requirement | How to demonstrate |
|---|---|---|
| **L0** | Read / Export | `BundleValidator().validate(bundle=...)` returns `ok` on your exported bundle. |
| **L1** | Import / Merge | Export → import into a fresh store reproduces counts/content; a second import is a no-op (idempotent). |
| **L2** | **Deletion propagation** (badge) | Delete an item, then prove it is unreachable via **every** route your engine supports + a tombstone was written (the probe below). |
| **L3** | Governed | Full audit trail + Evidence Pack export + signed tombstones. |

## Validate a bundle (L0)

```python
from portable_memory import BundleValidator

result = BundleValidator().validate(bundle="path/to/bundle.mem")
assert result.ok, "\n".join(result.issues)
```

The validator checks: the manifest parses, every listed file matches its `sha256` and
byte count, no unlisted/injected files are present, and every known-kind stream
decodes. Unknown (vendor) kinds are intentionally opaque and pass through.

Language-neutral validation: the `Schemas/` JSON Schemas cover `manifest.json`, every
`items/<kind>.jsonl` record kind, and the `audit/` records (`tombstone`, `log`), so a
non-Python implementer can validate a bundle without the SDK. Unknown (vendor) kinds have
no schema by design — they are opaque passthrough.

## The deletion-propagation probe (L2 — the gate)

This is the guarantee the badge rests on. For each of a handful of distinctive
"needle" memories:

1. Add it; confirm it is retrievable.
2. Delete it.
3. Assert it is unreachable via **every** route your engine exposes — at minimum:
   dense vector search, lexical/full-text, any k-hop graph, any embedding/derived
   cache, the bi-temporal `as_of` historical view, and any synced replica.
4. Assert a portable tombstone was written for it (positive proof, not mere absence).

A conformant `delete` reaches every artifact derived from the content; a conformant
`import` applies tombstones **before** additions, so a bundle that still carries the
stale rows can never resurrect deleted content.

The reference SDK demonstrates the offline, bundle-level part of this probe in
`tests/` — the tombstone-first / no-resurrection cases: tombstones are applied before
additions, so a stale bundle re-import can never resurrect a deleted item of **any**
kind. The live, all-routes assertion (dense / lexical / graph / cache / replica) is
completed by an adopter against its own retrieval stack.

## Fixtures

`fixtures/sample.mem/` is a small, valid bundle exercising episodes, an entity, an
edge, an episode carrying a foreign `ext` field, a vendor-specific passthrough kind,
and a tombstone (with proof-of-reach). Use it to test your importer and validator.

`fixtures/transfer/` pins the **memory-transfer text** adapter: a realistic pasted
export (`sample-export.txt`, the `[date] - memory` code block assistants produce for the
standard export prompt) and the exact `items/episode.jsonl` bytes both reference SDKs
must derive from it. An implementation of the adapter in another language is parity-
complete when it reproduces that file. See [`fixtures/transfer/README.md`](fixtures/transfer/README.md).

`fixtures/engram/` does the same for the **Engram (PLUR) adapter**: the Engram
Specification's own example, a PLUR pack-style file, and an `episodes.yaml`, with the exact
`items/episode.jsonl` bytes *and* the exact `render_yaml` output both SDKs must produce. See
[`fixtures/engram/README.md`](fixtures/engram/README.md).

## Vectors

`vectors/` holds the language-neutral conformance oracle — `canonical-json.json`
(`input → canonical bytes → sha256`) and a `signed.mem` fixture with its test keypair.
Reproduce every vector and you are byte-interoperable with the reference SDKs. See
[`vectors/README.md`](vectors/README.md).
