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


# Integral doubles below this bound serialize as plain integers ("1", not "1.0" —
# spec §1.1); at/above it both reference encoders switch to exponent form ("1e+16"),
# which Python's repr already produces. Probed against the Swift encoder: the two
# agree byte-for-byte on either side of this boundary.
_INTEGRAL_FLOAT_BOUND = 1e16


def _canon_numbers(obj: Any) -> Any:
    """Normalize floats to the canonical number form (spec §1.1) before dumping.

    ``json.dumps`` renders ``1.0`` as ``"1.0"``, but Canonical JSON (ECMAScript /
    JCS shortest-round-trip rule) requires integral values to emit with no decimal
    point — ``"1"``. Convert integral floats (including ``-0.0`` → ``0``) to ``int``;
    ``bool`` is untouched (it is an ``int`` subclass, never a ``float``).
    """
    if isinstance(obj, float):
        if obj.is_integer() and abs(obj) < _INTEGRAL_FLOAT_BOUND:
            return int(obj)
        return obj
    if isinstance(obj, dict):
        return {k: _canon_numbers(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_canon_numbers(v) for v in obj]
    return obj


def canonical_json(obj: Any) -> str:
    """Serialize one value to a single canonical JSON line (no trailing newline)."""
    # sort_keys -> sorted keys; separators -> no whitespace; ensure_ascii=False -> raw
    # UTF-8 (and Python never escapes '/'); floats use repr = shortest round-trip;
    # allow_nan=False -> NaN/Infinity raise instead of emitting invalid RFC 8259 JSON.
    return json.dumps(_canon_numbers(obj), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


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
        if not isinstance(value, str):
            raise TypeError(f"expected RFC 3339 string, got {type(value).__name__}")
        return parse_timestamp(value)
    if isinstance(inner, type) and issubclass(inner, Enum):
        return inner(value)
    if is_dataclass(inner):
        return from_wire(inner, value)
    if origin in (list, tuple):
        if not isinstance(value, list):
            raise TypeError(f"expected array, got {type(value).__name__}")
        args = get_args(inner)
        elem = args[0] if args else Any
        return [_decode_value(v, elem) for v in value]
    if origin is dict:
        if not isinstance(value, dict):
            raise TypeError(f"expected object, got {type(value).__name__}")
        args = get_args(inner)
        val_hint = args[1] if len(args) == 2 else Any
        return {k: _decode_value(v, val_hint) for k, v in value.items()}
    # Strict scalars — a wrong-typed field must fail the decode (as Swift's Codable
    # does), not be silently absorbed and re-emitted through the canonical exporter.
    if inner is str:
        if not isinstance(value, str):
            raise TypeError(f"expected string, got {type(value).__name__}")
        return value
    if inner is bool:
        if not isinstance(value, bool):
            raise TypeError(f"expected boolean, got {type(value).__name__}")
        return value
    if inner is int:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"expected integer, got {type(value).__name__}")
        # Integral floats are accepted for integer fields (Swift's decoder does the
        # same): canonical form writes 2.0 as "2", so a reader must take "2.0" too.
        if isinstance(value, float):
            if not value.is_integer():
                raise TypeError("expected integer, got non-integral number")
            return int(value)
        return value
    if inner is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"expected number, got {type(value).__name__}")
        # Canonical form writes 1.0 as "1", so integer tokens must decode into
        # float fields.
        return float(value)
    return value


def from_wire(cls: type, data: dict) -> Any:
    """Wire dict -> dataclass. Absent keys fall back to the field default."""
    hints = get_type_hints(cls)
    kwargs = {}
    for f in fields(cls):
        key = _json_key(f)
        if key in data and data[key] is not None:
            try:
                kwargs[f.name] = _decode_value(data[key], hints[f.name])
            except (TypeError, ValueError) as exc:
                raise type(exc)(f"{cls.__name__}.{key}: {exc}") from exc
    return cls(**kwargs)


def to_line(obj: Any) -> str:
    """Dataclass (or plain value) -> one canonical JSON line."""
    return canonical_json(to_wire(obj) if is_dataclass(obj) else obj)
