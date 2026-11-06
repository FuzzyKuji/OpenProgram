"""The built-in browser, as an application.

The App's browser tabs, the ``web_use`` runtime that controls exact Pages,
the Playwright engine, the user's Chrome or Edge through the Playwright
Extension, and the page resources recorded for each conversation.

- ``pages``: page resources (``BrowserResourceStore``) and their projections.
- ``contract``: the ``web_use`` argument schema and normalization.
- ``web_use/``: the ``web_use`` runtime, its sessions and backends.
- ``engine/``: the Playwright engine the ``web_use`` backends launch Pages with.
- ``chrome``: the Chrome/Chromium bootstrap and the App's CDP endpoint.
- ``privacy``: password-value redaction.
- ``tabs``: the tab driver behind ``computer_use_agent(target="browser")``.
- ``extension``: the user's Chrome or Edge through the Playwright Extension.
- ``prompt``: the system-prompt section about the App's open Pages.
- ``resource``: the ``web`` resource provider and the Page leases.
- ``service``: the ``browser`` service the core reaches all of this through.

The entry is ``web_use``. ``setup`` provides the ``browser`` service, adds
the open-Pages prompt section and the ``web`` resource provider; disposing
the application's context removes all three.
"""

from . import web_use as _web_use
from .contract import web_use_parameters

#: What the Launchpad, Applications page and Abilities call this application
#: (``openprogram.programs._host.identity`` reads them from the source).
TITLE = "Browser"
DESCRIPTION = "The built-in web browser. The Agent uses it to read pages, fill forms and take screenshots."
ICON = "browser"

PROGRAM_ENTRIES = [_web_use.web_use]

ENTRY_OPTIONS = {
    "web_use": {
        "toolset": ("browser",),
        "unsafe_in": ("wechat", "telegram", "plan"),
        "requires_approval": _web_use._web_use_requires_approval,
        "defer": True,
        "timeout": 120,
        # The Page inventory, WebSession registry, and renderer WebSocket
        # registry are worker-owned: run in the worker instead of copying
        # those registries into an isolated process.
        "run_in_worker": True,
        "parameters": web_use_parameters(),
        "input": {
            "command": {
                "description": (
                    "Call list_pages first; then observe, act, verify, or close. "
                    "observe or act with url opens a desktop web tab when no Page exists. "
                    "close closes the observed Page's tab and ends its session."
                ),
            },
            "backend": {
                "description": "Backend used when observe creates a session",
                "hidden": True,
                "advanced": True,
            },
            "page": {"description": "Turn Page alias used by observe; never a URL"},
            "web_session_id": {
                "description": "Session returned by observe",
                "hidden": True,
                "advanced": True,
            },
            "page_context_token": {"hidden": True, "advanced": True},
            "arguments": {
                "description": (
                    "Command-specific arguments. act needs action; expected_frame_id "
                    "is filled from the last observe when omitted. action, url, text, "
                    "and ref may also be passed at the top level."
                ),
            },
        },
    },
}


def setup(ctx) -> None:
    from openprogram.host.resources import registry as resources
    from . import prompt, resource
    from .service import BrowserService

    ctx.provide("browser", BrowserService())
    ctx.context("pages", prompt.pages_section, layer="L2")
    ctx.effect(resource.register(resources), "resource web")
