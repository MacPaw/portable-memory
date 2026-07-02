"""mem0 (https://github.com/mem0ai/mem0) ingest adapter.

Mirrors the Swift ``Mem0Adapter`` (Sources/PortableMemory/Adapters/Mem0Adapter.swift):
maps a mem0 export — a bare JSON array, or ``{"results":[...]}`` / ``{"memories":[...]}``
/ ``{"data":[...]}`` (the platform's paginated envelope also wraps ``results``) — onto
portable episodes. The format is a superset container, so whatever mem0 models that the
portable schema doesn't is preserved in ``metadata`` (namespaced ``mem0_*``) rather than
dropped; a later ``.mem`` export stays lossless. That includes a generic sweep of any
top-level key the mapping doesn't recognize (``score``, ``immutable``, ``memory_type``,
future platform fields, …).

mem0's promoted per-memory keys (OSS ``promoted_payload_keys``) are ``user_id``,
``agent_id``, ``run_id``, ``actor_id``, ``role``, ``attributed_to``, and
``expiration_date`` — all read here; ``expiration_date`` (normalized ``YYYY-MM-DD``)
additionally maps onto the episode's own ``expiration_date``. Graph ``relations``
(returned alongside ``results`` when graph memory is enabled) are NOT mapped in v1 —
adapters return episodes only; entity/edge promotion is a possible follow-up.

Adapters are pure: they take foreign bytes/JSON and return ``list[PortableEpisode]``
that a host then imports. There is no host, store, or I/O here.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from .._codec import canonical_json, parse_timestamp
from ..records import PortableEpisode

__all__ = ["Mem0Adapter", "parse_episodes"]


class Mem0Adapter:
    """Maps a mem0 export onto portable episodes.

    Missing/extra fields are handled gracefully; the original ``id``, ``hash``, role,
    and the various actor ids are preserved into episode ``metadata``.
    """

    @staticmethod
    def parse_episodes(data: bytes | str | dict) -> list[PortableEpisode]:
        """Parse a mem0 export into portable episodes.

        Accepts the already-decoded ``dict`` (or ``list``) as well as raw ``bytes`` /
        ``str`` JSON — the Swift API takes ``Data`` only, but Python callers routinely
        hold a parsed object, so we accept both without changing the mapping.
        """
        if isinstance(data, (bytes, bytearray, str)):
            root: Any = json.loads(data)
        else:
            root = data

        # A bare array, or one of the known envelope keys wrapping the array. Anything
        # else (or a missing/mistyped envelope) yields no items rather than raising —
        # mirrors the Swift adapter's tolerant shape handling.
        if isinstance(root, list):
            items = root
        elif isinstance(root, dict):
            items = (
                _as_object_list(root.get("results"))
                or _as_object_list(root.get("memories"))
                or _as_object_list(root.get("data"))
            )
        else:
            items = []

        # Swift builds the ISO-8601 parsers once per call for large exports; the
        # foundation's ``parse_timestamp`` is cheap, so we just wrap it in a lenient
        # closure that returns ``None`` for missing/unparseable input (Swift returns nil
        # from the failed-both-formatters path, which the call sites already tolerate).
        def parse(s: Any) -> datetime | None:
            if not isinstance(s, str) or not s:
                return None
            try:
                return parse_timestamp(s)
            except ValueError:
                return None

        episodes: list[PortableEpisode] = []
        for item in items:
            if not isinstance(item, dict):
                continue  # compactMap drops non-object entries
            ep = _map_one(item, parse)
            if ep is not None:
                episodes.append(ep)
        return episodes


def _as_object_list(value: Any) -> list[dict]:
    """Return ``value`` when it's a list of dicts, else ``[]`` (mirrors the Swift
    ``as? [[String: Any]]`` casts, which fail-to-nil on a mistyped envelope)."""
    if isinstance(value, list) and all(isinstance(e, dict) for e in value):
        return value
    return []


#: Top-level mem0 keys the mapping reads explicitly. Anything else is swept into
#: ``mem0_<key>`` metadata so no field a mem0 version emits is ever dropped.
_HANDLED_KEYS = frozenset({
    "memory", "text", "data", "role", "user_id", "agent_id", "actor_id", "run_id",
    "created_at", "updated_at", "metadata", "categories", "id", "hash",
    "attributed_to", "expiration_date",
})


def _map_one(
    o: dict,
    parse: Callable[[Any], "datetime | None"],
) -> PortableEpisode | None:
    """Map one mem0 record onto a portable episode, or ``None`` when it carries no text."""
    text = _first_str(o.get("memory"), o.get("text"), o.get("data")) or ""
    if not text.strip():
        return None  # nothing to remember

    role = _opt_str(o.get("role"))
    user_id = _opt_str(o.get("user_id"))
    agent_id = _opt_str(o.get("agent_id"))
    actor_id = _opt_str(o.get("actor_id"))
    run_id = _opt_str(o.get("run_id"))

    created = parse(o.get("created_at")) or datetime.now(timezone.utc)
    updated = parse(o.get("updated_at"))
    # mem0 normalizes expiration_date to date-only "YYYY-MM-DD"; the lenient parser
    # accepts it (midnight UTC). The raw string is also preserved in metadata below.
    expiration = parse(o.get("expiration_date"))

    # Actors in mem0's own precedence: user, then agent, then explicit actor. Only
    # non-empty ids are carried.
    actors = [a for a in (user_id, agent_id, actor_id) if a]

    # Foreign metadata first (stringified), then mem0 provenance overlaid. Provenance
    # keys only land when the value is a non-empty string, matching Swift.
    meta: dict[str, str] = {}
    raw_meta = o.get("metadata")
    if isinstance(raw_meta, dict):
        for k, v in raw_meta.items():
            meta[k] = _stringify(v)
    provenance = {
        "mem0_id": o.get("id"),
        "mem0_hash": o.get("hash"),
        "mem0_role": role,
        "mem0_user_id": user_id,
        "mem0_agent_id": agent_id,
        "mem0_actor_id": actor_id,
        "mem0_run_id": run_id,
        "mem0_created_at": o.get("created_at"),
        "mem0_updated_at": o.get("updated_at"),
        "mem0_attributed_to": o.get("attributed_to"),
        "mem0_expiration_date": o.get("expiration_date"),
    }
    for k, v in provenance.items():
        if isinstance(v, str) and v:
            meta[k] = v
    # Lossless sweep: any top-level key the mapping doesn't recognize (score, immutable,
    # memory_type, future platform fields, ...) is preserved as mem0_<key>. Nulls are
    # skipped — mem0 emits e.g. "expiration_date": null. setdefault so user metadata or
    # provenance that already claimed a key is never overwritten.
    for k, v in o.items():
        if k not in _HANDLED_KEYS and v is not None:
            meta.setdefault(f"mem0_{k}", _stringify(v))

    categories = [c for c in o.get("categories", []) if isinstance(c, str)]

    raw_id = _opt_str(o.get("id"))
    episode_id = raw_id or ("ep_" + uuid.uuid4().hex[:16])

    return PortableEpisode(
        id=episode_id,
        event_time=created,
        mention_time=updated or created,
        ingestion_time=created,
        # A message with a role came from a conversation; anything else is free text.
        source_type="chat" if role is not None else "text",
        source_id=raw_id,
        actors=actors,
        summary=text[:120],
        details=text,
        sensitivity="low",
        deleted_at=None,
        metadata=meta,
        context_id=run_id or None,
        categories=categories,
        importance=0.5,
        confidence=0.7,
        lifecycle_state="HOT",
        extraction_state="done",
        last_accessed=None,
        access_count=0,
        pinned=False,
        expiration_date=expiration,
        vault_refs=[],
        # Only chat-shaped roles map to a speaker; a bare "role" like "system" does not.
        speaker=role if role in ("user", "assistant") else None,
    )


def _first_str(*values: Any) -> str | None:
    """First value that is a ``str`` (mirrors Swift's ``as? String`` cast chain)."""
    for v in values:
        if isinstance(v, str):
            return v
    return None


def _opt_str(value: Any) -> str | None:
    """A ``str`` value, or ``None`` (Swift ``o[k] as? String``)."""
    return value if isinstance(value, str) else None


def _stringify(v: Any) -> str:
    """Render a metadata value as a string, mirroring Swift's ``stringify``.

    - ``str`` passes through.
    - ``bool`` becomes ``"1"``/``"0"`` — ``JSONSerialization`` decodes JSON booleans to
      ``NSNumber``, whose ``stringValue`` is ``"1"``/``"0"``. Checked before ``int``
      because ``bool`` is an ``int`` subclass in Python.
    - other numbers use their string form (``NSNumber.stringValue``).
    - containers use canonical JSON (Swift uses ``JSONSerialization`` with sorted keys;
      the foundation's ``canonical_json`` is the byte-compatible equivalent).
    """
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        # ``canonical_json`` yields the shortest round-tripping form, matching Swift's
        # ``NSNumber.stringValue`` for the numeric cases mem0 produces.
        return canonical_json(v)
    if isinstance(v, (dict, list)):
        return canonical_json(v)
    return str(v)


#: Module-level alias so callers can ``from portable_memory.adapters.mem0 import
#: parse_episodes`` without going through the class.
parse_episodes = Mem0Adapter.parse_episodes
