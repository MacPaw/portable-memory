# Security Policy

Portable Memory is a **trust-centric** format — it makes claims about integrity,
authenticity, and provable deletion. We take reports about those guarantees seriously.

## Reporting a vulnerability

**Please do not open a public issue for a security vulnerability.**

Report privately via **GitHub Security Advisories**: on this repository, go to the
**Security** tab → **Report a vulnerability**. This opens a private channel with the
maintainers.

Please include: a description, affected file(s)/function(s), a reproduction (a crafted
`.mem` bundle is ideal), and the impact you foresee. We aim to acknowledge within a few
business days and to agree on a disclosure timeline with you.

## Supported versions

Until `1.0.0` of the SDK, only the latest tagged release (and `main`) receives security
fixes. The on-disk **format** is versioned separately (`format` in the manifest).

## Scope

In scope — issues in this repository's code or spec, for example:

- Path traversal / zip-slip / symlink escape when reading a bundle.
- Signature forgery or verification bypass (`manifest.sig`, tombstone signatures).
- Checksum bypass, or a way to make a tampered bundle validate/import.
- `secretRef` leakage — any path by which plaintext/ciphertext or recoverable secret
  material leaves a bundle.
- Denial of service from a crafted bundle (memory exhaustion, unbounded work).

## Threat model (summary)

A `.mem` bundle is **untrusted input**. Readers MUST:

- treat checksums as **integrity** (corruption detection), **not** authenticity;
- verify Ed25519 signatures (`manifest.sig` / tombstones) against a **trusted key** when
  authenticity is required (spec §1.3);
- reject bundle paths that escape the bundle root (including via symlinks) and files not
  listed in the manifest;
- bound per-file size (`MemLimits`) before reading.

Signing lives in the optional `[signing]` extra (`cryptography`); it is imported lazily,
so a bundle can be produced or read without it, but authenticity checks are only available
when it is installed. A verifier that cannot check a signature MUST NOT treat the bundle as
authentic.

Bundles are **plaintext by design** (inspectable, vendor-neutral). Confidentiality is an
envelope concern — encrypt at rest/in transit with your own tooling. Secrets are never
carried as plaintext or ciphertext (spec §7).
