"""Per-tool argument normalisers that run after schema coercion.

A tool whose arguments have a normal form richer than its JSON schema (the
browser's ``web_use`` commands, say) registers a normaliser here when its
Program loads (``openprogram.programs._host.lower_layers``). Tool-call validation
asks :func:`normalizer_for` after coercing the arguments and, when one is
registered, hands the arguments through it. The normaliser returns the
arguments in normal form or raises ``ValueError`` to refuse the call.

Models sit below Programs and never import them; this registry is how a
Program's argument contract reaches validation.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

ArgumentNormalizer = Callable[[str, dict[str, Any]], dict[str, Any]]

_normalizers: dict[str, ArgumentNormalizer] = {}


def register_argument_normalizer(tool_name: str, normalizer: ArgumentNormalizer) -> None:
    """Install ``normalizer(tool_name, arguments)`` for ``tool_name``."""
    _normalizers[tool_name] = normalizer


def normalizer_for(tool_name: str) -> ArgumentNormalizer | None:
    """The normaliser registered for ``tool_name``, or None."""
    return _normalizers.get(tool_name)


__all__ = ["ArgumentNormalizer", "normalizer_for", "register_argument_normalizer"]
