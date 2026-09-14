# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The SDK package version is
independent of the on-disk **format** version (`format` in the manifest).

## [Unreleased]

### Added

- **Format 1.1.0** — the manifest gains four optional fields (spec §3.1): `specURL`,
  `coverage` (`{from, to}` — earliest/latest episode `eventTime`), `scopes` (sorted
  context ids the records reference) and `bundleDigest` (sha256 of the exact `CHECKSUMS`
  bytes — one hash for the whole archive). The exporter emits them; the validator
  recomputes `bundleDigest` when present. 1.0 bundles remain valid — the shipped 1.0
  fixtures double as backward-compatibility tests. `MemCoverage` is exported from the
  package.

## [0.2.0] - 2026-09-14

`pip install portable-memory` now installs the **`mem` command line** — paste an
assistant's memory export, get a verifiable `.mem` bundle, render it back for import
anywhere. (0.1.2 shipped the SDK only.)

### Added

- **README "Try it in 60 seconds"** with a demo GIF of the paste → validate → render flow.
- **`TransferTextAdapter`** (`portable_memory/adapters/transfer.py`) — parses the pasted
  memory-transfer text that ChatGPT, Claude, and Gemini exchange today (the standard
  export prompt's `[date saved, if available] - memory content` entries in a code block;
  tolerant of `-`/`–`/`—`/`:` separators, bullets and numbering, section headers, bare ISO
  dates, month-name dates, indented continuation lines, and plain prose summaries) into
  **deterministic, deduplicated** episodes with the date, section, and line preserved
  verbatim in `transfer_*` metadata — and renders any episodes back into paste-ready text
  (`render_text`). The shared fixture `Conformance/fixtures/transfer/` pins byte-identical
  output across both reference SDKs.
- **`mem` command line** (`[project.scripts]`, also `portable-memory`): `mem paste
  export.txt --out my.mem`, `mem ingest --from openai|claude|mem0|transfer`, `mem render
  my.mem [--fence] [--group]`, `mem validate my.mem`, `mem inspect my.mem`. Standard
  library only.
- **`InMemoryStore`** (`portable_memory/inmemory.py`) — a minimal public store for
  prototyping and the CLI; the shape an adopter's own store takes.

### Fixed

- `portable_memory.__version__` had drifted to `0.1.0` (the 0.1.2 wheel reports it); it
  now tracks `pyproject.toml` and a test enforces it.

## [0.1.2] - 2026-09-13

First release published to PyPI: `pip install portable-memory`.

### Added

- **Paper citation** — README callout and *Citation* section (BibTeX), `CITATION.cff` for
  GitHub's "Cite this repository", and a paper link in the spec header (the spec stays
  byte-identical with the Swift repository). Paper:
  <https://research.macpaw.com/publications/portable-memory>.
- **PyPI packaging** — project URLs (paper, changelog, issues), richer keywords and
  classifiers, and a Trusted-Publishing release workflow
  (`.github/workflows/publish.yml`) that builds, checks, and publishes the package when
  a GitHub release is published — no long-lived API token.

### Fixed

- **Package version alignment** — `pyproject.toml` still declared `0.1.0` while the
  repository was tagged `0.1.1`. The package version now tracks the git tag, and the
  release workflow refuses to publish when they disagree.

## [0.1.1] - 2026-07-03

First public release of the Python reference SDK, reaching parity with the Portable Memory
format (`format` **1.0.0**) and byte-for-byte interoperability with the
[Swift reference SDK](https://github.com/MacPaw/portable-memory-swift). Versioned `0.1.1`
to match the Swift SDK's release of the same day.

### Added

- **Python SDK** — `BundleExporter` / `BundleImporter` / `BundleValidator`, the
  `PortableMemoryStore` seam an adopter subclasses, and dataclass DTOs for all record
  kinds. Fully **synchronous** — local file I/O is done inline, no `async`/`await`.
- **Canonical JSON** — the serialization/hashing helpers in `portable_memory/_codec.py`
  produce output byte-for-byte identical to the Swift SDK's `MemCodec` (spec §1.1), so
  checksums and signatures match across implementations. Whole-valued floats serialize
  as integers, timestamps are whole-second UTC `Z`, NaN/Infinity are rejected, and
  scalar fields are type-checked on decode.
- **Pure-stdlib core** — the core depends only on the standard library (`json`, `hashlib`,
  `dataclasses`, `datetime`). Signing is an optional `[signing]` extra (`cryptography`),
  imported lazily so bundles can be produced and read without it.
- **Deletion propagation (L2)** — portable tombstones with proof-of-reach, applied before
  additions; no-resurrection enforced for **every** kind (not just episodes).
- **Ed25519 signing (L3)** — detached bundle signatures (`manifest.sig`) and tombstone
  signatures, verified against caller-supplied trusted keys.
- **Cross-vendor losslessness** — foreign episode fields via `ext` and foreign kinds via
  verbatim passthrough; a mem0 adapter (`portable_memory/adapters/mem0.py`, verified
  against mem0's documented export shapes), an OpenAI adapter for the ChatGPT data
  export (`adapters/openai.py` — `conversations.json` + a saved-memories fallback), and
  a Claude adapter for Claude memory files (`adapters/claude.py` — `MEMORY.md` + topic
  files with frontmatter).
- **JSON Schemas** for every record kind, the manifest, tombstones, and the audit log,
  validated against samples in the test suite.
- **Conformance kit** — a sample `.mem` fixture and a signed fixture shared with the
  Swift SDK, plus golden canonical-JSON vectors
  (`Conformance/vectors/canonical-json.json`) that every implementation must reproduce.
- **Untrusted-input hardening** — path-traversal + symlink-escape rejection, unlisted-file
  rejection, and a per-file size bound (`MemLimits`).

[Unreleased]: https://github.com/MacPaw/portable-memory/compare/0.2.0...HEAD
[0.2.0]: https://github.com/MacPaw/portable-memory/compare/0.1.2...0.2.0
[0.1.2]: https://github.com/MacPaw/portable-memory/compare/0.1.1...0.1.2
[0.1.1]: https://github.com/MacPaw/portable-memory/releases/tag/0.1.1
