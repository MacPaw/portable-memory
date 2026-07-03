"""Vendor ingest adapters (cross-provider import).

Each adapter maps a foreign export onto portable episodes; whatever it doesn't model is
preserved in ``metadata`` (namespaced) so a later ``.mem`` export stays lossless. Every
adapter exposes ``parse_episodes(...)`` (input shape varies by source) returning
``list[PortableEpisode]``.
"""
from __future__ import annotations

from .claude import ClaudeAdapter
from .mem0 import Mem0Adapter
from .mem0 import parse_episodes  # back-compat: the bare name is the original mem0 adapter
from .openai import OpenAIAdapter

__all__ = ["Mem0Adapter", "OpenAIAdapter", "ClaudeAdapter", "parse_episodes"]
