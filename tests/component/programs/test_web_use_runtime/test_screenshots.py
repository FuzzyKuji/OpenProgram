"""web use screenshots tests."""
from __future__ import annotations


def test_web_use_preserves_screenshot_tool_return(monkeypatch):
    from openprogram.programs import ToolReturn
    from openprogram.programs.applications.browser import web_use as browser
    screenshot = ToolReturn(images=[b"png"], json_data={"frame_id": "f1"})
    monkeypatch.setattr(browser, "_execute_web_use", lambda *args: screenshot)
    result = browser.web_use(command="act", arguments={"action": "screenshot"})
    assert result is screenshot
    assert result.images == [b"png"]

