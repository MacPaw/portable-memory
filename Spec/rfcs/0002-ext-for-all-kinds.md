# RFC-0002: Foreign-field carriage (`ext`) for every record kind

| | |
|---|---|
| **Status** | Draft — open for comment until 2026-10-05 |
| **Discussion** | https://github.com/MacPaw/portable-memory/issues/13 |
| **Target** | format **1.2.0** (minor); **prerequisite for RFC-0001** |
| **Author** | MacPaw (Sergii Kryvoblotskyi) · created 2026-09-14 |
| **Affects** | spec §4 (import/merge), §10 (vendor interoperability), §11 (conformance); the store seam in both reference SDKs |

## 1. Problem

The format promises a *lossless superset*: whatever a receiver does not model rides along
and comes back out unchanged. Today that promise is kept in two places and broken in a
third:

1. **Unknown record kinds** — `items/<vendorKind>.jsonl` is stored raw and re-emitted
   byte-for-byte (§1.2, §10). Kept.
2. **Unknown fields on `episode` records** — captured into the `ext` sidecar on import and
   merged back onto the native JSON on export (§10). Kept.
3. **Unknown fields on every other kind** — `entity`, `edge`, `fact`, `context`, … — are
   **silently dropped** by both reference readers: the Python codec decodes only the
   declared fields (`from_wire`) and Swift's synthesized `Decodable` ignores extra keys.
   A vendor field on a fact, or a format-1.2 `visibility` on an entity read by a 1.1
   reader, disappears on re-export.

The spec is precise about this — §10 says "any key on an `episode` record" — but the
project's READMEs and launch text have said "foreign fields round-trip verbatim" without
the qualifier. This RFC closes the gap in the format; the wording is corrected alongside.

## 2. Goals and non-goals

**Goals**

- **G1** Unknown fields on **any** record kind survive import → export byte-for-byte, as
  they already do for episodes.
- **G2** No wire-format change: foreign keys stay where vendors put them — at the top level
  of the record line — so a bundle stays readable with `cat`.
- **G3** Minimal store-seam churn: adopters who implement the seam today should not have
  to add fourteen method pairs.
- **G4** Make RFC-0001 (and any future optional field) safe to deploy against 1.1 readers.

**Non-goals**

- Interpreting foreign fields. They are opaque bytes with a stable home.
- Carrying foreign fields *across* kinds or merging two vendors' foreign fields for the
  same record (last-writer-wins at the record level, as today).

## 3. Proposal

### 3.1 Wire format — unchanged

A record line MAY carry keys outside its kind's schema. Canonical ordering (§1.1) sorts
them with everything else. Every kind's JSON Schema sets `additionalProperties: true`
(today `episode` does; the others are checked and aligned in the implementation PR).

### 3.2 Reader behavior — `ext` for every kind (normative in 1.2)

On import a reader MUST, for **every** native kind, split each record line into the
native fields it decodes and a foreign remainder, and hand the remainder to the host
keyed by the record's identity. On export it MUST merge the remainder back onto the
native JSON before canonicalization — exactly the `ext` mechanism §10 specifies for
episodes, generalized. A foreign key never overrides a native key.

**Record identity for the sidecar:** the record `id` for kinds that have one; for id-less
kinds (`factLink`, `episodeLink`, `preference`) the lowercase-hex SHA-256 of the record's
canonical *native* line — stable across implementations because the canonical form is.

### 3.3 Store seam — two generic methods instead of fourteen pairs

```
export_ext(kind: str) -> dict[str, str]          # record key → foreign-field JSON object
import_ext(kind: str, key: str, ext: str) -> None
```

(Swift: `exportExt(kind:)` / `importExt(kind:key:ext:)`.) Defaults: empty / no-op, so a
store that ignores foreign fields for a kind keeps working and simply is not L1-lossless
for that kind. The existing `export_episode_ext` / `import_episode(e, ext)` remain as the
episode specialization (they are what adopters implement today); the generic methods
default to delegating to them for `kind == "episode"`.

### 3.4 Conformance

- **L1 (Import / Merge — lossless)** gains: *foreign fields on every kind round-trip
  verbatim*. The shared conformance fixture gains an entity, an edge, a fact and a context
  each carrying a foreign field; both SDKs must reproduce the bundle byte-for-byte.
- The validator's "known-kind stream decodes" check is unchanged — foreign keys never make
  a record undecodable.

## 4. Compatibility

- **Wire:** no change. Every 1.0/1.1 bundle is unaffected.
- **Readers:** 1.0/1.1 readers keep dropping foreign fields on non-episode kinds (the
  status quo); 1.2 readers preserve them. Because RFC-0001 places `visibility` on
  non-episode kinds, RFC-0001 SHOULD NOT be adopted before this RFC.
- **Format version:** bundled into **1.2.0** with RFC-0001 (a normative reader
  requirement is a spec change even though bytes don't move).
- **SDKs:** additive; the two generic seam methods have defaults; no adopter code breaks.

## 5. Alternatives considered

- **A. A nested `ext` object inside each record on the wire.** Explicit, but it changes
  the wire form of every existing vendor field, breaks the "open it and read it"
  property, and would make today's bundles non-canonical. Rejected.
- **B. Document the limitation and leave it.** Cheapest, but it makes "lossless superset"
  a claim about one of fifteen kinds — and blocks RFC-0001. Rejected.
- **C. Per-kind method pairs on the seam** (`export_entity_ext`, …). Fourteen more
  methods for adopters to learn; the generic pair covers it. Rejected.

## 6. Open questions

1. Should the sidecar key for id-less kinds be the canonical-line hash (proposed) or
   should those kinds simply gain an `id`? (Giving `factLink` / `episodeLink` /
   `preference` ids is a larger change; the hash needs no wire change.)
2. Size bound per record for foreign remainders (`MemLimits`) — one bound for the whole
   file today; is a per-record cap needed against pathological input?
3. Should the manifest advertise the capability (`capabilities: ["ext:all-kinds"]`) so a
   sender can tell whether a receiver is L1-lossless for every kind?

## 7. Timeline

Comment period until **2026-10-05** alongside RFC-0001; decision by lazy consensus
(GOVERNANCE); implementation in both SDKs with the extended fixture; format **1.2.0**.
