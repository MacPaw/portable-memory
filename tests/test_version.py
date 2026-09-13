"""The package's ``__version__`` must track ``pyproject.toml`` — the release workflow
refuses to publish when the git tag disagrees with pyproject, and this keeps the runtime
attribute honest too (it drifted to 0.1.0 while the repo was tagged 0.1.1)."""
from __future__ import annotations

import re
from pathlib import Path

import portable_memory


def test_version_matches_pyproject():
    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    declared = re.search(r'^version = "([^"]+)"$', text, re.M).group(1)
    assert portable_memory.__version__ == declared
