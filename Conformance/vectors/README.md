# Conformance vectors

Language-neutral test data that pins the parts of the format most likely to drift
between implementations: **Canonical JSON** serialization (spec §1.1) and **signature**
verification (§1.3). If your implementation reproduces these, it is byte-interoperable
with the reference SDKs.

These files are **byte-identical** in the Swift and Python repositories.

## `canonical-json.json`

An array of `vectors`, each with:

| field | meaning |
|---|---|
| `name` | what the case pins |
| `input` | a JSON value |
| `canonical` | the exact Canonical JSON serialization of `input` (spec §1.1) |
| `sha256` | `sha256( utf8(canonical) )`, lowercase hex |

**Conformance:** for every vector, `canonicalize(input)` MUST equal `canonical`
byte-for-byte, and its SHA-256 MUST equal `sha256`. A ~10-line test in any language does
this; see `tests/` in either SDK for the reference loaders.

The cases cover whole-valued floats (`1.0` → `1`), shortest-round-trip fractions,
negative zero, exact integers through `UInt64.max` (**integer fields beyond 2^53 require
a bigint-aware JSON parser** — `JSON.parse` in JS silently rounds them), raw non-ASCII,
short vs `\uXXXX` escapes, `/` unescaped, recursive key sorting, and array-order
preservation.

## `signed.mem` + `signing-test-key.json`

A complete, signed bundle plus the **test keypair** used to sign it (a fixed 32-byte seed
`00 01 … 1f` — obviously not a real secret). Use it to prove signature interop:

- **Verify:** load `publicKeyHex`, verify `manifest.sig` against `manifest.json` → MUST
  pass; flip one byte of `manifest.json` → MUST fail.
- **Sign + verify:** load `privateKeyHex`, sign the manifest bytes, verify your own
  signature with the public key → MUST pass.

> **Signatures are verify-interoperable, not byte-reproducible.** Ed25519 signature bytes
> may differ between implementations (swift-crypto randomizes the nonce; Python's
> `cryptography` is deterministic) — both are valid. So `manifest.sig` is **excluded** from
> the byte-identity guarantee of §1.1; the data files, `manifest.json`, and `CHECKSUMS`
> are covered, the signature is not.

## Known cross-implementation residuals (out of scope for v1)

The reference SDKs are **not** guaranteed byte-identical for these, so no vector asserts
them. Keep them ASCII / in-range where cross-impl byte-identity matters:

- **Object keys outside the BMP** (e.g. emoji as a JSON *key*): key ordering differs
  (UTF-16 code-unit vs code-point). Native record keys are all ASCII; only exotic foreign
  `ext` keys are affected.
- **Integral numeric magnitudes ≥ 1e16** and **integers beyond `UInt64.max`**: exponent
  form and precision handling diverge. Real memory values (scores, counts) never reach
  this range.
- **Record/line ordering for non-ASCII ids**: within-file ordering differs for non-ASCII
  identifiers; use ASCII, kind-prefixed ids.

## Regenerating

`generate.py` (Python repo) rebuilds every file deterministically from the reference
encoder and the fixed test seed. Re-run it after any change to the canonicalization rules,
then confirm both SDK test suites stay green.
