"""Canonical JSON + dataclass <-> wire-dict codec.

The canonical form is byte-identical to the Swift reference SDK's ``MemCodec`` (spec
§1.1): UTF-8, no BOM, object keys sorted recursively, no insignificant whitespace,
``/`` unescaped, non-ASCII emitted raw (not ``\\u``), shortest round-tripping numbers,
and whole-second UTC ``Z`` timestamps. That is what lets a bundle written by one
implementation validate (matching checksums) in the other.
"""
from __future__ import annotations

import json
import types
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Union, get_args, get_origin, get_type_hints


def canonical_json(obj: Any) -> str:
    """Serialize one value to a single canonical JSON line (no trailing newline)."""
    # sort_keys -> sorted keys; separators -> no whitespace; ensure_ascii=False -> raw
    # UTF-8 (and Python never escapes '/'); floats use repr = shortest round-trip.
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def format_timestamp(dt: datetime) -> str:
    """Whole-second UTC RFC 3339 with a literal ``Z`` (canonical output, spec §1.1)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_timestamp(s: str) -> datetime:
    """Lenient RFC 3339 parse: accepts ``Z``, numeric offsets, and fractional seconds.

    Canonical output is always whole-second UTC, but a foreign bundle may emit other
    forms — a reader accepts them and re-emits canonically on the next export.
    """
    raw = s
    if s[-1:] in ("Z", "z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise ValueError(f"not a valid RFC 3339 timestamp: {raw}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _json_key(field) -> str:
    return field.metadata.get("json", field.name)


def _unwrap_optional(hint: Any) -> Any:
    """T from Optional[T] / T | None; hint unchanged otherwise."""
    origin = get_origin(hint)
    if origin is Union or origin is types.UnionType:
        non_none = [a for a in get_args(hint) if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return hint


def _encode_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime):
        return format_timestamp(value)
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return to_wire(value)
    if isinstance(value, (list, tuple)):
        return [_encode_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _encode_value(v) for k, v in value.items()}
    return value  # str / int / float / bool


def to_wire(obj: Any) -> dict:
    """Dataclass -> wire dict (camelCase keys; absent optionals omitted, never null)."""
    out: dict[str, Any] = {}
    for f in fields(obj):
        val = getattr(obj, f.name)
        if val is None:
            continue
        out[_json_key(f)] = _encode_value(val)
    return out


def _decode_value(value: Any, hint: Any) -> Any:
    inner = _unwrap_optional(hint)
    origin = get_origin(inner)
    if inner is datetime:
        return parse_timestamp(value)
    if isinstance(inner, type) and issubclass(inner, Enum):
        return inner(value)
    if is_dataclass(inner):
        return from_wire(inner, value)
    if origin in (list, tuple):
        args = get_args(inner)
        elem = args[0] if args else Any
        return [_decode_value(v, elem) for v in value]
    if origin is dict:
        return dict(value)
    return value


def from_wire(cls: type, data: dict) -> Any:
    """Wire dict -> dataclass. Absent keys fall back to the field default."""
    hints = get_type_hints(cls)
    kwargs = {}
    for f in fields(cls):
        key = _json_key(f)
        if key in data and data[key] is not None:
            kwargs[f.name] = _decode_value(data[key], hints[f.name])
    return cls(**kwargs)


def to_line(obj: Any) -> str:
    """Dataclass (or plain value) -> one canonical JSON line."""
    return canonical_json(to_wire(obj) if is_dataclass(obj) else obj)
