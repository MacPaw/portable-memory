# Releasing `portable-memory`

The SDK version is independent of the on-disk **format** version (`format` in the manifest, spec
§9): bump the SDK version for every release; bump the format version only when the spec changes
what a bundle contains.

Releases are tagged `X.Y.Z` (no `v` prefix). The [Swift SDK](https://github.com/MacPaw/portable-memory-swift)
is released with the same version on the same day, so `Spec/`, `Schemas/` and `Conformance/` stay
byte-identical across both repositories.

## 1. Prepare the release PR

1. `pyproject.toml` → `version = "X.Y.Z"` **and** `portable_memory/__init__.py` → `__version__ = "X.Y.Z"`
   (`tests/test_version.py` fails when they disagree).
2. `CHANGELOG.md`: rename **Unreleased** to `## [X.Y.Z] - YYYY-MM-DD`, add a fresh empty
   **Unreleased** above it, and update the compare links at the bottom.
3. If `Spec/`, `Schemas/` or `Conformance/` changed, they must still match the Swift repository
   (`diff -r -x __pycache__ Spec ../portable-memory-swift/Spec`, likewise for the other two) —
   sync the Swift repository in the same release.
4. `pytest -q`, then open the PR from `release/X.Y.Z`. `main` is protected: it needs an approving review.

## 2. Tag and publish to PyPI

1. After the merge: `git checkout main && git pull --ff-only && git tag X.Y.Z && git push origin X.Y.Z`.
2. GitHub → **Releases** → *Draft a new release* for tag `X.Y.Z`, paste the changelog section, **Publish**.
3. Publishing the release runs [`publish.yml`](.github/workflows/publish.yml): it builds the sdist and
   wheel, runs `twine check`, **refuses to continue when the tag differs from the `pyproject` version**,
   smoke-installs the wheel, and uploads through PyPI **Trusted Publishing** (OIDC, the `pypi`
   environment). No API token exists anywhere.
4. Verify from a clean environment — the PyPI simple index can lag the JSON API by a minute:

   ```bash
   python3 -m venv /tmp/pm && /tmp/pm/bin/pip install -q "portable-memory==X.Y.Z" && /tmp/pm/bin/mem --version
   ```

## 3. Homebrew

The formula lives in [`MacPaw/homebrew-taps`](https://github.com/MacPaw/homebrew-taps)
(`Formula/portable-memory.rb`) and points at the PyPI **sdist**. Once PyPI serves the new version
(`brew livecheck macpaw/taps/portable-memory` reports it), open the bump PR:

```bash
export HOMEBREW_GITHUB_API_TOKEN="$(gh auth token)"
brew bump-formula-pr --version=X.Y.Z macpaw/taps/portable-memory
```

This resolves the new sdist URL and `sha256` from PyPI, audits the formula, and opens a PR against the
tap from your fork. To do it by hand instead: take the sdist `url` and `digests.sha256` from
`https://pypi.org/pypi/portable-memory/X.Y.Z/json`, edit the formula, and run
`brew install --build-from-source`, `brew test`, `brew audit --strict --online` and `brew style` on
the tap before opening the PR.

## 4. Swift SDK

Mirror the release in `MacPaw/portable-memory-swift`: same changelog shape, tag `X.Y.Z`, GitHub
release. The [Swift Package Index](https://swiftpackageindex.com/MacPaw/portable-memory-swift) picks
the tag up on its own.
