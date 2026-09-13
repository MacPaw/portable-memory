"""Minimal YAML reader — the subset the Engram Specification and PLUR's files use.

The core stays standard-library only, so this is a small, tolerant, deterministic reader
for the YAML that memory tools actually write — not a general YAML 1.2 implementation:

* block mappings and block sequences (including a sequence at the same indent as its key,
  and ``- key: value`` items whose mapping starts inline);
* block scalars ``|``, ``|-``, ``|+``, ``>``, ``>-``, ``>+`` (literal / folded, chomping);
* single-line and multi-line flow collections ``[a, b]`` / ``{k: v}``;
* double-quoted (JSON escapes) and single-quoted strings; plain scalars typed by the YAML
  1.2 core schema (``null``/``~``, ``true``/``false``, integers, floats — dates stay
  strings); multi-line plain scalars;
* comments, and ``---`` / ``...`` document markers (a multi-document stream yields a list).

Anything outside the subset degrades to strings rather than raising. Mirrored
line-for-line by the Swift ``YAMLSubset`` so both SDKs read a file identically.
"""
from __future__ import annotations

from typing import Any

__all__ = ["load_yaml"]

_DIGITS = "0123456789"
_INT_MIN = -(2 ** 63)
_UINT_MAX = 2 ** 64 - 1


def load_yaml(text: str) -> Any:
    """Parse a YAML stream. One document → its value; several → a list of values."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    docs: list[Any] = []
    current: list[str] = []
    started = False
    for line in lines:
        c = _content(line)
        if not started and c.startswith("%"):
            continue  # a directive before the first document
        if c == "---" or c.startswith("--- "):
            if started or current:
                docs.append(_parse_document(current))
            current = []
            started = True
            rest = c[3:].strip(" \t")
            if rest:
                current.append(rest)
            continue
        if c == "...":
            docs.append(_parse_document(current))
            current = []
            started = False
            continue
        if c != "":
            started = True
        current.append(line)
    if current or not docs:
        docs.append(_parse_document(current))
    while len(docs) > 1 and docs[-1] is None:
        docs.pop()
    while len(docs) > 1 and docs[0] is None:
        docs.pop(0)
    return docs[0] if len(docs) == 1 else docs


# ── Lines ─────────────────────────────────────────────────────────────────────────────

def _indent(line: str) -> int:
    n = 0
    while n < len(line) and line[n] == " ":
        n += 1
    return n


def _opens_quote(line: str, idx: int) -> bool:
    return idx == 0 or line[idx - 1] in " \t:[{,"


#: Nesting deeper than this degrades to a string — keeps hostile input from exhausting the
#: stack (mirrored in Swift so both SDKs agree on where they give up).
_MAX_DEPTH = 64


def _strip_comment(line: str) -> str:
    in_single = in_double = False
    idx = 0
    while idx < len(line):
        ch = line[idx]
        if in_double:
            if ch == "\\":
                idx += 1
            elif ch == '"':
                in_double = False
        elif in_single:
            if ch == "'":
                if idx + 1 < len(line) and line[idx + 1] == "'":
                    idx += 1  # '' is an escaped quote, not the end of the string
                else:
                    in_single = False
        elif ch == '"' and _opens_quote(line, idx):
            in_double = True
        elif ch == "'" and _opens_quote(line, idx):
            in_single = True
        elif ch == "#" and (idx == 0 or line[idx - 1] in " \t"):
            return line[:idx]
        idx += 1
    return line


def _content(line: str) -> str:
    return _strip_comment(line).strip(" \t")


def _skip_blank(lines: list[str], i: int) -> int:
    while i < len(lines) and _content(lines[i]) == "":
        i += 1
    return i


def _is_seq_item(c: str) -> bool:
    return c == "-" or c.startswith("- ")


# ── Block structure ───────────────────────────────────────────────────────────────────

def _parse_document(lines: list[str]) -> Any:
    lines = list(lines)
    i = _skip_blank(lines, 0)
    if i >= len(lines):
        return None
    value, _ = _parse_block(lines, i, _indent(lines[i]))
    return value


def _parse_block(lines: list[str], i: int, indent: int, depth: int = 0) -> tuple[Any, int]:
    c = _content(lines[i])
    if depth > _MAX_DEPTH:
        return _scalar(c), i + 1
    if _is_seq_item(c):
        return _parse_sequence(lines, i, indent, depth)
    if _split_key(c) is not None:
        return _parse_mapping(lines, i, indent, depth)
    return _parse_inline_value(lines, i, indent - 1, c)


def _parse_sequence(lines: list[str], i: int, indent: int, depth: int = 0) -> tuple[list[Any], int]:
    items: list[Any] = []
    n = len(lines)
    while True:
        i = _skip_blank(lines, i)
        if i >= n:
            break
        ind, c = _indent(lines[i]), _content(lines[i])
        if ind < indent:
            break
        if ind > indent:
            i += 1  # a stray deeper line — tolerate and move on
            continue
        if not _is_seq_item(c):
            break
        if c == "-":
            j = _skip_blank(lines, i + 1)
            if j < n and _indent(lines[j]) > indent:
                value, i = _parse_block(lines, j, _indent(lines[j]), depth + 1)
            else:
                value, i = None, j
        else:
            rest = c[2:].lstrip(" \t")
            col = indent + (len(c) - len(rest))
            if _split_key(rest) is not None:
                lines[i] = " " * col + rest  # re-read the item as a mapping starting at `col`
                value, i = _parse_mapping(lines, i, col, depth + 1)
            else:
                value, i = _parse_inline_value(lines, i, indent, rest)
        items.append(value)
    return items, i


def _parse_mapping(lines: list[str], i: int, indent: int, depth: int = 0) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    n = len(lines)
    while True:
        i = _skip_blank(lines, i)
        if i >= n:
            break
        ind, c = _indent(lines[i]), _content(lines[i])
        if ind < indent:
            break
        if ind > indent:
            i += 1
            continue
        if _is_seq_item(c):
            break
        kv = _split_key(c)
        if kv is None:
            break
        key, rest = kv
        if rest == "":
            j = _skip_blank(lines, i + 1)
            if j < n and _indent(lines[j]) > indent:
                value, i = _parse_block(lines, j, _indent(lines[j]), depth + 1)
            elif j < n and _indent(lines[j]) == indent and _is_seq_item(_content(lines[j])):
                value, i = _parse_sequence(lines, j, indent, depth + 1)  # a sequence at the key's own indent
            else:
                value, i = None, j
        else:
            value, i = _parse_inline_value(lines, i, indent, rest)
        result[key] = value
    return result, i


def _split_key(c: str) -> tuple[str, str] | None:
    """``key: rest`` → (key, rest) when ``c`` is a mapping entry, else None."""
    if c == "" or c[0] in "[{":
        return None
    if c[0] in "\"'":
        key, pos = _read_quoted(c, 0)
        while pos < len(c) and c[pos] in " \t":
            pos += 1
        if pos < len(c) and c[pos] == ":" and (pos + 1 == len(c) or c[pos + 1] in " \t"):
            return key, c[pos + 1:].strip(" \t")
        return None
    for idx, ch in enumerate(c):
        if ch == ":" and (idx + 1 == len(c) or c[idx + 1] in " \t"):
            key = c[:idx].strip(" \t")
            return (key, c[idx + 1:].strip(" \t")) if key else None
    return None


# ── Values ────────────────────────────────────────────────────────────────────────────

def _is_block_indicator(rest: str) -> bool:
    return rest != "" and rest[0] in "|>" and all(ch in "+-" + _DIGITS for ch in rest[1:])


def _parse_inline_value(lines: list[str], i: int, indent: int, rest: str) -> tuple[Any, int]:
    n = len(lines)
    if _is_block_indicator(rest):
        return _parse_block_scalar(lines, i, indent, rest)
    if rest[0] in "[{":
        text, j = rest, i + 1
        while not _flow_balanced(text) and j < n:
            text += " " + _content(lines[j])
            j += 1
        value, _ = _parse_flow(text, 0)
        return value, j
    if rest[0] in "\"'":
        return _scalar(rest), i + 1
    text, j = rest, i + 1
    while j < n:
        cj = _content(lines[j])
        if cj == "" or _indent(lines[j]) <= indent or _is_seq_item(cj) or _split_key(cj) is not None:
            break
        text += " " + cj  # a plain scalar continued on a deeper line
        j += 1
    return _scalar(text), j


def _parse_block_scalar(lines: list[str], i: int, indent: int, indicator: str) -> tuple[str, int]:
    literal = indicator[0] == "|"
    chomp = "strip" if "-" in indicator else ("keep" if "+" in indicator else "clip")
    explicit = "".join(ch for ch in indicator[1:] if ch in _DIGITS)
    block_indent = indent + int(explicit) if explicit else None
    collected: list[str] = []
    j, n = i + 1, len(lines)
    while j < n:
        raw = lines[j]
        if raw.strip(" \t") == "":
            collected.append("")
            j += 1
            continue
        ind = _indent(raw)
        if block_indent is None:
            if ind <= indent:
                break
            block_indent = ind
        if ind < block_indent:
            break
        collected.append(raw[block_indent:])
        j += 1
    trailing = 0
    while collected and collected[-1] == "":
        collected.pop()
        trailing += 1
    if literal:
        body = "\n".join(collected)
    else:
        parts: list[str] = []
        for ln in collected:
            if ln == "":
                parts.append("\n")
            else:
                if parts and parts[-1] != "\n":
                    parts.append(" ")
                parts.append(ln)
        body = "".join(parts)
    if chomp == "strip":
        return body, j
    if chomp == "keep":
        return body + "\n" * (1 + trailing), j
    return (body + "\n") if body else "", j


def _flow_balanced(text: str) -> bool:
    depth = 0
    in_single = in_double = False
    idx = 0
    while idx < len(text):
        ch = text[idx]
        if in_double:
            if ch == "\\":
                idx += 1
            elif ch == '"':
                in_double = False
        elif in_single:
            if ch == "'":
                if idx + 1 < len(text) and text[idx + 1] == "'":
                    idx += 1
                else:
                    in_single = False
        elif ch == '"':
            in_double = True
        elif ch == "'":
            in_single = True
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        idx += 1
    return depth <= 0


def _ws(text: str, pos: int) -> int:
    while pos < len(text) and text[pos] in " \t\n":
        pos += 1
    return pos


def _parse_flow(text: str, pos: int, depth: int = 0) -> tuple[Any, int]:
    pos = _ws(text, pos)
    if pos >= len(text):
        return None, pos
    if depth > _MAX_DEPTH:
        return text[pos:].strip(" \t"), len(text)  # too deep — the rest is a string
    ch = text[pos]
    if ch == "[":
        items: list[Any] = []
        pos += 1
        while True:
            pos = _ws(text, pos)
            if pos >= len(text):
                return items, pos
            if text[pos] == "]":
                return items, pos + 1
            if text[pos] == ",":
                pos += 1
                continue
            value, pos = _parse_flow_value(text, pos, "]", depth)
            items.append(value)
    if ch == "{":
        obj: dict[str, Any] = {}
        pos += 1
        while True:
            pos = _ws(text, pos)
            if pos >= len(text):
                return obj, pos
            if text[pos] == "}":
                return obj, pos + 1
            if text[pos] == ",":
                pos += 1
                continue
            key, pos = _flow_key(text, pos)
            pos = _ws(text, pos)
            if pos < len(text) and text[pos] == ":":
                pos += 1
            pos = _ws(text, pos)
            if pos >= len(text) or text[pos] in ",}":
                obj[key] = None
            else:
                value, pos = _parse_flow_value(text, pos, "}", depth)
                obj[key] = value
    return _parse_flow_value(text, pos, "", depth)


def _flow_key(text: str, pos: int) -> tuple[str, int]:
    if text[pos] in "\"'":
        return _read_quoted(text, pos)
    start = pos
    while pos < len(text) and text[pos] not in ":,}":
        pos += 1
    return text[start:pos].strip(" \t"), pos


def _parse_flow_value(text: str, pos: int, closer: str, depth: int = 0) -> tuple[Any, int]:
    if text[pos] in "[{":
        return _parse_flow(text, pos, depth + 1)
    if text[pos] in "\"'":
        return _read_quoted(text, pos)
    start = pos
    while pos < len(text) and text[pos] != "," and (closer == "" or text[pos] != closer):
        pos += 1
    return _scalar(text[start:pos]), pos


def _read_quoted(text: str, pos: int) -> tuple[str, int]:
    """Read a quoted scalar starting at ``text[pos]``; returns (value, index after the
    closing quote). An unterminated quote consumes the rest of the text."""
    quote = text[pos]
    pos += 1
    out: list[str] = []
    if quote == "'":
        while pos < len(text):
            ch = text[pos]
            if ch == "'":
                if pos + 1 < len(text) and text[pos + 1] == "'":
                    out.append("'")
                    pos += 2
                    continue
                return "".join(out), pos + 1
            out.append(ch)
            pos += 1
        return "".join(out), pos
    while pos < len(text):
        ch = text[pos]
        if ch == "\\" and pos + 1 < len(text):
            esc = text[pos + 1]
            pos += 2
            if esc == "n":
                out.append("\n")
            elif esc == "t":
                out.append("\t")
            elif esc == "r":
                out.append("\r")
            elif esc == "b":
                out.append("\b")
            elif esc == "f":
                out.append("\f")
            elif esc == "0":
                out.append("\0")
            elif esc == "u" and pos + 4 <= len(text) and all(h in "0123456789abcdefABCDEF" for h in text[pos:pos + 4]):
                cp = int(text[pos:pos + 4], 16)
                # A lone surrogate is not encodable as UTF-8 — substitute U+FFFD (Swift does the same).
                out.append(chr(cp) if not 0xD800 <= cp <= 0xDFFF else "�")
                pos += 4
            else:
                out.append(esc)  # \" \\ \/ and anything unknown → the character itself
            continue
        if ch == '"':
            return "".join(out), pos + 1
        out.append(ch)
        pos += 1
    return "".join(out), pos


def _scalar(s: str) -> Any:
    s = s.strip(" \t")
    if s == "":
        return None
    if s[0] in "\"'":
        value, _ = _read_quoted(s, 0)
        return value
    if s in ("null", "Null", "NULL", "~"):
        return None
    if s in ("true", "True", "TRUE"):
        return True
    if s in ("false", "False", "FALSE"):
        return False
    if _is_int(s):
        v = int(s)
        return v if _INT_MIN <= v <= _UINT_MAX else s
    if _is_float(s):
        return float(s)
    return s


def _is_int(s: str) -> bool:
    body = s[1:] if s[0] in "+-" else s
    return body != "" and all(ch in _DIGITS for ch in body)


def _is_float(s: str) -> bool:
    body = s[1:] if s[0] in "+-" else s
    if body == "" or body[0] not in _DIGITS:
        return False
    i = 0
    while i < len(body) and body[i] in _DIGITS:
        i += 1
    saw_fraction = saw_exponent = False
    if i < len(body) and body[i] == ".":
        i += 1
        start = i
        while i < len(body) and body[i] in _DIGITS:
            i += 1
        if i == start:
            return False
        saw_fraction = True
    if i < len(body) and body[i] in "eE":
        i += 1
        if i < len(body) and body[i] in "+-":
            i += 1
        start = i
        while i < len(body) and body[i] in _DIGITS:
            i += 1
        if i == start:
            return False
        saw_exponent = True
    return i == len(body) and (saw_fraction or saw_exponent)
