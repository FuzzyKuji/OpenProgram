"""Server-side context edits a request carries by default.

Anthropic's Context Editing API clears old tool results on the server
without breaking the prompt cache prefix. When an edit fires depends on how
many tool calls the current run has made, which only the runtime counts, so
the runtime registers the producer here when it loads. A request that sets
``StreamOptions.cache_edits`` uses its own; every other request (summaries,
classifiers, background calls) uses this default, so each provider request
of a run sees the same trigger state.

Kept free of provider imports so registering it costs nothing.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

CacheEdits = Callable[[], "dict[str, Any] | None"]

_default: CacheEdits | None = None


def register_default_cache_edits(producer: CacheEdits) -> None:
    """Make ``producer`` the cache edits of a request that names none."""
    global _default
    _default = producer


def default_cache_edits() -> CacheEdits | None:
    """The registered producer, or None when nothing counts tool calls."""
    return _default


__all__ = ["CacheEdits", "default_cache_edits", "register_default_cache_edits"]
