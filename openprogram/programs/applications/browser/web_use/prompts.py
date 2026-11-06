"""What a controller result shows a model: screenshot pixels stay out of its text."""
from __future__ import annotations
from importlib import import_module

# Bind to the web_use package namespace.
state = import_module(__package__)


def _result_for_prompt(result: state.Any) -> state.Any:
    """Keep screenshot pixels out of the planner's text channel."""
    if not isinstance(result, state.ToolReturn) or not result.images:
        return result
    metadata = dict(result.json_data) if isinstance(result.json_data, dict) else {}
    return {
        key: value
        for key, value in {
            "frame_id": metadata.get("frame_id"),
            "viewport": metadata.get("viewport"),
            "image_attached": True,
        }.items()
        if value is not None
    }
