"""Engram (PLUR) ingest adapter — ``engrams.yaml`` / ``episodes.yaml`` ↔ portable episodes.

The Engram Specification (plur.ai/spec.html, v2.1, Apache-2.0) models one atomic unit of
learned knowledge per *engram*: a ``statement`` with ``type`` (behavioral / terminological /
procedural / architectural), ``scope``, ``status``, tags and domain, an ``activation`` block
(retrieval/storage strength, access frequency, last access), ``temporal`` validity,
``episodic`` weight/confidence, entities, associations, provenance, and open
``structured_data``. Engrams live in YAML files — a bare list per the spec, or wrapped in an
``engrams:`` key as PLUR's own pack files are written. Timestamped events live in a sibling
``episodes.yaml`` (``id``, ``timestamp``, ``summary``, ``agent``, ``channel``, ``session_id``).

Engrams are complementary to Portable Memory, not competing: they describe *what an agent
learned*; a ``.mem`` bundle gives that knowledge checksums, signatures, cross-vendor merge,
and provable deletion. This adapter is the bridge in both directions:

* :meth:`EngramAdapter.parse_episodes` maps each engram onto one portable episode — the
  statement is the episode text; ``temporal.learned_at`` (else ``created_at``) is the event
  time; ``activation`` feeds ``last_accessed`` / ``access_count`` / ``importance``;
  ``episodic.confidence`` (1–10) becomes ``confidence``; ``tags`` become categories; ``scope``
  becomes the context id; ``temporal.valid_until`` the expiration; ``pinned`` is pinned. PLUR
  episodes map onto event episodes (``agent`` → speaker, ``session_id`` → context id).
  **Every** top-level key is preserved verbatim as ``metadata["engram_<key>"]`` — strings as
  they are, everything else as canonical JSON — so nothing is lost.
* :meth:`EngramAdapter.render_yaml` is the reverse: episodes → spec-shaped YAML. Episodes
  that came from engrams are restored exactly; other episodes are synthesized into valid
  engrams (required fields filled with documented defaults).

Input is YAML or JSON text (or already-parsed data). The YAML reader is the standard-library
subset in :mod:`portable_memory._yaml`; both reference SDKs share the same rules and the
fixture in ``Conformance/fixtures/engram/`` pins byte-identical output.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from .._codec import canonical_json, format_timestamp
from .._yaml import load_yaml
from ..hashing import sha256_hex_str
from ..records import PortableEpisode
from .transfer import _DIGITS, _is_iso_date, _ymd

__all__ = ["EngramAdapter", "parse_episodes", "render_yaml"]

_META_PREFIX = "engram_"
_RECORD_KEY = "engram_record"

#: status → lifecycle_state, and back. ``candidate`` engrams are live knowledge too.
_LIFECYCLE = {"active": "HOT", "candidate": "HOT", "dormant": "COLD", "retired": "ARCHIVED"}
_STATUS = {"HOT": "active", "COLD": "dormant", "ARCHIVED": "retired"}

#: Engram keys whose values are strings in the spec — restored as-is (``"null"`` → null).
_STRING_KEYS = {
    "id", "status", "type", "scope", "visibility", "polarity", "created_at", "updated_at",
    "statement", "rationale", "source", "pack", "abstract", "derived_from", "domain",
    "claim_class", "content_hash", "commitment", "locked_at", "locked_reason", "summary",
}
#: Emission order for engram keys (the spec's order); anything else follows, sorted.
_KEY_ORDER = [
    "id", "version", "status", "type", "scope", "visibility", "polarity", "statement",
    "rationale", "contraindications", "tags", "domain", "consolidated", "pinned", "activation",
    "entities", "temporal", "episodic", "usage", "associations", "relations", "knowledge_type",
    "knowledge_anchors", "dual_coding", "source", "provenance", "attribution", "claim_class",
    "derivation_count", "pack", "abstract", "derived_from", "feedback_signals", "exchange",
    "structured_data", "insight", "commitment", "created_at", "updated_at", "summary",
    "content_hash",
]
_EPISODE_KEY_ORDER = ["id", "timestamp", "summary", "agent", "channel", "session_id"]


class EngramAdapter:
    """Maps Engram-spec YAML/JSON onto portable episodes, and back."""

    @staticmethod
    def parse_episodes(data: bytes | str | dict | list, *, now: datetime | None = None) -> list[PortableEpisode]:
        """Parse engrams (and PLUR episodes) into portable episodes.

        ``data`` is YAML or JSON text, or already-parsed content: a bare list of engrams,
        ``{"engrams": [...]}``, ``{"episodes": [...]}``, a single engram, or a list of
        documents. ``now`` is the ingestion instant (and the event time of undated
        entries); inject it for reproducible output.
        """
        root = _load(data)
        stamp = now or datetime.now(timezone.utc)
        engrams: list[dict] = []
        plur_episodes: list[dict] = []
        _collect(root, engrams, plur_episodes)
        out: list[PortableEpisode] = []
        seen: set[str] = set()
        for e in engrams:
            ep = _from_engram(e, stamp)
            if ep is not None and ep.id not in seen:
                seen.add(ep.id)
                out.append(ep)
        for p in plur_episodes:
            ep = _from_plur_episode(p, stamp)
            if ep is not None and ep.id not in seen:
                seen.add(ep.id)
                out.append(ep)
        return out

    @staticmethod
    def render_yaml(episodes: Iterable[PortableEpisode], *, kind: str = "engrams", wrapped: bool = False) -> str:
        """Render episodes as Engram-spec YAML.

        ``kind="engrams"`` (default) writes an ``engrams.yaml``: episodes that came from
        engrams are restored from their ``engram_*`` metadata exactly; any other episode is
        synthesized into a valid engram. ``kind="episodes"`` writes a PLUR ``episodes.yaml``.
        ``wrapped=True`` nests the list under an ``engrams:`` / ``episodes:`` key, as PLUR's
        pack files do; the default is the spec's bare-list root.
        """
        if kind not in ("engrams", "episodes"):
            raise ValueError(f"kind must be 'engrams' or 'episodes', not {kind!r}")
        items = [
            _episode_to_plur_episode(e) if kind == "episodes" else _episode_to_engram(e)
            for e in episodes
            if kind == "episodes" or e.metadata.get(_RECORD_KEY) != "episode"
        ]
        if wrapped:
            lines = [kind + ":"] + (_emit_sequence(items, 2) if items else ["  []"])
        else:
            lines = _emit_sequence(items, 0) if items else ["[]"]
        return "\n".join(lines) + "\n"


# ── Loading / collecting ──────────────────────────────────────────────────────────────

def _load(data: Any) -> Any:
    if isinstance(data, (bytes, bytearray)):
        data = bytes(data).decode("utf-8")
    if not isinstance(data, str):
        return data
    head = data.lstrip(" \t\r\n")
    if head[:1] in ("[", "{"):
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            pass
    return load_yaml(data)


def _collect(node: Any, engrams: list[dict], plur_episodes: list[dict]) -> None:
    if isinstance(node, list):
        for item in node:
            if isinstance(item, (list, dict)):
                _collect(item, engrams, plur_episodes)
        return
    if not isinstance(node, dict):
        return
    if isinstance(node.get("engrams"), list) or isinstance(node.get("episodes"), list):
        for e in node.get("engrams") or []:
            if isinstance(e, dict):
                engrams.append(e)
        for p in node.get("episodes") or []:
            if isinstance(p, dict):
                plur_episodes.append(p)
        return
    if "statement" in node:
        engrams.append(node)
    elif "summary" in node and ("timestamp" in node or "agent" in node or "session_id" in node):
        plur_episodes.append(node)


# ── Engram → episode ──────────────────────────────────────────────────────────────────

def _from_engram(e: dict, now: datetime) -> PortableEpisode | None:
    statement = e.get("statement")
    statement = statement if isinstance(statement, str) else ("" if statement is None else _stringify(statement))
    ident = e.get("id")
    if not (isinstance(ident, str) and ident):
        if not statement.strip():
            return None
        ident = "eng_" + sha256_hex_str(statement)[:24]
    temporal = e.get("temporal") if isinstance(e.get("temporal"), dict) else {}
    activation = e.get("activation") if isinstance(e.get("activation"), dict) else {}
    episodic = e.get("episodic") if isinstance(e.get("episodic"), dict) else {}

    event_time = _date(temporal.get("learned_at")) or _date(e.get("created_at")) or now
    mention_time = _date(e.get("updated_at")) or event_time
    confidence = _int(episodic.get("confidence"))
    tags = e.get("tags")
    status = e.get("status") if isinstance(e.get("status"), str) else None
    summary = e.get("summary") if isinstance(e.get("summary"), str) else None

    meta: dict[str, str] = {_RECORD_KEY: "engram"}
    for key, value in e.items():
        if key in ("id", "statement"):
            continue
        meta[_META_PREFIX + key] = _stringify(value)

    return PortableEpisode(
        id=ident,
        event_time=event_time,
        mention_time=mention_time,
        ingestion_time=now,
        source_type="note",
        source_id=None,
        actors=[],
        summary=(summary or statement.strip().split("\n", 1)[0])[:120],
        details=statement,
        sensitivity="low",
        deleted_at=None,
        metadata=meta,
        context_id=e.get("scope") if isinstance(e.get("scope"), str) and e.get("scope") else None,
        categories=[t for t in tags if isinstance(t, str)] if isinstance(tags, list) else [],
        importance=_unit(activation.get("retrieval_strength"), 0.5),
        confidence=(confidence / 10) if confidence is not None and 1 <= confidence <= 10 else 0.7,
        lifecycle_state=_LIFECYCLE.get(status or "", "HOT"),
        extraction_state="done",
        last_accessed=_date(activation.get("last_accessed")),
        access_count=max(_int(activation.get("frequency")) or 0, 0),
        pinned=e.get("pinned") is True,
        expiration_date=_date(temporal.get("valid_until")),
        vault_refs=[],
        speaker=None,
    )


def _from_plur_episode(p: dict, now: datetime) -> PortableEpisode | None:
    summary = p.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return None
    ts = p.get("timestamp") if isinstance(p.get("timestamp"), str) else ""
    ident = p.get("id")
    if not (isinstance(ident, str) and ident):
        ident = "epx_" + sha256_hex_str(ts + "\n" + summary)[:24]
    when = _date(ts) or now
    meta: dict[str, str] = {_RECORD_KEY: "episode"}
    for key, value in p.items():
        if key in ("id", "summary"):
            continue
        meta[_META_PREFIX + key] = _stringify(value)
    agent = p.get("agent") if isinstance(p.get("agent"), str) and p.get("agent") else None
    session = p.get("session_id") if isinstance(p.get("session_id"), str) and p.get("session_id") else None
    return PortableEpisode(
        id=ident,
        event_time=when,
        mention_time=when,
        ingestion_time=now,
        source_type="event",
        source_id=None,
        actors=[],
        summary=summary.strip().split("\n", 1)[0][:120],
        details=summary,
        sensitivity="low",
        deleted_at=None,
        metadata=meta,
        context_id=session,
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
        speaker=agent,
    )


# ── Episode → engram / PLUR episode ───────────────────────────────────────────────────

def _restored(e: PortableEpisode) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in e.metadata.items():
        if key == _RECORD_KEY or not key.startswith(_META_PREFIX):
            continue
        out[key[len(_META_PREFIX):]] = _unstringify(key[len(_META_PREFIX):], value)
    return out


def _episode_to_engram(e: PortableEpisode) -> dict[str, Any]:
    obj = _restored(e) if e.metadata.get(_RECORD_KEY) == "engram" else {}
    obj["id"] = e.id
    obj["statement"] = e.details if e.details else e.summary
    if e.metadata.get(_RECORD_KEY) == "engram":
        return obj
    # Synthesize a valid engram (required: id, status, type, scope, statement).
    obj.setdefault("version", 2)
    obj.setdefault("status", _STATUS.get(e.lifecycle_state, "active"))
    obj.setdefault("type", "terminological")
    obj.setdefault("scope", e.context_id or "global")
    if e.summary and e.summary != obj["statement"].strip().split("\n", 1)[0][:120]:
        obj.setdefault("summary", e.summary)
    if e.categories:
        obj.setdefault("tags", list(e.categories))
    if e.pinned:
        obj["pinned"] = True
    activation: dict[str, Any] = {
        "retrieval_strength": e.importance,
        "storage_strength": e.importance,
        "frequency": e.access_count,
    }
    if e.last_accessed is not None:
        activation["last_accessed"] = format_timestamp(e.last_accessed)[:10]
    obj["activation"] = activation
    temporal: dict[str, Any] = {"learned_at": format_timestamp(e.event_time)[:10]}
    if e.expiration_date is not None:
        temporal["valid_until"] = format_timestamp(e.expiration_date)[:10]
    obj["temporal"] = temporal
    obj.setdefault("source", "portable-memory")
    return obj


def _episode_to_plur_episode(e: PortableEpisode) -> dict[str, Any]:
    obj = _restored(e) if e.metadata.get(_RECORD_KEY) == "episode" else {}
    obj["id"] = e.id
    obj["summary"] = e.details if e.details else e.summary
    obj.setdefault("timestamp", format_timestamp(e.event_time))
    if e.speaker:
        obj.setdefault("agent", e.speaker)
    if e.context_id:
        obj.setdefault("session_id", e.context_id)
    return obj


def _unstringify(key: str, s: str) -> Any:
    if key in _STRING_KEYS:
        return None if s == "null" else s
    if key == "record":
        return s
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return s


# ── YAML emitter (deterministic, spec-shaped) ─────────────────────────────────────────

def _ordered_keys(obj: dict[str, Any], order: list[str]) -> list[str]:
    known = [k for k in order if k in obj]
    return known + sorted(k for k in obj if k not in order)


def _emit_sequence(items: list[Any], indent: int) -> list[str]:
    pad = " " * indent
    out: list[str] = []
    for item in items:
        if isinstance(item, dict):
            body = _emit_mapping(item, indent + 2)
            if body:
                out.append(pad + "- " + body[0][indent + 2:])
                out.extend(body[1:])
            else:
                out.append(pad + "- {}")
        elif isinstance(item, list):
            if _all_scalars(item):
                out.append(pad + "- " + _flow_list(item))
            else:
                out.append(pad + "-")
                out.extend(_emit_sequence(item, indent + 2))
        else:
            out.extend(_emit_scalar_lines(pad + "- ", item, indent + 2))
    return out


def _emit_mapping(obj: dict[str, Any], indent: int) -> list[str]:
    pad = " " * indent
    out: list[str] = []
    order = _EPISODE_KEY_ORDER if "timestamp" in obj and "statement" not in obj else _KEY_ORDER
    for key in _ordered_keys(obj, order):
        value = obj[key]
        head = pad + _emit_key(key) + ":"
        if isinstance(value, dict):
            if value:
                out.append(head)
                out.extend(_emit_mapping(value, indent + 2))
            else:
                out.append(head + " {}")
        elif isinstance(value, list):
            if not value:
                out.append(head + " []")
            elif _all_scalars(value):
                out.append(head + " " + _flow_list(value))
            else:
                out.append(head)
                out.extend(_emit_sequence(value, indent + 2))
        else:
            out.extend(_emit_scalar_lines(head + " ", value, indent + 2))
    return out


def _emit_scalar_lines(prefix: str, value: Any, indent: int) -> list[str]:
    """``prefix`` + scalar; multi-line strings become literal block scalars."""
    if isinstance(value, str) and "\n" in value and _blockable(value):
        body = value.rstrip("\n")
        trailing = len(value) - len(body)
        indicator = "|-" if trailing == 0 else ("|" if trailing == 1 else "|+")
        pad = " " * indent
        lines = [prefix.rstrip(" ") + " " + indicator]
        lines.extend((pad + ln) if ln else "" for ln in body.split("\n"))
        lines.extend("" for _ in range(trailing - 1))
        return lines
    return [prefix + _emit_scalar(value)]


def _blockable(s: str) -> bool:
    return not s.startswith((" ", "\t")) and not any(ln.startswith((" ", "\t")) for ln in s.split("\n"))


def _all_scalars(items: list[Any]) -> bool:
    return all(not isinstance(v, (dict, list)) and not (isinstance(v, str) and "\n" in v) for v in items)


def _flow_list(items: list[Any]) -> str:
    return "[" + ", ".join(_emit_scalar(v) for v in items) + "]"


def _emit_key(key: str) -> str:
    return key if key and all(ch.isalnum() or ch in "_-./" for ch in key) and key[0] not in "-." else _quote(key)


def _emit_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return canonical_json(value)
    if isinstance(value, str):
        return _quote(value)
    return _quote(canonical_json(value))


def _quote(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


# ── Helpers ───────────────────────────────────────────────────────────────────────────

def _stringify(value: Any) -> str:
    """Strings pass through; everything else is canonical JSON (bools as ``true``/``false``,
    ``null``, numbers in shortest form, containers with sorted keys) — reversible exactly."""
    return value if isinstance(value, str) else canonical_json(value)


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value) if float(value).is_integer() else None


def _unit(value: Any, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return min(max(float(value), 0.0), 1.0)


def _date(value: Any) -> datetime | None:
    """``YYYY-MM-DD`` or RFC 3339 (``T`` or space, optional fraction, ``Z`` or ``±HH:MM``) → UTC."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if len(s) == 10 and _is_iso_date(s):
        return _ymd(int(s[:4]), int(s[5:7]), int(s[8:10]))
    if (
        len(s) >= 19 and _is_iso_date(s[:10]) and s[10] in "T " and s[13] == ":" and s[16] == ":"
        and all(s[i] in _DIGITS for i in (11, 12, 14, 15, 17, 18))
    ):
        base = _ymd(int(s[:4]), int(s[5:7]), int(s[8:10]), int(s[11:13]), int(s[14:16]), int(s[17:19]))
        if base is None:
            return None
        rest = s[19:]
        if rest.startswith("."):
            k = 1
            while k < len(rest) and rest[k] in _DIGITS:
                k += 1
            rest = rest[k:]
        if rest in ("", "Z", "z"):
            return base
        if len(rest) == 6 and rest[0] in "+-" and rest[3] == ":" and all(rest[i] in _DIGITS for i in (1, 2, 4, 5)):
            minutes = int(rest[1:3]) * 60 + int(rest[4:6])
            return base - timedelta(minutes=minutes) if rest[0] == "+" else base + timedelta(minutes=minutes)
    return None


parse_episodes = EngramAdapter.parse_episodes
render_yaml = EngramAdapter.render_yaml
