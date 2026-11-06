"""observe finds a Page the turn has not bound, by its list_pages name."""
from __future__ import annotations

import pytest

from openprogram.runtime.conversation import surface_context
from openprogram.programs.applications.browser.web_use import runtime as web_use_runtime
from openprogram.programs.applications.browser.web_use.execute import _execute_web_use

_PAGES = [
    {"page": "p1", "aliases": ["p1", "web:1"], "region": "background", "visible": False,
     "focused": False, "title": "Results", "page_context_token": "pct_one"},
    {"page": "p2", "aliases": ["p2", "web:2"], "region": "center", "visible": True,
     "focused": False, "title": "Form", "page_context_token": "pct_two"},
]


@pytest.fixture
def registry(monkeypatch):
    class _Registry:
        def __init__(self):
            self.executed = []
            self.pages = list(_PAGES)

        def list_pages(self, *, context, owner_id):
            return {"ok": True, "pages": self.pages}

        def execute(self, **kwargs):
            self.executed.append(kwargs)
            return {"ok": True, "frame_id": "frame-1"}

    value = _Registry()
    # A new turn: the window is known, but no Page is bound to it yet.
    monkeypatch.setattr(surface_context, "current",
                        lambda: {"context_id": "c1", "origin_window_id": "main", "surfaces": []})
    monkeypatch.setattr(surface_context, "capture_pages_for_listing", lambda _context=None: {"surfaces": []})
    monkeypatch.setattr(surface_context, "release_bindings", lambda _context: None)
    monkeypatch.setattr(web_use_runtime, "get_registry", lambda: value)
    return value


@pytest.mark.parametrize("page, token", [("p2", "pct_two"), ("web:1", "pct_one"), ("", "pct_two")])
def test_observe_resolves_a_listed_page(registry, page, token):
    result = _execute_web_use("observe", page=page)
    assert result["ok"] is True
    assert registry.executed[-1]["page_context_token"] == token


def test_unknown_or_ambiguous_page_lists_the_choices(registry):
    missing = _execute_web_use("observe", page="p9")
    assert missing["reason_code"] == "page_not_found"
    assert [item["page_context_token"] for item in missing["pages"]] == ["pct_one", "pct_two"]
    registry.pages = [{**item, "region": "center", "visible": True} for item in _PAGES]
    ambiguous = _execute_web_use("observe")
    assert ambiguous["reason_code"] == "page_required"
    assert registry.executed == []
