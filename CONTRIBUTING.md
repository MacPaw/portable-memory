# Contributing to Portable Memory

Thanks for helping build an open, vendor-neutral memory format. Contributions of every
kind are welcome — SDK code, new adapters, other-language implementations, spec
clarifications, and conformance fixtures.

## Ways to contribute

- **Implement the spec** in another language. The format is defined by
  [`Spec/portable-memory-spec.md`](Spec/portable-memory-spec.md) and the language-neutral
  [`Schemas/`](Schemas); you don't need this Python SDK to interoperate.
- **Write an adapter** that maps another vendor's export into the model (see
  `portable_memory/adapters/mem0.py` for the pattern — map what's modeled, keep the rest
  in `ext`/`metadata` so a later export stays lossless).
- **Improve the SDK** — bug fixes, robustness, docs.
- **Propose a spec change** (see below).

## Building & testing

```sh
pip install -e .[dev]
pytest
```

The `[dev]` extra pulls in `pytest`, `jsonschema` (for validating `Schemas/` against
samples), and `cryptography` (so signing paths are exercised). Please add a test with any
behavior change; the reference in-memory store in the test suite shows the shape an adopter
implements by subclassing `PortableMemoryStore`.

## SDK changes vs spec changes

- **SDK change** (code/tests/docs, no wire-format impact): open a PR.
- **Spec change** (anything that alters the on-disk format, schemas, or a normative
  requirement): open an issue using the **Spec change** template first, so the design can
  be discussed before implementation. Format-affecting changes follow semver on the
  manifest `format` field and are decided per [`GOVERNANCE.md`](GOVERNANCE.md).

Keep the spec, the JSON Schemas, the Python DTOs, and the sample fixture **in sync** — a PR
that changes one usually needs to touch the others. `pytest` validates the shipped fixture;
please also validate `Schemas/` against your samples. Because there are now two reference
SDKs (Python here and [Swift](https://github.com/MacPaw/portable-memory-swift)), a
format-affecting change must land in both before the format version is bumped — see
[`GOVERNANCE.md`](GOVERNANCE.md).

## Conventions

- Match the surrounding style; keep the SDK dependency-light. The core is **pure standard
  library** (`json`, `hashlib`, `dataclasses`, `datetime`); the only optional dependency is
  `cryptography`, behind the `[signing]` extra and imported lazily. Don't add runtime
  dependencies to the core.
- The SDK is fully **synchronous** — local file I/O is done inline, no `async`/`await`.
  (The Swift SDK uses `async` for actor isolation; the Python side has no such requirement.)
- Canonical JSON rules are normative (spec §1.1) — don't introduce serialization that
  diverges from the canonical helpers in `portable_memory/_codec.py`. Serialize and hash
  through those helpers so bytes match the Swift SDK exactly.
- Update [`CHANGELOG.md`](CHANGELOG.md) under **Unreleased**.

## Developer Certificate of Origin (DCO)

We use the [DCO](https://developercertificate.org/) rather than a CLA. Sign off each
commit (`git commit -s`), certifying you have the right to submit it under the project's
MIT license:

```
Signed-off-by: Your Name <you@example.com>
```

By contributing, you agree your contributions are licensed under the repository's
[MIT license](LICENSE).
