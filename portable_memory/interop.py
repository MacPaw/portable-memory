"""Cross-vendor lossless passthrough (spec §1 ``ext``, §10).

For a ``.mem`` bundle to be a LOSSLESS container for any vendor's memory, two things
another system put in a bundle must survive a round-trip even though this engine doesn't
model them:
  * unknown FIELDS on an episode — captured into ``ext`` and re-merged on export;
  * unknown KINDS (``items/<vendorKind>.jsonl``) — stored raw and re-emitted with each
    record's bytes preserved (JSONL framing normalized to a single trailing newline).

Both native and foreign fields are serialized through the same canonical codec, so an
episode carrying ``ext`` is byte-identical to one without for its native portion.
"""
from __future__ import annotations

import json
from dataclasses import fields

from ._codec import canonical_json
from .records import PortableEpisode

#: The native JSON keys on an episode. Any key on an imported episode line NOT in this
#: set is a foreign field -> ext.
KNOWN_EPISODE_KEYS: frozenset[str] = frozenset(
    f.metadata.get("json", f.name) for f in fields(PortableEpisode)
)


def extract_episode_ext(line: bytes | str) -> str | None:
    """From one raw episode JSONL line, return the canonical JSON of any foreign
    (non-native) keys — the ``ext`` to persist so it round-trips. ``None`` when none."""
    obj = json.loads(line)
    extra = {k: v for k, v in obj.items() if k not in KNOWN_EPISODE_KEYS}
    if not extra:
        return None
    return canonical_json(extra)


def merge_episode_ext(native_json: bytes, ext_json: str | None) -> bytes:
    """Merge persisted ``ext`` keys back into an episode's native JSON on export, without
    overriding any native key. Returns the original bytes unchanged when there is no ext
    (so ext-free exports stay byte-identical)."""
    if not ext_json:
        return native_json
    ext = json.loads(ext_json)
    if not ext:
        return native_json
    obj = json.loads(native_json)
    for k, v in ext.items():
        if k not in obj:
            obj[k] = v
    return canonical_json(obj).encode("utf-8")
