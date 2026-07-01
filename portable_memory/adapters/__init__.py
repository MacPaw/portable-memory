"""Vendor ingest adapters (cross-provider import).

Each adapter maps a foreign export onto portable episodes; whatever it doesn't model is
preserved in ``metadata`` (namespaced) so a later ``.mem`` export stays lossless.
"""
from __future__ import annotations

from .mem0 import Mem0Adapter, parse_episodes

__all__ = ["Mem0Adapter", "parse_episodes"]
