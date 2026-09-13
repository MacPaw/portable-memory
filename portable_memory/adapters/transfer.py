"""Memory-transfer text adapter — the de-facto cross-vendor interchange today.

Since March 2026 the major assistants move memory between each other by *prompt*, not by
file. Claude (claude.com/import-memory) and Gemini (gemini.google/import-memory) hand the
user a prompt to run in the source assistant — "List every memory you have stored about
me … Output everything in a single code block … Format each entry as: [date saved, if
available] - memory content" — and the user pastes the result into the destination's
import box. ChatGPT has no memory export at all (its "Manage memories" list is copied by
hand, or the same prompt is used), and Claude's own export ("View and edit your memory",
or asking Claude to write its memories out verbatim) is free text too.

That pasted text is lossy prose with no identity, no structure, and no way to delete —
exactly the failure mode Portable Memory exists to fix. This adapter is the on-ramp:

* :meth:`TransferTextAdapter.parse_episodes` maps the text onto portable episodes, one per
  entry, preserving the bracketed date verbatim, the section a header put it under, and
  its line number, so nothing the source wrote is lost. Ids are **deterministic** (a hash
  of the entry), so pasting the same export twice merges instead of duplicating, and both
  reference SDKs produce byte-identical bundles from the same text.
* :meth:`TransferTextAdapter.render_text` is the reverse: any episodes → the
  ``[date] - content`` block every importer accepts. Portable Memory in, paste-ready text
  out.

Accepted input (tolerant; the rules are normative for cross-SDK parity and mirrored
line-for-line by the Swift ``TransferTextAdapter``):

* Text with one or more ```` ``` ```` fenced blocks — only the fenced content is read (the
  assistant's surrounding prose, e.g. "that is the complete set", is ignored) — or plain
  text with no fences (the whole text is read).
* Entries: ``[date] - content`` with ``-``, ``–``, ``—`` or ``:`` as the separator; a bare
  ISO date ``2026-01-15 - content``; bulleted (``-``, ``*``, ``•``) or numbered (``1.``,
  ``1)``, ``(1)``) lines; undated lines. Bracket text that is not a recognizable date
  (``[date unknown]``, ``[n/a]``) is kept verbatim in metadata and the entry is undated.
* Dates: ``YYYY-MM-DD`` (optionally ``THH:MM:SSZ``), ``YYYY-MM``, ``YYYY``, ``Month YYYY``,
  ``Month D, YYYY``, ``D Month YYYY`` (English month names or abbreviations).
* Headers (``## Preferences``, ``**Projects**``, ``Preferences:``, ``TOOLS``) set the
  section for the entries that follow; they never become entries themselves.
* Indented lines continue the previous entry (multi-line memories).
* Text with no entry markers at all (e.g. Claude's prose memory summary) is read as
  paragraphs: each blank-line-separated block is one entry.

Adapters are pure: text in, ``list[PortableEpisode]`` out. No host, store, or I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from .._codec import format_timestamp
from ..hashing import sha256_hex_str
from ..records import PortableEpisode

__all__ = ["TransferTextAdapter", "parse_episodes", "render_text"]

_BULLETS = ("-", "*", "•", "–", "—")
_SEPARATORS = ("-", "–", "—", ":")
_DIGITS = "0123456789"
_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_ID_PREFIX = "tx_"


@dataclass
class _Entry:
    line: int             # 1-based line number within the parsed body
    section: str | None   # the most recent header, verbatim
    date_raw: str | None  # bracket (or bare-ISO) text, verbatim
    content: str          # the memory text; continuation lines joined with "\n"


class TransferTextAdapter:
    """Maps pasted memory-transfer text onto portable episodes, and back."""

    @staticmethod
    def parse_episodes(
        text: bytes | str,
        *,
        source: str | None = None,
        now: datetime | None = None,
    ) -> list[PortableEpisode]:
        """Parse ``text`` into episodes.

        ``source`` names the assistant the text came from (``"chatgpt"``, ``"claude"``,
        ``"gemini"``, …) and is recorded as ``metadata["transfer_source"]``. ``now`` is the
        ingestion instant (and the event time of undated entries); inject it for
        reproducible output — ids never depend on it.
        """
        if isinstance(text, (bytes, bytearray)):
            text = bytes(text).decode("utf-8")
        stamp = now or datetime.now(timezone.utc)
        episodes: list[PortableEpisode] = []
        seen: set[str] = set()
        for entry in _entries(_body_lines(text)):
            ep = _episode(entry, source, stamp)
            if ep.id in seen:
                continue  # an exact repeat of an earlier entry — keep the first
            seen.add(ep.id)
            episodes.append(ep)
        return episodes

    @staticmethod
    def render_text(episodes: Iterable[PortableEpisode], *, group_by_section: bool = False) -> str:
        """Render episodes as paste-ready ``[YYYY-MM-DD] - content`` lines.

        Continuation lines of a multi-line memory are indented by two spaces, which is
        what :meth:`parse_episodes` reads back as a continuation. With ``group_by_section``
        the first category of each episode becomes a ``## Section`` header (the standard
        export prompt asks *not* to group, so the default is a flat list).
        """
        out: list[str] = []
        if group_by_section:
            order: list[str] = []
            groups: dict[str, list[PortableEpisode]] = {}
            for e in episodes:
                key = e.categories[0] if e.categories else ""
                if key not in groups:
                    groups[key] = []
                    order.append(key)
                groups[key].append(e)
            for i, key in enumerate(order):
                if i:
                    out.append("")
                if key:
                    out.append("## " + key)
                out.extend(_render_lines(groups[key]))
        else:
            out.extend(_render_lines(episodes))
        return "\n".join(out) + ("\n" if out else "")


# ── Body ──────────────────────────────────────────────────────────────────────────────

def _body_lines(text: str) -> list[str]:
    """The lines to parse: the contents of all fenced blocks if any, else every line."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    inside = False
    saw_fence = False
    fenced: list[str] = []
    for line in lines:
        if line.strip().startswith("```"):
            saw_fence = True
            inside = not inside
            continue
        if inside:
            fenced.append(line)
    return fenced if saw_fence else lines


def _entries(lines: list[str]) -> list[_Entry]:
    if not any(_is_marker(line) for line in lines):
        return _paragraphs(lines)
    entries: list[_Entry] = []
    section: str | None = None
    current: _Entry | None = None
    for number, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if not stripped:
            current = None
            continue
        if current is not None and raw[0] in (" ", "\t"):
            current.content += "\n" + stripped
            continue
        text, bulleted = _strip_bullet(stripped)
        header = _header(text, bulleted)
        if header is not None:
            section = header
            current = None
            continue
        date_raw, content = _split_date(text)
        if not content:
            current = None
            continue
        current = _Entry(line=number, section=section, date_raw=date_raw, content=content)
        entries.append(current)
    return entries


def _paragraphs(lines: list[str]) -> list[_Entry]:
    entries: list[_Entry] = []
    buf: list[str] = []
    start = 0
    for number, raw in enumerate(lines, start=1):
        s = raw.strip()
        if s:
            if not buf:
                start = number
            buf.append(s)
        elif buf:
            entries.append(_Entry(line=start, section=None, date_raw=None, content="\n".join(buf)))
            buf = []
    if buf:
        entries.append(_Entry(line=start, section=None, date_raw=None, content="\n".join(buf)))
    return entries


def _is_marker(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    text, bulleted = _strip_bullet(s)
    return bulleted or text.startswith("[") or _header(text, bulleted) is not None or _bare_iso(text) is not None


# ── Line pieces ───────────────────────────────────────────────────────────────────────

def _strip_bullet(s: str) -> tuple[str, bool]:
    """Remove one leading list marker (``- ``, ``* ``, ``• ``, ``1. ``, ``1) ``, ``(1) ``)."""
    for b in _BULLETS:
        if s.startswith(b + " "):
            return s[len(b):].lstrip(), True
    body = s[1:] if s.startswith("(") else s
    i = 0
    while i < len(body) and i < 3 and body[i] in _DIGITS:
        i += 1
    if 0 < i < len(body) and body[i] in ".)" and i + 1 < len(body) and body[i + 1] == " ":
        return body[i + 1:].lstrip(), True
    return s, False


def _header(text: str, bulleted: bool) -> str | None:
    """The section name if ``text`` is a header line, else None."""
    if bulleted or not text or text.startswith("["):
        return None
    if text.startswith("#"):
        name = text.lstrip("#").strip()
        return name or None
    if text.startswith("**"):
        inner = text.rstrip(":").strip()
        if inner.endswith("**") and len(inner) > 4:
            name = inner[2:-2].strip().rstrip(":").strip()
            return name or None
        return None
    if _has_separator(text) or _bare_iso(text) is not None:
        return None
    words = text.split()
    if text.endswith(":") and len(words) <= 8:
        name = text[:-1].strip()
        return name or None
    letters = [c for c in text if c.isalpha()]
    if len(letters) >= 3 and len(words) <= 6 and all(c.isupper() for c in letters):
        return text
    return None


def _has_separator(text: str) -> bool:
    return " - " in text or " – " in text or " — " in text


def _is_iso_date(s: str) -> bool:
    return (
        len(s) == 10 and s[4] == "-" and s[7] == "-"
        and all(s[i] in _DIGITS for i in (0, 1, 2, 3, 5, 6, 8, 9))
    )


def _bare_iso(text: str) -> tuple[str, str] | None:
    """``2026-01-15 - content`` / ``2026-01-15: content`` → (date token, content)."""
    if not _is_iso_date(text[:10]):
        return None
    sp = text.find(" ")
    token = text if sp == -1 else text[:sp]
    rest = "" if sp == -1 else text[sp + 1:].lstrip()
    if token and token[-1] in _SEPARATORS:
        return token[:-1], rest.strip()
    if rest and rest[0] in _SEPARATORS:
        return token, rest[1:].lstrip().strip()
    return None


def _split_date(text: str) -> tuple[str | None, str]:
    """``[date] - content`` → (date text or None, content)."""
    if text.startswith("["):
        end = text.find("]")
        if end != -1:
            date_raw = text[1:end].strip()
            rest = text[end + 1:].lstrip()
            if rest and rest[0] in _SEPARATORS:
                rest = rest[1:].lstrip()
            return (date_raw or None), rest.strip()
        return None, text
    bare = _bare_iso(text)
    if bare is not None:
        return bare[0], bare[1].strip()
    return None, text


# ── Dates ─────────────────────────────────────────────────────────────────────────────

def _parse_date(raw: str) -> datetime | None:
    s = raw.strip()
    if not s:
        return None
    if len(s) >= 10 and _is_iso_date(s[:10]):
        y, m, d = int(s[:4]), int(s[5:7]), int(s[8:10])
        if (
            len(s) == 20 and s[10] == "T" and s[13] == ":" and s[16] == ":" and s[19] == "Z"
            and all(s[i] in _DIGITS for i in (11, 12, 14, 15, 17, 18))
        ):
            hh, mm, ss = int(s[11:13]), int(s[14:16]), int(s[17:19])
            if hh <= 23 and mm <= 59 and ss <= 59:
                return _ymd(y, m, d, hh, mm, ss)
        return _ymd(y, m, d)
    if len(s) == 7 and s[4] == "-" and all(s[i] in _DIGITS for i in (0, 1, 2, 3, 5, 6)):
        return _ymd(int(s[:4]), int(s[5:7]), 1)
    if len(s) == 4 and all(c in _DIGITS for c in s):
        return _ymd(int(s), 1, 1)
    tokens = s.replace(",", " ").split()
    if len(tokens) == 2:
        m, y = _MONTHS.get(tokens[0].lower()), _int4(tokens[1])
        if m and y:
            return _ymd(y, m, 1)
    if len(tokens) == 3:
        m, d, y = _MONTHS.get(tokens[0].lower()), _day(tokens[1]), _int4(tokens[2])
        if m and d and y:
            return _ymd(y, m, d)
        d, m, y = _day(tokens[0]), _MONTHS.get(tokens[1].lower()), _int4(tokens[2])
        if m and d and y:
            return _ymd(y, m, d)
    return None


def _int4(t: str) -> int | None:
    return int(t) if len(t) == 4 and all(c in _DIGITS for c in t) else None


def _day(t: str) -> int | None:
    t = t.lower()
    for suffix in ("st", "nd", "rd", "th"):
        if t.endswith(suffix):
            t = t[:-2]
            break
    return int(t) if 1 <= len(t) <= 2 and all(c in _DIGITS for c in t) else None


def _ymd(y: int, m: int, d: int, hh: int = 0, mm: int = 0, ss: int = 0) -> datetime | None:
    try:
        return datetime(y, m, d, hh, mm, ss, tzinfo=timezone.utc)
    except ValueError:
        return None


# ── Episodes ──────────────────────────────────────────────────────────────────────────

def _episode(e: _Entry, source: str | None, now: datetime) -> PortableEpisode:
    parsed = _parse_date(e.date_raw) if e.date_raw else None
    date_key = format_timestamp(parsed)[:10] if parsed else ""
    # Deterministic identity: the same dated memory text always maps to the same id, in
    # both SDKs, so repeated pastes merge and cross-SDK bundles are byte-identical.
    ident = _ID_PREFIX + sha256_hex_str(date_key + "\n" + e.content)[:24]
    meta: dict[str, str] = {"transfer_line": str(e.line)}
    _put(meta, "transfer_source", source)
    _put(meta, "transfer_date_raw", e.date_raw)
    _put(meta, "transfer_section", e.section)
    when = parsed or now
    first_line = e.content.split("\n", 1)[0]
    return PortableEpisode(
        id=ident,
        event_time=when,
        mention_time=when,
        ingestion_time=now,
        source_type="note",
        source_id=None,
        actors=[],
        summary=first_line[:120],
        details=e.content,
        sensitivity="low",
        deleted_at=None,
        metadata=meta,
        context_id=None,
        categories=[e.section] if e.section else [],
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


def _render_lines(episodes: Iterable[PortableEpisode]) -> list[str]:
    out: list[str] = []
    for e in episodes:
        text = e.details or e.summary
        if not text.strip():
            continue
        parts = text.split("\n")
        date = format_timestamp(e.event_time)[:10]
        out.append(f"[{date}] - {parts[0]}")
        out.extend("  " + p for p in parts[1:])
    return out


def _put(meta: dict[str, str], key: str, value: str | None) -> None:
    if value:
        meta[key] = value


parse_episodes = TransferTextAdapter.parse_episodes
render_text = TransferTextAdapter.render_text
