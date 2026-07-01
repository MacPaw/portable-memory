<!-- Thanks for contributing to Portable Memory! -->

## What & why

<!-- What does this change and why? Link any issue. -->

## Type of change

- [ ] SDK change (no wire-format impact)
- [ ] **Spec / format change** (discussed in an issue first — see CONTRIBUTING)
- [ ] New adapter / other-language implementation
- [ ] Docs / conformance / fixtures

## Checklist

- [ ] `pytest -q` passes (run `pip install -e .[dev]` first)
- [ ] Added/updated tests for the change
- [ ] If the wire format changed: the spec, `Schemas/`, the Python DTOs, and the sample
      fixture are all in sync, and the `format` version bump follows GOVERNANCE
- [ ] If the wire format changed: kept parity with the Swift reference SDK
      (bundles stay byte-identical across both implementations)
- [ ] Updated `CHANGELOG.md` under **Unreleased**
- [ ] Commits are signed off (`git commit -s`, DCO)
