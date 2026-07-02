"""Anthropic / Claude memory ingest adapter.

Claude's memory is a *directory of files* — a ``MEMORY.md`` entrypoint plus topic files
(markdown, commonly with YAML frontmatter), as used by the Claude Code auto-memory and the
API memory tool. This adapter maps each memory file onto one portable episode: the file
body becomes the episode text, and the frontmatter (``name``, ``description``,
``metadata.type``) plus the file path are preserved into ``metadata`` (namespaced
``claude_*``) so a later ``.mem`` export stays lossless.

Input is the memory files themselves (not JSON), since Claude leaves the storage format to
the host. Accepted shapes (tolerant):
  * ``list`` of ``{"path": str, "content": str}`` (``name``/``text``/``body`` also accepted);
  * ``list`` of ``(path, content)`` tuples;
  * ``dict`` mapping ``path -> content``.

Adapters are pure: files in, ``list[PortableEpisode]`` out. No host, store, or I/O.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

from ..records import PortableEpisode

__all__ = ["ClaudeAdapter", "parse_episodes"]

_INDEX_FILES = {"MEMORY.md", "CLAUDE.md"}


class ClaudeAdapter:
    """Maps a set of Claude memory files onto portable episodes."""

    @staticmethod
    def parse_episodes(files: Any) -> list[PortableEpisode]:
        episodes: list[PortableEpisode] = []
        for path, content in _iter_files(files):
            ep = _map_file(path, content)
            if ep is not None:
                episodes.append(ep)
        return episodes


def _iter_files(files: Any):
    """Yield (path, content) from any accepted input shape."""
    if isinstance(files, dict):
        for path, content in files.items():
            if isinstance(path, str) and isinstance(content, str):
                yield path, content
        return
    if isinstance(files, (list, tuple)):
        for f in files:
            if isinstance(f, dict):
                path = _first_str(f.get("path"), f.get("name")) or ""
                content = _first_str(f.get("content"), f.get("text"), f.get("body"))
                if content is not None:
                    yield path, content
            elif isinstance(f, (list, tuple)) and len(f) == 2 and isinstance(f[1], str):
                yield (f[0] if isinstance(f[0], str) else ""), f[1]


def _map_file(path: str, content: str) -> PortableEpisode | None:
    frontmatter, body = _split_frontmatter(content)
    text = (body or content).strip()
    if not text:
        return None

    base = os.path.basename(path) if path else ""
    name = frontmatter.get("name") or (base[:-3] if base.endswith(".md") else base) or None
    description = frontmatter.get("description")
    ctype = frontmatter.get("metadata.type") or frontmatter.get("type")

    # Summary: the description, else the first non-empty line, else the name.
    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    summary = (description or first_line or name or "")[:120]

    meta: dict[str, str] = {}
    _put(meta, "claude_path", path or None)
    _put(meta, "claude_name", name)
    _put(meta, "claude_type", ctype)
    _put(meta, "claude_description", description)
    if base in _INDEX_FILES:
        meta["claude_role"] = "index"

    now = datetime.now(timezone.utc)
    return PortableEpisode(
        id=name or (base[:-3] if base.endswith(".md") else base) or ("ep_" + uuid.uuid4().hex[:16]),
        event_time=now,
        mention_time=now,
        ingestion_time=now,
        source_type="note",
        source_id=path or None,
        actors=[],
        summary=summary,
        details=text,
        sensitivity="low",
        deleted_at=None,
        metadata=meta,
        context_id=None,
        categories=[ctype] if ctype else [],
        importance=0.5,
        confidence=0.7,
        lifecycle_state="HOT",
        extraction_state="done",
        last_accessed=None,
        access_count=0,
        pinned=False,
        expiration_date=None,
        vault_refs=[],
        speaker=None,
    )


def _split_frontmatter(content: str) -> tuple[dict[str, str], str]:
    """Parse a leading ``---`` YAML frontmatter block into a flat dict (nested keys as
    ``parent.child``) + the remaining body. Returns ({}, content) when there is none.

    A minimal, stdlib-only parser for the ``key: value`` subset the memory format uses
    (Claude leaves the format to the host; the core stays dependency-free). Anything it
    can't parse is left in the body, never dropped.
    """
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, content
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, content

    fm: dict[str, str] = {}
    parent: str | None = None
    for raw in lines[1:end]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indented = raw[:1] in (" ", "\t")
        key, sep, val = raw.strip().partition(":")
        if not sep:
            continue
        key, val = key.strip(), val.strip()
        if indented and parent is not None:
            fm[f"{parent}.{key}"] = val
        elif val == "":
            parent = key  # a nested block follows
        else:
            fm[key] = val
            parent = None
    return fm, "\n".join(lines[end + 1:])


def _first_str(*values: Any) -> str | None:
    for v in values:
        if isinstance(v, str):
            return v
    return None


def _put(meta: dict[str, str], key: str, value: str | None) -> None:
    if value:
        meta[key] = value


parse_episodes = ClaudeAdapter.parse_episodes
