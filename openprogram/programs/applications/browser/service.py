"""The ``browser`` service: everything of the built-in browser the core reaches.

The application's ``setup`` provides one :class:`BrowserService` as the
service ``browser``. The core never imports the application; it looks the
service up (``openprogram.programs._host.services.lookup("browser")``) and runs
without a browser when the lookup returns ``None``.

Members:

- ``pages``: the page-resource module (``BrowserResourceStore``, the
  per-conversation projections, resource control, human page input).
- ``web_use_parameters()`` / ``normalize_web_use_arguments(arguments)``:
  the ``web_use`` argument contract.
- ``execute_direct_web_use(arguments, owner_id=...)``: one ``web_use``
  command for an MCP client.
- ``registry()``: the ``web_use`` session registry; ``release_owner`` /
  ``park_owner`` end or keep a turn's sessions without creating one.
- ``authorized_page(arguments, window_id)``: the observed Page's lease,
  for a native presentation command.
- ``browser_of(args)``: ``chrome`` or ``edge`` when a call names the
  user's own browser, else ``""``; ``user_browser_names`` names them.
- ``tabs``: the tab driver behind ``computer_use_agent(target="browser")``
  (``ACTIONS``, ``driver()``, ``batch()``).
- ``extension``: the user's Chrome or Edge through the Playwright
  Extension (``ExtensionBrowser``, ``Unavailable``).
- ``chrome``: the Chrome bootstrap (sidecar profile, port file), which
  ``openprogram browser`` maintains.
"""
from __future__ import annotations

from typing import Any, Mapping

from . import chrome, contract, extension, pages, tabs
from .resource import authorized_page
from .web_use import execute_direct_web_use as _execute_direct_web_use
from .web_use import runtime as _runtime


class BrowserService:
    """The built-in browser, as the core reaches it."""

    pages = pages
    tabs = tabs
    chrome = chrome
    extension = extension
    user_browser_names = extension.NAMES

    @staticmethod
    def web_use_parameters() -> dict:
        return contract.web_use_parameters()

    @staticmethod
    def normalize_web_use_arguments(arguments: Mapping[str, Any]) -> dict:
        return contract.normalize_web_use_arguments(arguments)

    @staticmethod
    def execute_direct_web_use(arguments: dict, *, owner_id: str):
        return _execute_direct_web_use(arguments, owner_id=owner_id)

    @staticmethod
    def registry():
        return _runtime.get_registry()

    @staticmethod
    def release_owner(owner_id: str) -> None:
        _runtime.release_owner_if_initialized(owner_id)

    @staticmethod
    def park_owner(owner_id: str) -> None:
        _runtime.park_owner_if_initialized(owner_id)

    authorized_page = staticmethod(authorized_page)

    @staticmethod
    def browser_of(args: Mapping[str, Any]) -> str:
        return extension.browser_of(args)


def get() -> BrowserService | None:
    """The provided ``browser`` service, or ``None`` while the browser is not enabled."""
    from openprogram.programs._host import services as _services
    return _services.lookup("browser")


#: What a caller reports when the browser application is not loaded.
NOT_ENABLED = "the browser is not enabled"
