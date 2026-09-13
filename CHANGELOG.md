# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The SDK package version is
independent of the on-disk **format** version (`format` in the manifest).

## [Unreleased]

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

[Unreleased]: https://github.com/MacPaw/portable-memory/compare/0.1.2...HEAD
[0.1.2]: https://github.com/MacPaw/portable-memory/compare/0.1.1...0.1.2
[0.1.1]: https://github.com/MacPaw/portable-memory/releases/tag/0.1.1
