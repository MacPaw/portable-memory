"""OpenAI / ChatGPT ingest adapter.

Maps a ChatGPT data export onto portable episodes. The native export
(Settings → Data controls → Export) delivers ``conversations.json``: an array of
conversation objects, each with a ``mapping`` tree of message nodes. Each visible
user/assistant turn with text becomes one episode; the conversation id/title, message id,
role, model, and timestamps are preserved into ``metadata`` (namespaced ``openai_*``) so a
later ``.mem`` export stays lossless.

Accepted shapes (tolerant, like the mem0 adapter):
  * the full export — a JSON array of conversation objects (each has ``mapping``);
  * a single conversation object (has ``mapping``);
  * ``{"conversations": [...]}``;
  * a fallback "saved memories" list — bare strings, or objects with
    ``memory`` / ``content`` / ``text`` and no ``mapping`` — each mapped to a note episode.

Adapters are pure: foreign JSON in, ``list[PortableEpisode]`` out. No host, store, or I/O.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from .._codec import format_timestamp
from ..records import PortableEpisode

__all__ = ["OpenAIAdapter", "parse_episodes"]

# Roles that carry user-facing memory. System prompts and tool plumbing are skipped.
_MEMORY_ROLES = {"user", "assistant"}


class OpenAIAdapter:
    """Maps a ChatGPT export onto portable episodes."""

    @staticmethod
    def parse_episodes(data: bytes | str | dict | list) -> list[PortableEpisode]:
        root: Any = json.loads(data) if isinstance(data, (bytes, bytearray, str)) else data

        conversations = _conversations(root)
        if conversations is not None:
            episodes: list[PortableEpisode] = []
            for conv in conversations:
                episodes.extend(_episodes_from_conversation(conv))
            return episodes

        # Fallback: a flat list of "saved memories".
        return [ep for ep in (_episode_from_memory(m) for m in _memory_items(root)) if ep]


def _conversations(root: Any) -> list[dict] | None:
    """The conversation objects in `root`, or None if this isn't a conversations export."""
    if isinstance(root, dict):
        if isinstance(root.get("mapping"), dict):
            return [root]
        if isinstance(root.get("conversations"), list):
            return [c for c in root["conversations"] if isinstance(c, dict) and isinstance(c.get("mapping"), dict)]
        return None
    if isinstance(root, list):
        convs = [c for c in root if isinstance(c, dict) and isinstance(c.get("mapping"), dict)]
        return convs or None
    return None


def _memory_items(root: Any) -> list[Any]:
    if isinstance(root, list):
        return root
    if isinstance(root, dict):
        for key in ("memories", "results", "data"):
            if isinstance(root.get(key), list):
                return root[key]
    return []


def _at(ts: Any) -> datetime | None:
    """A ChatGPT epoch-seconds float → aware UTC datetime, else None."""
    if isinstance(ts, (int, float)) and not isinstance(ts, bool):
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    return None


def _message_text(message: dict) -> str:
    """Concatenate the string parts of a message's content (skips non-text parts)."""
    content = message.get("content")
    if not isinstance(content, dict):
        return ""
    parts = content.get("parts")
    if isinstance(parts, list):
        return "\n".join(p for p in parts if isinstance(p, str)).strip()
    # Some content types carry text under a different key.
    text = content.get("text")
    return text.strip() if isinstance(text, str) else ""


def _episodes_from_conversation(conv: dict) -> list[PortableEpisode]:
    conv_id = _str(conv.get("conversation_id")) or _str(conv.get("id"))
    conv_title = _str(conv.get("title"))
    mapping = conv.get("mapping")
    if not isinstance(mapping, dict):
        return []

    rows: list[tuple[float, str, dict]] = []
    for node_key, node in mapping.items():
        if not isinstance(node, dict):
            continue
        message = node.get("message")
        if not isinstance(message, dict):
            continue
        author = message.get("author") if isinstance(message.get("author"), dict) else {}
        role = _str(author.get("role"))
        if role not in _MEMORY_ROLES:
            continue
        meta = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        if meta.get("is_visually_hidden_from_conversation") is True:
            continue
        if not _message_text(message):
            continue
        ct = message.get("create_time")
        # Sort by create_time; entries without one sort last, tie-broken by the mapping
        # node key — a deterministic order both reference SDKs reproduce (dictionaries
        # are unordered in Swift, so document order is not portable).
        sort_ts = float(ct) if isinstance(ct, (int, float)) and not isinstance(ct, bool) else float("inf")
        rows.append((sort_ts, str(node_key), message))

    rows.sort(key=lambda r: (r[0], r[1]))
    return [_episode_from_message(m, conv_id, conv_title) for _, _, m in rows]


def _episode_from_message(message: dict, conv_id: str | None, conv_title: str | None) -> PortableEpisode:
    text = _message_text(message)
    author = message.get("author") if isinstance(message.get("author"), dict) else {}
    role = _str(author.get("role"))
    msg_meta = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    created = _at(message.get("create_time"))
    updated = _at(message.get("update_time"))
    now = datetime.now(timezone.utc)
    msg_id = _str(message.get("id"))

    meta: dict[str, str] = {}
    _put(meta, "openai_conversation_id", conv_id)
    _put(meta, "openai_conversation_title", conv_title)
    _put(meta, "openai_message_id", msg_id)
    _put(meta, "openai_role", role)
    _put(meta, "openai_model", _str(msg_meta.get("model_slug")))
    recipient = _str(message.get("recipient"))
    if recipient and recipient != "all":
        _put(meta, "openai_recipient", recipient)
    if created:
        # Canonical whole-second UTC "Z" form — identical to what the Swift adapter
        # writes, so the same export maps to byte-identical metadata in both SDKs.
        _put(meta, "openai_create_time", format_timestamp(created))

    return PortableEpisode(
        id=msg_id or ("ep_" + uuid.uuid4().hex[:16]),
        event_time=created or now,
        mention_time=updated or created or now,
        ingestion_time=created or now,
        source_type="chat",
        source_id=msg_id,
        actors=[],
        summary=text[:120],
        details=text,
        sensitivity="low",
        deleted_at=None,
        metadata=meta,
        context_id=conv_id or None,
        categories=[],
        importance=0.5,
        confidence=0.7,
        lifecycle_state="HOT",
        extraction_state="done",
        last_accessed=None,
        access_count=0,
        pinned=False,
        expiration_date=None,
        vault_refs=[],
        speaker=role if role in _MEMORY_ROLES else None,
    )


def _episode_from_memory(item: Any) -> PortableEpisode | None:
    """A saved-memory entry (bare string or object) → a note episode."""
    if isinstance(item, str):
        text, mem_id = item, None
    elif isinstance(item, dict):
        text = _first_str(item.get("memory"), item.get("content"), item.get("text")) or ""
        mem_id = _str(item.get("id"))
    else:
        return None
    if not text.strip():
        return None
    now = datetime.now(timezone.utc)
    meta: dict[str, str] = {"openai_source": "memory"}
    _put(meta, "openai_memory_id", mem_id)
    return PortableEpisode(
        id=mem_id or ("ep_" + uuid.uuid4().hex[:16]),
        event_time=now, mention_time=now, ingestion_time=now,
        source_type="note", source_id=mem_id, actors=[],
        summary=text[:120], details=text, sensitivity="low", deleted_at=None,
        metadata=meta, context_id=None, categories=[], importance=0.5, confidence=0.7,
        lifecycle_state="HOT", extraction_state="done", last_accessed=None,
        access_count=0, pinned=False, expiration_date=None, vault_refs=[], speaker=None,
    )


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _first_str(*values: Any) -> str | None:
    for v in values:
        if isinstance(v, str):
            return v
    return None


def _put(meta: dict[str, str], key: str, value: str | None) -> None:
    if value:
        meta[key] = value


parse_episodes = OpenAIAdapter.parse_episodes
