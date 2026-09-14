# Portable Memory — Specification v1.0

> An open, vendor-neutral format for AI memory portability — proposed and stewarded in the open by MacPaw.
> Status: **v1.0**. Reference SDKs: Swift (github.com/MacPaw/portable-memory-swift) and Python (github.com/MacPaw/portable-memory).
> Paper: [Memory Belongs to the User: Portable Memory, an Open Standard Proposal for Cross-Vendor AI Memory](https://research.macpaw.com/publications/portable-memory) (MacPaw Research, 2026).

**Goal.** Define an open, vendor-neutral format and protocol for carrying AI memory
across apps, devices, and vendors — losslessly, locally, and **verifiably governed**.
It is offered as an open format any vendor can adopt and extend — not a finished
"standard" decreed by one company, but a proposal stewarded in the open (see
`GOVERNANCE.md`) that aims to earn adoption. Its conformance badge is **gated on
deletion-propagation correctness** — the single hardest guarantee a memory layer makes.

This document specifies the on-disk format (`.mem` bundle), the data model, the
export/import/merge protocol, the deletion-and-redaction propagation guarantee, the
governance artifacts, and the conformance levels. It is written to be implementable
by any vendor in any language; the Swift and Python `PortableMemory` packages are the
reference implementations, and `Schemas/` carries language-neutral JSON Schemas.

---

## 0. Design principles

- **Vendor-neutral** — Readable/writable with no proprietary dependency. Plain JSONL
  + a JSON manifest. No database engine, no binary container required.
- **Local-first** — A bundle is a self-contained set of files. No server is required
  to read, verify, or transfer it.
- **Lossless round-trip** — `export → import` preserves facts, time, links,
  provenance, lifecycle state, and unknown fields.
- **Governed** — Deletions and redactions propagate to every replica and derived
  artifact; they are recorded as portable tombstones with proof-of-reach, and are
  **verifiable** when signed (§1.3).
- **Engine-agnostic** — Source text is mandatory and authoritative; embeddings are
  optional and model-tagged. Receivers re-embed.
- **Auditable** — Every record carries provenance; every mutation is logged in a
  portable trail.

### Conformance terminology

The key words **MUST**, **MUST NOT**, **REQUIRED**, **SHALL**, **SHOULD**, **MAY**, and
**OPTIONAL** in this document are to be interpreted as described in RFC 2119 and RFC 8174
when, and only when, they appear in all capitals. Sections and notes marked *(normative)*
state requirements; everything else is explanatory rationale.

---

## 1. The container — a `.mem` bundle

A bundle is a directory (optionally packaged as a single archive). JSONL streams keep
it scalable and append-friendly; the manifest declares everything an importer needs
to negotiate capabilities and verify integrity.

```text
mybundle.mem/
  manifest.json            format version, source, capabilities, model tags, counts, integrity
  items/
    episode.jsonl          one JSON object per line; the file name is the kind discriminator
    entity.jsonl
    edge.jsonl             semantic relations (bi-temporal)
    fact.jsonl             derived subject–predicate–object triples
    factLink.jsonl
    episodeLink.jsonl
    resource.jsonl
    chunk.jsonl
    core.jsonl             always-injected profile blocks
    procedure.jsonl
    context.jsonl
    community.jsonl
    category.jsonl
    preference.jsonl
    secretRef.jsonl        vault references — encryption metadata only, NEVER plaintext
  embeddings/              OPTIONAL, model-tagged, id-parallel; receiver may ignore
    <table>.<model>.vec
  audit/
    log.jsonl              every mutation (provenance trail)
    tombstones.jsonl       deletions + redactions — applied FIRST on import
  CHECKSUMS                sha256 per file (sha256sum-compatible)
```

Only non-empty `items/<kind>.jsonl` files are written; a missing file means zero
records of that kind. Serialization follows the **Canonical JSON** rules below, so two
conformant implementations emit byte-identical bundles (diffable, and with matching
checksums).

### 1.1 Canonical JSON (normative)

Every native record and the `manifest.json` MUST be serialized as **Canonical JSON**.
This is what makes checksums reproducible across languages; an implementation that
diverges here will fail the L0 checksum gate against another's bundle.

- **Encoding.** UTF-8, no byte-order mark.
- **Framing.** One JSON object per line (JSONL); lines are joined with a single line
  feed `\n`, and every `items/*.jsonl` and `audit/*.jsonl` file ends with a trailing
  `\n`. There is no insignificant whitespace **within** a record (no spaces between
  tokens).
- **Object keys.** Sorted ascending by Unicode code point, **recursively** (nested
  objects too).
- **Strings.** RFC 8259 escaping, with two constraints: the forward slash `/` MUST NOT
  be escaped, and non-ASCII characters MUST be emitted as raw UTF-8 (not `\u` escapes).
  Only `"`, `\`, and the mandatory control characters (U+0000–U+001F) are escaped.
- **Numbers.** The shortest decimal string that round-trips to the same IEEE-754
  double (the ECMAScript `Number`-to-string rule, as in RFC 8785 JCS). Integers within
  range are emitted with no decimal point or exponent. For example the value `0.7` MUST
  serialize as `0.7`, never `0.69999999999999996`.
- **Booleans / null.** `true`, `false`, `null`.
- **Absent optional fields** MUST be omitted, never emitted as `null`.
- **Timestamps.** RFC 3339 in UTC with a literal `Z` and **whole-second** precision
  (no fractional seconds, no numeric offset), e.g. `2026-06-30T00:00:00Z`.

> **Conformance vectors (normative).** `Conformance/vectors/canonical-json.json` pins
> these rules as `input → canonical bytes → sha256` cases; a conformant implementation
> MUST reproduce every vector. Values outside the tested domain are **not** guaranteed
> byte-identical across implementations in v1 and SHOULD be avoided where cross-implementation
> byte-identity matters: integral magnitudes ≥ 1e16, integers beyond `UInt64.max` (2^64−1),
> and non-ASCII / non-BMP object keys. Integer fields beyond 2^53 require a bigint-aware
> JSON parser.

### 1.2 Integrity files (normative)

- Each `files[].sha256` (manifest, §3) and each `CHECKSUMS` entry is the **lowercase
  hex** SHA-256 of the exact file bytes as written, **including** the trailing `\n`.
- `CHECKSUMS` uses the `sha256sum` text format: `<hex><two spaces><bundle-relative
  path>`, one line per file, sorted by path, `\n`-terminated. It covers every file in
  `manifest.files` and no others.
- `manifest.json`, `CHECKSUMS`, and `manifest.sig` are **not** self-listed. Checksums
  provide corruption/transport **integrity** — NOT **authenticity**: a party who can
  rewrite a file can recompute its public SHA-256 and the matching manifest entry. For
  authenticity, sign the bundle (§1.3).

Foreign, unrecognized-kind files (`items/<vendorKind>.jsonl`, §10) are stored and
re-emitted with each record's bytes preserved (they are exempt from re-canonicalization
so their checksum is stable); JSONL framing is normalized to a single trailing `\n`.

### 1.3 Signatures (normative, optional — L3)

Authenticity is provided by Ed25519 signatures over Canonical JSON bytes. Signing is
OPTIONAL; when present it upgrades a bundle from integrity-only to authenticated.

- **Bundle.** A producer MAY write `manifest.sig` (at the bundle root, not self-listed)
  holding a detached signature over the exact `manifest.json` bytes. Because the manifest
  lists every file's `sha256`, that one signature authenticates the whole bundle.
- **Tombstone.** A tombstone MAY carry a `signature` over its own Canonical JSON with the
  `signature` field itself absent.
- **Token format.** `ed25519:<publicKeyHex>:<signatureHex>` — lowercase hex over the raw
  32-byte public key and 64-byte signature. The public key travels with the token so a
  verifier can select which trusted key to check against; verification MUST succeed only
  when that key is in the verifier's trusted set, so a self-signed swap by an untrusted
  key is rejected.
- Keys are distributed out of band; key management is out of scope for this spec.
- A verifier configured with a trusted key MUST reject a bundle whose `manifest.sig` is
  missing, malformed, or not signed by a trusted key. With no trusted key configured,
  signatures are ignored and only integrity is checked.
- Signatures are **not** required to be byte-identical across implementations — some
  Ed25519 libraries randomize the signing nonce, others are deterministic, and both
  produce valid signatures. Verification against a trusted key is the interoperability
  guarantee, so `manifest.sig` is **excluded** from the byte-reproducibility of §1.1 (the
  data files, `manifest.json`, and `CHECKSUMS` are covered). A signed fixture and its test
  keypair live in `Conformance/vectors/`.

**Lossless superset (cross-vendor).** To carry any vendor's memory without loss, the
container preserves what this engine doesn't natively model: **foreign fields** on the
episode record survive via an `ext` carrier (any key not in the native schema is kept
and re-emitted), and **entire foreign kinds** (`items/<vendorKind>.jsonl`) round-trip
**verbatim**. A bundle is therefore a superset container, not a lowest-common-denominator
one — see §10.

---

## 2. The data model — items by kind

Every memory is a record in `items/<kind>.jsonl`. The seven-component model (Working /
Core / Episodic / Semantic / Procedural / Resource / Vault) maps onto these kinds.
Vendors **may** add kinds; unknown kinds round-trip verbatim.

| `kind` | Payload | Notes |
|---|---|---|
| `episode` | A timestamped event — the atomic memory | Bi-temporal (`eventTime`, `mentionTime`, `ingestionTime`); carries `lifecycleState`, `sensitivity`, `pinned`, `deletedAt`. |
| `entity` | A semantic graph node | person / org / project / place / product / document / topic. |
| `edge` | A bi-temporal relation | `tValidFrom` / `tValidTo` / `supersededBy` / `evidenceEpisodeIDs`. |
| `fact` | A derived subject–predicate–object triple | Non-destructive reconciliation layer; bi-temporal + prune marker. |
| `factLink` | `evidence_of` / `refines` link between facts | |
| `episodeLink` | A-Mem cross-link between episodes | |
| `resource` | A file/doc reference | Parent of `chunk`s; `contentHash` + `uri`. |
| `chunk` | A resource fragment | Re-embeddable from `text`. |
| `core` | An always-injected profile block | human / persona. |
| `procedure` | A user-defined routine | Trigger + steps. |
| `context` / `community` / `category` / `preference` | Scoping, clustering, taxonomy, durable settings | |
| `secretRef` | A reference to a vault secret | **Never** carries plaintext or ciphertext (§7). |

### Identity, time & provenance

- **Stable IDs** — globally unique, kind-prefixed (`ep_`, `ent_`, `edge_`,
  `fact_`, …). The same id across systems denotes the same memory; this is what makes
  merge and deletion idempotent.
- **Bi-temporal facts** — edges and facts carry `tValidFrom` / `tValidTo` /
  `supersededBy`. Updates **supersede, never overwrite**: keep both rows, set
  `tValidTo` on the old one. A point-in-time view reconstructs any past state — no
  information loss.
- **Provenance** — edges carry `evidenceEpisodeIDs`; facts carry `episodeID`. Every
  derived assertion ties back to the episodes that justify it. Required for the
  Evidence Pack (§7). *Typed* provenance — how a claim came to be (asserted / observed /
  inferred / merged / imported), who asserted it, and merge lineage — is proposed for
  format 1.2 in [RFC-0003](rfcs/0003-provenance-typing.md).

### Embeddings & engine-agnostic representation

Vectors are model-specific and therefore **not** the portable truth — the source text
is. Embeddings are an optional accelerator.

- `content` / `text` is always carried; embeddings, when present, live in
  `embeddings/<table>.<model>.vec` with the model tag and dimension declared in the
  manifest.
- An importer **may** reuse vectors only when its model tag matches exactly;
  otherwise it **re-embeds from source text**. Never assume cross-model vector
  compatibility.
- The reference implementation (v1.0) does not inline vectors
  (`embeddingsIncluded: false`); the receiver re-embeds on import, restoring vector
  search without any cross-model risk.

### Scopes & visibility *(status: RFC — not yet normative)*

The format says *where* a memory belongs (`contextID` → `context` records, which nest via
`parentID`) and *how sensitive* it is (`sensitivity`), but not yet *who may see it* — a
channel, one person, or a group. Vendor visibility settings survive a round-trip only as
opaque `ext` / metadata: lossless, but not meaningful to a receiver. A shared `visibility`
model — four levels (`private` / `group` / `shared` / `public`) plus opaque principals,
context-level defaults with per-record overrides, most-restrictive-wins on merge — is
proposed for format **1.2** in [RFC-0001](rfcs/0001-scopes-and-visibility.md) (discussion:
[issue #11](https://github.com/MacPaw/portable-memory/issues/11)). Until it is adopted,
a receiver SHOULD treat imported memories as private to the importing user unless the
source says otherwise.

---

## 3. The manifest

```jsonc
{
  "format": "1.0.0",
  "generator": "your-app/1.0",
  "conformanceLevel": "L2",
  "createdAt": "2026-06-30T00:00:00Z",
  "exportMode": "full",            // or "incremental" with "since"
  "schemaVersion": 12,
  "embeddingModel": "bge-m3",
  "embeddingDim": 1024,
  "embeddingsIncluded": false,     // false ⇒ receiver re-embeds from source text
  "capabilities": ["bitemporal", "tombstones", "redaction", "evidence-pack"],
  "counts": { "episode": 128, "edge": 64, "tombstone": 3 },
  "files": [ { "path": "items/episode.jsonl", "sha256": "…", "bytes": 40213 } ]
}
```

`format` is semver. `capabilities` declares optional features. Importers negotiate by
capability and **preserve unknown kinds verbatim** + **foreign episode fields via
`ext`** on round-trip (§10), so a newer or other-vendor bundle never loses data here.

---

## 4. Operations — export & import / merge

- **Export** — full, or incremental (`--since <cursor>`) emitting only items +
  tombstones changed since the cursor. Deterministic ordering for diffable bundles.
- **Import** — idempotent and **merge-by-key** (§4.1). Re-importing the same bundle
  converges to an identical store (a no-op in effect).
- **Order of operations on import** (strict, normative):
  1. **Verify.** If a trusted key is configured, verify `manifest.sig` (§1.3). Then
     re-hash every file against `files[].sha256`, and reject any path that escapes the
     bundle (including via symlinks) or exceeds the size bound. Abort on any failure — a
     corrupt, oversized, escaping, or (when keys are configured) unauthenticated bundle
     MUST NOT half-apply.
  2. **Apply tombstones FIRST** (`audit/tombstones.jsonl`), so that even if the bundle
     also ships the (stale) rows, the subsequent merge cannot resurrect deleted content
     and redaction wins.
  3. **Merge items by key**, parents before children (§4.1).
  4. **Re-derive** local artifacts: FTS index, sentence segmentation, and embeddings
     (re-embed from text when no matching vectors are carried). Imported data is
     first-class, not second-tier.
  5. Converge the synced replica.

### 4.1 Identity & merge (normative)

- **Merge key.** Records with an `id` MUST merge by `id` — the same `id` denotes the same
  memory across systems. The id-less kinds merge by a natural composite key: `factLink`
  by (`srcFactID`, `dstFactID`, `linkType`); `episodeLink` by (`srcEpisodeID`,
  `dstEpisodeID`, `linkType`); `category` by `name`; `preference` by `key`.
- **Idempotency.** Importing a record whose key already exists with equal content is a
  no-op; re-importing an entire bundle MUST converge to an identical store.
- **Supersession, not overwrite.** For bi-temporal kinds (`edge`, `fact`) an update MUST
  supersede rather than overwrite: keep both rows, set `tValidTo` on the prior row and
  point its `supersededBy` at the successor. A point-in-time (`as_of`) view then
  reconstructs any past state — no information is lost. A single-valued ("cardinality-1")
  relation is updated the same way; it MUST NOT be silently overwritten.
- **No resurrection.** A record whose key — or a parent it cannot exist without (e.g. a
  `chunk`'s `resourceID`, an `edge`'s endpoint entity) — is tombstoned MUST NOT be merged,
  even if the bundle still ships the row. This MUST hold for **every** kind, not only
  episodes.

---

## 5. Deletion & redaction propagation — the trust core

This is the guarantee the whole standard rests on, and the conformance gate. A
deletion is not a row removal; it is a **tombstone** that propagates everywhere the
data — or anything derived from it — ever went.

```jsonc
// audit/tombstones.jsonl — first-class, portable, monotonic (cannot be un-seen)
{
  "id": "tomb_01J…",
  "op": "delete",                  // "delete" | "redact"
  "targetKind": "episode",
  "targetID": "ep_01J9X…",
  "deletedAt": "2026-06-30T00:00:00Z",
  "reason": "erasure request (GDPR Art. 17)",
  "actor": "actor_7c3f",           // opaque id — keep PII out of the portable trail
  "derived": {                     // proof-of-reach: what was actually removed
    "sentenceIDs": ["…"],
    "factIDs": ["…"],
    "edgeIDs": ["…"],              // edges deleted because their last evidence was removed
    "entityIDs": ["…"],           // entities orphaned by those edge deletions
    "chunkIDs": ["…"],
    "embeddingCacheKeys": ["…"],  // content-hash cache entries evicted
    "episodeLinkCount": 2
  },
  "signature": "ed25519:<pubHex>:<sigHex>"  // optional (§1.3, L3)
}
```

- **Delete** removes the item **and every derived artifact**: the FTS rows, the dense
  embedding, the **content-hash-keyed embedding cache**, the sentence index, graph
  edges evidenced only by it, the entities those orphan, A-Mem links, access history,
  and the synced replica copy.
- **Redact** additionally purges the content text while keeping the tombstone, so the
  deletion itself remains provable without retaining the content.
- **Propagation** — importers apply tombstones **before** additions. Every replica and
  external adopter must honor them. A synced replica is just another target that must
  converge.

**Receiver obligations (normative).** On `op: "delete"` a receiver MUST remove the target
and every artifact derived from it (above) and MUST NOT resurrect it on a later merge, for
**every** kind. On `op: "redact"` a receiver MUST additionally purge the target's content
text while retaining the tombstone (and a minimal metadata skeleton), so the deletion
stays provable without keeping the content. A receiver MUST apply a tombstone even when the
target row arrives later in the same bundle.

> Note: `reason` and `actor` travel in the portable, monotonic trail ("cannot be
> un-seen"). Use opaque actor ids and keep personal data out of `reason`, so the erasure
> record does not itself accumulate the data the erasure was meant to remove.

> **Conformance probe (the L2 gate).**
> Issue a delete, then assert the content is unreachable via **every** route the host
> supports: dense vector search, lexical/full-text, the k-hop graph, any embedding
> cache, the bi-temporal `as_of` historical view, and the synced replica — and that a
> portable tombstone was written. A bundle that ships a conformance badge with this
> probe failing turns a trust asset into a liability the moment a user tests it.

---

## 6. Governance & the Evidence Pack

Every mutation appends to `audit/log.jsonl` as `(ts, actor, op, targetID, reason)`
(schema: `Schemas/log.schema.json`).
The **Memory Evidence Pack** is an exportable, procurement-grade subset — provenance
(`provenance/edges.jsonl`) + audit (`audit/log.jsonl`) + **proof-of-deletion**
(`audit/tombstones.jsonl`, each tombstone carrying the ids of every derived artifact
removed as of a timestamp) — formatted for IT/compliance and SIEM ingestion. This is
what converts "governed memory" from a claim into a buyable artifact under the EU AI
Act. Produced by `BundleExporter.exportEvidencePack(_:to:)` in this SDK.

---

## 7. Security & vault handling

- **Integrity vs authenticity.** Checksums (§1.2) detect corruption; they do NOT prove
  origin. For authenticity, sign the bundle (`manifest.sig`) and/or tombstones (§1.3) and
  verify against a trusted key on import.
- **Secrets** are **never** exported as plaintext or ciphertext — only a `secretRef` with
  encryption metadata. Its `preview` MUST be a masked hint only (e.g. last-4) and MUST NOT
  contain recoverable secret material. The encrypted value stays in the originating vault
  unless an explicit, authorized, encrypted transfer is negotiated; import restores the
  metadata skeleton only and warns.
- **At rest.** Bundles may be encrypted at rest (envelope); `vault_must_stay_local` is
  honored across export and sync.
- **Untrusted input.** A reader MUST treat a `.mem` as untrusted: reject paths that escape
  the bundle (including via symlinks), reject files not listed in the manifest, and bound
  per-file size (the reference reader caps it — see `MemLimits`). Bundles are plaintext by
  design; do not expose an importer to untrusted input without these guards.
- **Local-first** by default; replica/sync is opt-in, regional where required, and **must
  propagate tombstones**.

---

## 8. Conformance levels & the badge

| Level | Requirement | What it proves |
|---|---|---|
| **L0** | Read / Export | Produces a valid, checksum-clean bundle. |
| **L1** | Import / Merge | Ingests losslessly, idempotently, with bi-temporal merge. |
| **L2** | Deletion propagation | Honors tombstones across all derived artifacts; passes the §5 probe. **Badge requires L2.** |
| **L3** | Governed | Full audit trail, Evidence Pack export, signed tombstones. |

The Swift reference SDK passes L0–L2 offline (`swift test` proves the lossless
idempotent round-trip, tombstone-first ordering across **every** kind,
foreign-field/kind passthrough, and integrity/checksum rejection). An adopter with live
retrieval routes (dense, lexical, k-hop graph, embedding cache, synced replica) runs the
full L2 deletion-propagation probe across those routes and produces the L3 Evidence Pack.
The SDK implements Ed25519 bundle and tombstone signing (§1.3), so L3's *signed
tombstones* is a real, testable feature — not an aspiration.

---

## 9. Versioning & capability negotiation

- `format` is semver in the manifest. `capabilities[]` declares features (e.g.
  `bitemporal`, `tombstones`, `redaction`, `evidence-pack`, `embeddings:<model>`).
- Importers negotiate by capability and **preserve unknown kinds verbatim** and
  **foreign fields on the episode record (via `ext`)** on round-trip, so a newer or
  other-vendor bundle never loses data in this reader (§10).

---

## 10. Vendor interoperability

The format is a **superset container**: it absorbs another provider's memory and
carries whatever it doesn't natively model, so a memory can move *into* the standard
and back out without loss. Two mechanisms make this concrete:

- **`ext` (foreign fields).** On import, any key on an `episode` record that is not in
  the native schema is captured and re-emitted on export. Nothing a vendor attached to
  a memory is dropped. *Scope note:* `ext` is specified for `episode` records only; the
  reference readers decode the known fields of other kinds and drop the rest. Extending
  `ext` to every kind is proposed in [RFC-0002](rfcs/0002-ext-for-all-kinds.md) (target
  format 1.2).
- **Passthrough (foreign kinds).** An `items/<vendorKind>.jsonl` whose kind this engine
  doesn't recognize is stored raw and re-emitted byte-for-byte.

**Adapters** map a foreign export onto the model on ingest; unmapped fields are kept in
`metadata` (namespaced) so a later `.mem` export stays lossless:

```swift
let episodes = try Mem0Adapter.parseEpisodes(data)   // ships in this reference SDK
```

### Mapping reference

| `.mem` | mem0 | OpenAI / ChatGPT memory | Anthropic / Claude memory | Letta (MemGPT) |
|---|---|---|---|---|
| `episode` | a memory (`memory`, `created_at`, `user_id`/`agent_id`/`run_id`, `categories`) | a saved memory string / conversation turn | a memory-tool file entry | archival/recall message |
| `core` | — | "what ChatGPT knows about you" profile | persona/project memory notes | core memory block (human/persona) |
| `entity` / `edge` / `fact` | mem0 graph relations | — (derive on import) | — (derive on import) | — |
| `procedure` | — | custom instructions | — | — |
| `secretRef` | — | — | — | — |
| provenance | `user_id`/`agent_id`/`run_id`/`role` → actors + `metadata` | author/source | source file | sender/role |

Kinds a source lacks are simply absent; kinds a source has that the standard lacks ride
in via `ext`/passthrough. New adapters (ChatGPT export, Claude memory files, Letta) plug
in the same way — map what's modeled, preserve the rest. This is what lets the standard
grow *outward* across vendors instead of forcing a lossy common subset.

---

## 11. Worked example — a minimal bundle

```jsonc
// manifest.json (excerpt)
{ "format": "1.0.0", "generator": "your-app/1.0", "conformanceLevel": "L2",
  "counts": { "episode": 1, "edge": 1, "tombstone": 1 } }
```

```jsonc
// items/edge.jsonl — a bi-temporal edge superseded, not overwritten
{ "id": "edge_a1", "srcEntityID": "ent_q3", "dstEntityID": "ent_may30",
  "edgeType": "launch_date", "tValidFrom": "2026-01-10T00:00:00Z",
  "tValidTo": "2026-06-30T00:00:00Z", "supersededBy": "edge_a2",
  "evidenceEpisodeIDs": ["ep_7"], "confidence": 0.9, "ingestionTime": "2026-01-10T00:00:00Z" }
```

```jsonc
// audit/tombstones.jsonl
{ "id": "tomb_1", "op": "delete", "targetKind": "episode", "targetID": "ep_legacy7",
  "deletedAt": "2026-06-30T00:00:00Z", "reason": "user erasure", "actor": "user",
  "derived": { "factIDs": ["fact_3"], "edgeIDs": ["edge_9"], "entityIDs": [], "chunkIDs": [],
               "sentenceIDs": ["sent_3"], "embeddingCacheKeys": ["…"], "episodeLinkCount": 0 } }
```

---

## 12. Prior art & how this differs

Portable Memory builds on, rather than replaces, existing work — and fills a specific gap.

- **Memory engines** — mem0, Letta (MemGPT), Zep, OpenMemory, and the memory modules in
  LangChain / LlamaIndex are *runtimes* that store and retrieve memory. They are not
  vendor-neutral interchange formats, and their exports are lossy across engines. Portable
  Memory is the missing *interchange layer*: a losslessly re-importable container those
  engines can export to and ingest from (the `Mem0Adapter` is the first example).
- **MCP (Model Context Protocol)** — a *runtime* protocol connecting models to tools and
  context sources. It is complementary: MCP moves context at call time; Portable Memory is
  the durable, on-disk *data format* for the memory itself. An MCP-based assistant can
  export/import its memory as a `.mem` bundle.
- **Data-portability regimes** — GDPR Art. 20 (right to data portability) and Art. 17
  (erasure), and efforts like the Data Transfer Project, establish that users should be
  able to take their data elsewhere and have it deleted. Portable Memory is a concrete,
  machine-verifiable format for exercising both for AI memory — with deletion propagation
  as a first-class, testable guarantee rather than a policy promise.

What's distinctive here is the combination: local-first + lossless *superset* container +
deletion propagation gated as the conformance badge. None of the above provides all three.

---

*v1.0. Design rationale: keep the format vendor-neutral and local-first; make source
text (not vectors) the portable truth; preserve any vendor's data losslessly (superset
container); and gate conformance on deletion-propagation correctness — the single
hardest guarantee a memory layer makes.*
