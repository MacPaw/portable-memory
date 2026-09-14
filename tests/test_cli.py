"""``mem`` command line — end-to-end on temp bundles, in-process."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from portable_memory.cli import main

FIXTURES = Path(__file__).resolve().parents[1] / "Conformance" / "fixtures" / "transfer"


def test_paste_validate_inspect_render(tmp_path, capsys):
    src = tmp_path / "export.txt"
    src.write_text((FIXTURES / "sample-export.txt").read_text(encoding="utf-8"), encoding="utf-8")
    out = tmp_path / "my.mem"

    assert main(["paste", str(src), "--out", str(out), "--source", "chatgpt"]) == 0
    o = capsys.readouterr().out
    assert "11 episodes" in o and (out / "manifest.json").exists() and (out / "CHECKSUMS").exists()

    assert main(["validate", str(out)]) == 0
    assert capsys.readouterr().out.startswith("OK")

    assert main(["inspect", str(out)]) == 0
    o = capsys.readouterr().out
    assert "episode: 11" in o and "portable-memory-cli/" in o and "integrity:   OK" in o

    assert main(["render", str(out), "--fence"]) == 0
    o = capsys.readouterr().out
    assert o.startswith("```\n") and o.endswith("```\n")
    assert "[2025-11-03] - Prefers concise answers: code first, explanation second." in o
    assert "  Exception: emoji are fine in casual chats." in o

    assert main(["render", str(out), "--group"]) == 0
    assert "## INSTRUCTIONS" in capsys.readouterr().out


def test_paste_from_stdin(tmp_path, capsys, monkeypatch):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("[2026-01-01] - from stdin\n"))
    out = tmp_path / "s.mem"
    assert main(["paste", "-", "--out", str(out)]) == 0
    assert "1 episodes" in capsys.readouterr().out


def test_ingest_openai_and_claude_dir(tmp_path, capsys):
    export = [{
        "title": "T", "conversation_id": "c1", "mapping": {
            "a": {"id": "a", "message": {"id": "m1", "author": {"role": "user"},
                  "content": {"content_type": "text", "parts": ["hello"]}, "create_time": 1700000000.0}},
            "b": {"id": "b", "message": {"id": "m2", "author": {"role": "assistant"},
                  "content": {"content_type": "text", "parts": ["hi"]}, "create_time": 1700000001.0}},
        },
    }]
    conv = tmp_path / "conversations.json"
    conv.write_text(json.dumps(export), encoding="utf-8")
    assert main(["ingest", "--from", "openai", str(conv), "--out", str(tmp_path / "o.mem")]) == 0
    assert "2 episodes" in capsys.readouterr().out

    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "MEMORY.md").write_text("# index\n- proj\n", encoding="utf-8")
    (mem / "proj.md").write_text("---\nname: proj\n---\nShip it.\n", encoding="utf-8")
    (mem / "notes.txt").write_text("ignored\n", encoding="utf-8")
    assert main(["ingest", "--from", "claude", str(mem), "--out", str(tmp_path / "c.mem")]) == 0
    assert "2 episodes" in capsys.readouterr().out


def test_validate_detects_tampering(tmp_path, capsys):
    out = tmp_path / "t.mem"
    src = tmp_path / "e.txt"
    src.write_text("[2026-01-01] - a\n", encoding="utf-8")
    assert main(["paste", str(src), "--out", str(out)]) == 0
    capsys.readouterr()
    with open(out / "items" / "episode.jsonl", "ab") as fh:
        fh.write(b'{"id":"evil"}\n')
    assert main(["validate", str(out)]) == 1
    assert "FAIL" in capsys.readouterr().err
    assert main(["inspect", str(out)]) == 1


def test_missing_input_and_bad_bundle(tmp_path, capsys):
    assert main(["paste", str(tmp_path / "nope.txt"), "--out", str(tmp_path / "x.mem")]) == 2
    assert "error:" in capsys.readouterr().err
    assert main(["render", str(tmp_path / "not-a-bundle")]) == 2
    assert main(["inspect", str(tmp_path / "not-a-bundle")]) == 1


def test_version_and_no_command(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.startswith("portable-memory ")
    assert main([]) == 2


def test_inspect_shows_format_1_1_fields_and_validate_catches_digest_tamper(tmp_path, capsys):
    import shutil
    fixture = Path(__file__).resolve().parents[1] / "Conformance" / "fixtures" / "sample-1.1.mem"
    assert main(["inspect", str(fixture)]) == 0
    o = capsys.readouterr().out
    assert "format:      1.1.0" in o
    assert "spec:        https://github.com/MacPaw/portable-memory/blob/main/Spec/portable-memory-spec.md" in o
    assert "coverage:    2023-11-14T22:13:20Z → 2026-03-01T00:00:00Z" in o
    assert "scopes:      ctx_comms, ctx_instructions, ctx_root" in o
    assert "digest:      d9b8b8899dec2e16" in o and "integrity:   OK" in o

    out = tmp_path / "c.mem"
    shutil.copytree(fixture, out)
    with open(out / "CHECKSUMS", "ab") as fh:
        fh.write(b"0" * 64 + b"  items/evil.jsonl\n")
    assert main(["validate", str(out)]) == 1
    assert "bundleDigest mismatch" in capsys.readouterr().err
