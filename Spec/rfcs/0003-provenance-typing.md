# RFC-0003: Provenance typing — how a memory came to be

| | |
|---|---|
| **Status** | Draft — open for comment until 2026-10-05 |
| **Discussion** | https://github.com/MacPaw/portable-memory/issues/14 |
| **Target** | format **1.2.0** (minor, backward-compatible); depends on RFC-0002 for lossless carriage on non-episode kinds |
| **Author** | MacPaw (Sergii Kryvoblotskyi) · created 2026-09-14 |
| **Affects** | spec §2 (data model — identity, time & provenance), §6 (Evidence Pack), §10 (adapters), §11 (conformance); `Schemas/`; both reference SDKs |

## 1. Problem

Provenance in the format today answers *what justifies this?* — an edge carries
`evidenceEpisodeIDs`, a fact carries `episodeID`, every record has `confidence`, updates
supersede rather than overwrite (`supersededBy`), and every mutation lands in the audit
log. It does not answer two questions a reader — or an auditor — asks first:

- **How did this memory come to be?** Was it *asserted* by a person ("I prefer metric
  units"), *observed* by the system (a message that happened), *inferred* by a model
  ("the user seems to work in fintech"), *merged* from several earlier records, or
  *imported* from another system through an adapter?
- **Who asserted it?** A person, an agent, a model (which one, which version)?

Those distinctions are exactly what separates a fact from a guess when memory crosses a
vendor boundary, and exactly what an erasure or accuracy review needs ("show me every
*inferred* claim about this person"). Sources carry them — the Engram spec has
`claim_class` (`observed | documented | structural | asserted | inferred | revised`) and
`attribution.asserted_by` / `.model`; conversation exports know the speaker's role — and
our adapters preserve them only as opaque, vendor-namespaced metadata.

## 2. Goals and non-goals

**Goals**

- **G1** A small, shared vocabulary for *how* a memory came to be, usable by every adapter
  and understood by every receiver.
- **G2** A typed *who* — the asserting principal — reusing RFC-0001's principal syntax so
  attribution and visibility speak the same language.
- **G3** Merge lineage: when records are consolidated, the result names what it replaced.
- **G4** Optional everywhere; minor bump; readers accept absence.

**Non-goals**

- A full provenance graph (W3C PROV). We align names with PROV (§6) but carry three
  fields, not a graph.
- Trust scoring or truth adjudication. `confidence` stays what it is; this RFC only makes
  the *origin* of a claim explicit.

## 3. Proposal

Three optional fields on `episode`, `fact`, `edge` and `entity` (facts and edges are
where derived knowledge lives; episodes and entities are where imported and observed
knowledge lands):

### 3.1 `claimClass`

One of:

| value | meaning | typical producer |
|---|---|---|
| `asserted` | stated directly by a person or an authoritative source, kept verbatim in spirit | user says "I use metric units"; a document states a fact |
| `observed` | recorded by the system as it happened | a conversation turn; a captured event |
| `inferred` | derived by a model or rule from other memories | "works in fintech" from several episodes |
| `merged` | the consolidation of two or more earlier records | reconciliation, dedup |
| `imported` | brought in from another system through an adapter, class unknown at source | pasted memory-transfer text; a vendor export with no origin data |

Receivers MUST preserve unknown values (the enumeration may grow) and SHOULD treat a
record without `claimClass` as `imported` when it arrived through an adapter and as
unspecified otherwise.

### 3.2 `assertedBy`

A single principal string in RFC-0001's `<type>:<id>` form naming who made the claim —
`user:alice@example.com`, `agent:claude-code`, `model:gpt-5@2026-06`, `system:mnemos`.
Opaque; never resolved by the format. For `inferred` records this is the model or agent
that inferred; for `merged` records the process that merged.

### 3.3 `mergedFrom`

`string[]` — the ids of the records consolidated into this one. Used with
`claimClass: merged`. The merged-away records are expected to be **superseded, not
deleted** (§2 bi-temporal rule), so the lineage stays reconstructible; if a host does
delete them, the ids remain as opaque history.

### 3.4 Where existing fields stop and these start

| question | today | with RFC-0003 |
|---|---|---|
| what justifies it? | `episodeID`, `evidenceEpisodeIDs` | unchanged |
| how sure? | `confidence` | unchanged |
| what replaced what? | `supersededBy` (one-to-one, in time) | + `mergedFrom` (many-to-one, by consolidation) |
| how did it come to be? | — | `claimClass` |
| who said so? | `speaker` (the utterer of an episode), `actors` | + `assertedBy` (the *claimant* of a fact/edge/entity — often a model, not a speaker) |

`speaker` is not renamed: it answers "who was talking" on an episode; `assertedBy`
answers "who stands behind this claim" on any record.

### 3.5 Evidence Pack (§6)

The Evidence Pack SHOULD include `claimClass` and `assertedBy` on its provenance rows so a
reviewer can partition a person's memory into asserted / observed / inferred and see
which models produced the inferences — the single most useful cut in an erasure or
accuracy review.

## 4. Adapter mappings (informative)

| Source | `claimClass` | `assertedBy` |
|---|---|---|
| Engram / PLUR `claim_class` | `observed`→`observed`, `documented`/`structural`/`asserted`→`asserted`, `inferred`→`inferred`, `revised`→`merged` (with `mergedFrom` if `previous_version_ref` present) | `attribution.asserted_by` / `attribution.model.name` → `user:`/`agent:`/`model:` |
| ChatGPT `conversations.json` turns | `observed` | `user:<owner>` for user turns, `agent:chatgpt` (+ `model:<model_slug>`) for assistant turns |
| Claude memory files | `asserted` | `agent:claude` |
| Pasted memory-transfer text | `imported` | `agent:<source>` (the assistant that produced the export) |
| mem0 memories (LLM-extracted) | `inferred` | `agent:mem0` |

Adapters keep the raw source values in namespaced metadata as today.

## 5. Compatibility

- **Format:** minor bump, bundled into **1.2.0** with RFC-0001/0002. All fields optional.
- **Old readers:** ignore the fields; for non-episode kinds they would drop them on
  re-export until RFC-0002 lands — hence the dependency.
- **Identity & merge (§4.1):** none of the three fields is part of record identity. On
  merge, `claimClass` follows the surviving record; `mergedFrom` lists are unioned.
- **Schemas:** a shared `$defs/claimClass` enumeration (open — `string` with documented
  values, so unknown future values validate) and `$defs/principal` reused from RFC-0001.

## 6. Alignment with W3C PROV (informative)

`assertedBy` ≈ `prov:wasAttributedTo`; `mergedFrom` ≈ `prov:wasDerivedFrom`;
`evidenceEpisodeIDs` / `episodeID` ≈ `prov:used`; `claimClass` has no direct PROV
counterpart (PROV types the *activity*, not the epistemic status of the claim) — it is the
field that makes the vocabulary useful to a reviewer without a graph query.

## 7. Conformance

- **L1** gains: the three fields round-trip verbatim (via RFC-0002 for non-episode kinds).
- **L3 / Evidence Pack** gains: provenance rows carry `claimClass` and `assertedBy` when
  the host has them.

## 8. Open questions

1. Is five classes the right granularity? (`documented` — from a file — vs `asserted` —
   from a person — is a distinction the Engram spec keeps and this RFC collapses.)
2. Should `assertedBy` allow a list (co-asserted claims), or stay singular with
   `mergedFrom` covering multi-origin cases?
3. Should `episode` carry `claimClass` at all, or is `sourceType` (`chat` / `note` /
   `event` / …) already that field for episodes? (Proposed: allow both; `sourceType` is
   the *channel*, `claimClass` the *epistemic status*.)
4. Model identifiers: recommend `model:<name>@<version>` or leave the id fully opaque?

## 9. Timeline

Comment period until **2026-10-05** alongside RFC-0001 and RFC-0002; decision by lazy
consensus (GOVERNANCE); implementation in both SDKs with fixture coverage; format
**1.2.0**.
