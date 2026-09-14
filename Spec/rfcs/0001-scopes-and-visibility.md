# RFC-0001: Scopes & visibility — who may see a memory

| | |
|---|---|
| **Status** | Draft — open for comment until 2026-10-05 |
| **Discussion** | https://github.com/MacPaw/portable-memory/issues/11 |
| **Target** | format **1.2.0** (minor, backward-compatible) |
| **Author** | MacPaw (Sergii Kryvoblotskyi) · created 2026-09-14 |
| **Affects** | spec §2 (data model), §3 (manifest), §4 (merge), §11 (conformance); `Schemas/`; both reference SDKs |

## 1. Problem

Portable Memory says **where** a memory belongs — `contextID` → `context` records, which nest
via `parentID` — and **how sensitive** it is (`sensitivity`). It does not yet say **who may
see it**. Real memory is scoped: some of it is visible to everyone in a channel or workspace,
some is private to one person, some is restricted to a group. Every source we ingest carries
such a setting — PLUR engrams have `visibility: private | public | template` and
`scope: agent:X | space:X | global`; team memory tools bind memories to a channel; personal
assistants keep everything private to the account owner.

Today those settings survive a round-trip only as opaque `ext` / namespaced metadata. That is
lossless, but not *meaningful*: a receiving system cannot honor an audience restriction it
cannot read, so a cross-vendor import can silently **widen** who sees a private memory. This
is the one layer of the format that still has "no shared meaning" — the failure the format
was built to remove everywhere else.

## 2. Goals and non-goals

**Goals**

- **G1** Express the three audiences that occur in practice: *visible to a shared scope*
  (channel, space, workspace), *private to one person*, *restricted to a group*.
- **G2** Portable **without a shared identity provider**: principals are labels the sender
  chose, not accounts the receiver must know.
- **G3** Honorable without an ACL engine: a receiver that can only follow a simple
  default-deny rule still does the right thing.
- **G4** Backward-compatible minor bump: 1.0/1.1 readers ignore the new field; 1.2 readers
  accept its absence.
- **G5** Lossless: vendor-specific ACLs beyond this model still ride along in `ext`.

**Non-goals**

- Enforcement. The format *labels*; the host *enforces*. Conformance can test that a
  receiver honors labels (§7), not mandate an access-control architecture.
- Confidentiality of the bundle itself (encryption per scope). Complementary; a separate
  RFC. `secretRef` already keeps secret material out of bundles.
- Identity federation or resolving principals across vendors.
- Per-field redaction (see §5 of the spec for whole-record redaction).

## 3. Proposal

### 3.1 The `visibility` object

```json
"visibility": {
  "level": "group",
  "principals": ["group:platform-team", "user:alice@example.com"]
}
```

- **`level`** (required when the object is present) — one of:
  - `private` — one person. `principals` SHOULD name exactly one `user:` principal; when
    omitted it means *the bundle's owner*.
  - `group` — a closed set: exactly the principals listed.
  - `shared` — everyone with access to the containing scope (the `context` the record
    belongs to, or the scope principal named in `principals`, e.g. `channel:` / `space:`).
  - `public` — no restriction.
- **`principals`** (optional, `string[]`, de-duplicated, sorted by Unicode code point on
  export like every other list the canonical form sorts) — opaque identifiers of the form
  `<type>:<id>`. Recommended types: `user`, `group`, `channel`, `space`, `agent`, `org`.
  The format never resolves them (G2). Unknown types MUST be preserved.

### 3.2 Where it lives

- **On `context` records** — a *scope default*: applies to every record whose `contextID`
  resolves to that context or to a descendant (via `parentID`) unless the record overrides.
  This is how "everything in #ops is channel-visible" is said once.
- **On records** — an optional `visibility` on `episode`, `fact`, `entity`, `resource`
  (its `chunk`s inherit), `core`, `procedure`, `preference`. It overrides the context
  default. One private note inside a shared channel is a per-record override.
- **Derived records** — an `edge` or `fact` whose evidence (`evidenceEpisodeIDs`,
  `episodeID`) is restricted inherits the **most restrictive** visibility among its evidence
  unless it carries its own.

### 3.3 Precedence

```
record.visibility  >  nearest context.visibility (walking parentID)  >  unspecified
```

**Unspecified** (no `visibility` anywhere, which is every 1.0/1.1 bundle) means the sender
said nothing. A receiver applies its own default and **MUST NOT widen beyond
private-to-the-importing-user without an explicit user decision.** Default-deny is the only
safe reading of silence.

### 3.4 Receiver obligations (normative in 1.2)

1. **Preserve** `visibility` verbatim on re-export, including principals it cannot resolve
   (this is L1 losslessness, spec §4).
2. **Honor** it when surfacing memories: show a record to a viewer only if the viewer maps
   to a listed principal (`private`, `group`), has access to the scope (`shared`), or the
   level is `public`. A principal the receiver cannot map is treated as *no one* — so an
   unresolvable `group` is visible only to the importing owner.
3. **Never downgrade on merge.** The order is `private < group < shared < public`; when two
   versions of the same record disagree, the merge result carries the lower level and the
   intersection of principals. A stale bundle can therefore never re-widen a memory the
   owner has since restricted (the mirror of the tombstone no-resurrection rule).
4. Deletion and redaction (§5) are unchanged: a tombstone removes the record for every
   audience.

### 3.5 Manifest summary (optional, 1.2)

Alongside 1.1's `scopes`, an optional distribution so an auditor sees the audience mix
without opening a stream:

```json
"visibility": { "private": 12, "group": 3, "shared": 40, "public": 0, "unspecified": 5 }
```

### 3.6 Audience-scoped export (SDK behavior, not format)

Exporters SHOULD offer `export(..., audience=...)`: emit only records the given principal
may see, so a user can hand a teammate "the shared memories, not my private ones". The
manifest's `scopes`/`visibility` summaries describe the *result*. This is a filter, not a
format feature, and needs no spec change beyond this section.

## 4. Adapter mappings (informative)

| Source | `visibility` on import |
|---|---|
| Engram / PLUR — `visibility: private`, `scope: agent:X` | `private`, principals `["agent:X"]` |
| Engram / PLUR — `visibility: public`, `scope: space:X` / `global` | `shared` + `["space:X"]` / `public` |
| Engram / PLUR — `visibility: template` | `public` |
| Channel-bound team memory (Slack / Discord tools) | `shared` + `["channel:<platform>/<name>"]` |
| ChatGPT / Claude / Gemini personal memory, pasted transfer text | `private` (owner) |
| Cursor / repo-scoped rules | `shared` + `["space:<repo>"]` |
| mem0 — `user_id` / `agent_id` / `run_id` | `private` + `["user:<id>"]` / `["agent:<id>"]`; org-scoped → `shared` |

Adapters keep the source's raw setting in namespaced metadata as today; `visibility` is the
shared meaning layered on top.

## 5. Compatibility

- **Format:** minor bump **1.1.0 → 1.2.0**. All new fields optional. A 1.0/1.1 reader
  ignores them; a 1.2 reader accepts their absence (§3.3).
- **Losslessness prerequisite.** Unknown-field carriage (`ext`) exists today only on
  `episode` (spec §10). For `visibility` on other kinds to survive a re-export by a 1.0/1.1
  reader, `ext` must extend to **every** record kind. That is a separate, prerequisite
  change (**RFC-0002**); until it lands, a 1.0/1.1 reader would drop `visibility`
  from non-episode kinds on re-export — a losslessness violation we would rather fix than
  document.
- **Schemas:** one `$defs/visibility` reused by every kind that may carry it; `context`
  gains the same property.
- **Identity & merge (§4.1):** `visibility` is **not** part of any record's identity; the
  merge rule in §3.4(3) applies.
- **Both reference SDKs** land the change together with a shared fixture (GOVERNANCE), as
  every format change has so far.

## 6. Conformance

- **L1** gains: *visibility preserved verbatim on round-trip* (including unknown principal
  types).
- **L3** gains an optional probe: *visibility honored* — import a bundle with `private` and
  `group` needle memories, then assert a viewer outside the principals cannot retrieve them
  through any route the host exposes (the deletion probe, pointed at audience).

## 7. Alternatives considered

- **A. Context-only ACL, no per-record field.** Fewer bytes, but cannot express one private
  memory inside a shared channel — the most common real case. Rejected; kept as the default
  layer (§3.2).
- **B. Full ACL model (allow/deny lists, roles, inheritance flags).** Hosts differ too much
  and principals are unresolvable across vendors anyway; the extra expressiveness would not
  be honored. Rejected in favor of four levels + labels.
- **C. Reuse `sensitivity`.** Sensitivity is *classification* (how harmful if leaked);
  visibility is *audience*. A public-but-sensitive memory and a private-but-mundane one are
  both real. Orthogonal; keep both.
- **D. Encrypt per scope instead.** Protects confidentiality in transit and at rest, not
  "who may see" inside a receiving host. Complementary; future RFC.

## 8. Open questions

1. Principal identifiers: opaque prefixed strings only, or recommend W3C DIDs
   (`did:…`) for the `user` type as the concurrent PAM proposal does?
2. Should `shared` **require** a scope principal, or may it be bare (= the record's own
   context)?
3. Is *unspecified → receiver default, never widen* the right reading of 1.0/1.1 bundles,
   or should absence mean `private`?
4. Should `principals` participate in the manifest `scopes` enumeration (1.1), or stay a
   separate summary (§3.5)?

## 9. Timeline

Comment period until **2026-10-05** on the discussion issue; decision by lazy consensus
(GOVERNANCE); then implementation in both SDKs + fixture; format **1.2.0**.
