"""``mem`` — the Portable Memory command line (Python reference SDK).

Zero dependencies, works on the memory you can already get out of an assistant today::

    mem paste export.txt --out my-memory.mem --source chatgpt   # pasted memory text → .mem
    mem ingest --from openai conversations.json --out my-memory.mem
    mem ingest --from claude  ~/.claude/memory --out my-memory.mem
    mem ingest --from mem0    memories.json --out my-memory.mem
    mem render   my-memory.mem --fence      # .mem → paste-ready text for Claude/Gemini import
    mem validate my-memory.mem              # checksums, structure, no injected files
    mem inspect  my-memory.mem              # manifest summary

Exit codes: 0 ok · 1 validation failed · 2 usage / input error.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Sequence

from . import __version__
from ._codec import format_timestamp
from .adapters.claude import ClaudeAdapter
from .adapters.mem0 import Mem0Adapter
from .adapters.openai import OpenAIAdapter
from .adapters.transfer import TransferTextAdapter
from .exporter import BundleExporter
from .importer import BundleImporter, MemImportError
from .inmemory import InMemoryStore
from .records import PortableEpisode
from .validator import BundleValidator

_FORMATS = ("transfer", "openai", "claude", "mem0")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    try:
        return int(args.func(args))
    except MemImportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


# ── Commands ──────────────────────────────────────────────────────────────────────────

def _cmd_ingest(args: argparse.Namespace) -> int:
    episodes = _parse(args.source_format, args.input, args.source)
    store = InMemoryStore(generator=f"portable-memory-cli/{__version__}")
    for e in episodes:
        store.import_episode(e, None)
    manifest = BundleExporter().export(store, args.out)
    print(f"wrote {args.out}: {len(episodes)} episodes in {len(manifest.files)} files")
    for f in manifest.files:
        print(f"  {f.sha256[:16]}…  {f.path}  ({f.bytes} bytes)")
    if not episodes:
        print("  (no entries recognized — is this the right --from format?)", file=sys.stderr)
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    store = InMemoryStore()
    BundleImporter().import_bundle(store, args.bundle, reembed=False)
    episodes = sorted(store.episodes.values(), key=lambda e: (e.event_time, e.id))
    text = TransferTextAdapter.render_text(episodes, group_by_section=args.group)
    if args.fence:
        text = "```\n" + text + "```\n"
    sys.stdout.write(text)
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    result = BundleValidator().validate(args.bundle)
    if result.ok:
        n = len(result.manifest.files) if result.manifest else 0
        fmt = result.manifest.format if result.manifest else "?"
        print(f"OK  {args.bundle} — {n} files verified, format {fmt}")
        return 0
    print(f"FAIL  {args.bundle} — {len(result.issues)} issue(s):", file=sys.stderr)
    for issue in result.issues:
        print(f"  - {issue}", file=sys.stderr)
    return 1


def _cmd_inspect(args: argparse.Namespace) -> int:
    result = BundleValidator().validate(args.bundle)
    m = result.manifest
    if m is None:
        print(f"error: no readable manifest at {args.bundle}", file=sys.stderr)
        for issue in result.issues:
            print(f"  - {issue}", file=sys.stderr)
        return 1
    print(f"bundle:      {args.bundle}")
    print(f"format:      {m.format}")
    print(f"generator:   {m.generator}")
    print(f"conformance: {m.conformance_level.value}")
    print(f"created:     {format_timestamp(m.created_at)}")
    print(f"mode:        {m.export_mode.value}" + (f" since {format_timestamp(m.since)}" if m.since else ""))
    # Format 1.1 summaries — what the archive covers, in which scopes, and its one-line digest.
    if m.spec_url:
        print(f"spec:        {m.spec_url}")
    if m.coverage is not None:
        print(f"coverage:    {format_timestamp(m.coverage.from_)} → {format_timestamp(m.coverage.to)}")
    if m.scopes:
        print("scopes:      " + ", ".join(m.scopes))
    if m.bundle_digest:
        print(f"digest:      {m.bundle_digest}")
    print(f"integrity:   {'OK' if result.ok else 'ISSUES (' + str(len(result.issues)) + ')'}")
    counts = {k: v for k, v in sorted(m.counts.items()) if v}
    print("counts:      " + (", ".join(f"{k}: {v}" for k, v in counts.items()) or "(empty)"))
    print("files:")
    for f in m.files:
        print(f"  {f.sha256[:16]}…  {f.path}  ({f.bytes} bytes)")
    for issue in result.issues:
        print(f"  ! {issue}", file=sys.stderr)
    return 0 if result.ok else 1


# ── Input handling ────────────────────────────────────────────────────────────────────

def _parse(source_format: str, path: str, source: str | None) -> list[PortableEpisode]:
    if source_format == "transfer":
        return TransferTextAdapter.parse_episodes(_read_text(path), source=source)
    if source_format == "openai":
        return OpenAIAdapter.parse_episodes(_read_text(path))
    if source_format == "mem0":
        return Mem0Adapter.parse_episodes(_read_text(path))
    if source_format == "claude":
        return ClaudeAdapter.parse_episodes(_claude_files(path))
    raise ValueError(f"unknown --from format: {source_format}")


def _read_text(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _claude_files(path: str) -> list[dict[str, str]]:
    """A directory of Claude memory files → [{path, content}], or a JSON list as-is."""
    if os.path.isdir(path):
        files: list[dict[str, str]] = []
        for root, _dirs, names in os.walk(path):
            for name in sorted(names):
                if not name.endswith(".md"):
                    continue
                full = os.path.join(root, name)
                with open(full, "r", encoding="utf-8") as fh:
                    files.append({"path": os.path.relpath(full, path), "content": fh.read()})
        files.sort(key=lambda f: f["path"])
        return files
    return json.loads(_read_text(path))


# ── Argument parser ───────────────────────────────────────────────────────────────────

def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mem",
        description="Portable Memory — an open, vendor-neutral .mem format for AI memory.",
        epilog="Docs: https://github.com/MacPaw/portable-memory",
    )
    p.add_argument("--version", action="version", version=f"portable-memory {__version__}")
    sub = p.add_subparsers(dest="command")

    paste = sub.add_parser("paste", help="pasted memory-transfer text → .mem bundle")
    paste.add_argument("input", help="text file with the assistant's memory export ('-' for stdin)")
    paste.add_argument("--out", required=True, help="bundle directory to write, e.g. my-memory.mem")
    paste.add_argument("--source", help="where the text came from: chatgpt, claude, gemini, …")
    paste.set_defaults(func=_cmd_ingest, source_format="transfer")

    ingest = sub.add_parser("ingest", help="a vendor export → .mem bundle")
    ingest.add_argument("--from", dest="source_format", required=True, choices=_FORMATS,
                        help="transfer (pasted text), openai (conversations.json), claude (memory files dir), mem0 (json)")
    ingest.add_argument("input", help="file, directory (claude), or '-' for stdin")
    ingest.add_argument("--out", required=True, help="bundle directory to write")
    ingest.add_argument("--source", help="source label recorded on transfer-text entries")
    ingest.set_defaults(func=_cmd_ingest)

    render = sub.add_parser("render", help=".mem bundle → paste-ready memory text")
    render.add_argument("bundle")
    render.add_argument("--fence", action="store_true", help="wrap in a ``` code fence")
    render.add_argument("--group", action="store_true", help="group entries under ## section headers")
    render.set_defaults(func=_cmd_render)

    validate = sub.add_parser("validate", help="verify a bundle's integrity (L0)")
    validate.add_argument("bundle")
    validate.set_defaults(func=_cmd_validate)

    inspect = sub.add_parser("inspect", help="show a bundle's manifest")
    inspect.add_argument("bundle")
    inspect.set_defaults(func=_cmd_inspect)
    return p


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
