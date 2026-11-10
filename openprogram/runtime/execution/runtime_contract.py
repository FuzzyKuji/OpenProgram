"""What an Agent turn was resolved against, and whether it still resolves.

A resumed turn must keep its model, prompt, tools and permissions. The resolved
values are saved once, in the turn's journal, and compared here before resuming.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

# Repeated-failure counters a turn may carry.
MAX_AGENT_REPEAT_FAILURES = 16
RUNTIME_CONTRACT_VERSION = 1


class RuntimeContractError(ValueError):
    """A saved Agent turn is malformed or no longer resolves."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RuntimeContractError(
            "checkpoint_schema_invalid", "checkpoint values must be JSON"
        ) from exc


def json_safe(value: Any) -> Any:
    """Convert runtime metadata to canonical JSON without retaining objects."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif hasattr(value, "to_dict"):
        value = value.to_dict()
    try:
        return json.loads(canonical_json_bytes(value))
    except RuntimeContractError:
        return None


def validate_runtime_contract(
    expected: Mapping[str, Any], actual: Mapping[str, Any], *, durable_function_names=(),
) -> None:
    """Reject runtime drift except implementations with durable function state."""
    if durable_function_names and isinstance(expected, Mapping) and isinstance(actual, Mapping):
        before = expected.get("tools")
        after = actual.get("tools")
        if isinstance(before, list) and isinstance(after, list):
            retained = {tool.get("name"): tool for tool in before if isinstance(tool, Mapping)}
            actual = dict(actual)
            actual["tools"] = [
                {**tool, "implementation": retained[tool["name"]].get("implementation")}
                if isinstance(tool, Mapping) and tool.get("name") in durable_function_names and tool.get("name") in retained
                else tool for tool in after
            ]
    required = {
        "contract_version", "model", "system_prompt", "tools",
        "structured_output", "toolset", "request_semantics",
    }
    if (
        not isinstance(expected, Mapping)
        or set(expected) != required
        or expected.get("contract_version") != RUNTIME_CONTRACT_VERSION
        or not isinstance(expected.get("model"), Mapping)
        or not isinstance(expected["model"].get("id"), str)
        or not expected["model"].get("id")
        or not all(
            isinstance(expected["model"].get(key), str)
            and expected["model"].get(key)
            for key in ("api", "provider", "base_url", "endpoint")
        )
        or not isinstance(expected.get("system_prompt"), str)
        or not isinstance(expected.get("tools"), list)
        or not isinstance(expected.get("request_semantics"), Mapping)
        or not isinstance(expected["request_semantics"].get("_execution_revision_id"), str)
        or not expected["request_semantics"]["_execution_revision_id"]
        or not isinstance(expected["request_semantics"].get("execution_location"), Mapping)
        or any(
            not isinstance(tool, Mapping)
            or set(tool) != {
                "name", "description", "parameters", "cache_control",
                "permission", "approval", "implementation",
            }
            or not isinstance(tool.get("name"), str)
            or not tool.get("name")
            or not isinstance(tool.get("description"), str)
            or not isinstance(tool.get("parameters"), Mapping)
            or not isinstance(tool.get("permission"), Mapping)
            or set(tool["permission"]) != {"mode", "rules"}
            or not isinstance(tool.get("approval"), Mapping)
            or set(tool["approval"]) != {"requires", "accept_edits_safe"}
            or not isinstance(tool["approval"].get("accept_edits_safe"), bool)
            or not isinstance(tool.get("implementation"), Mapping)
            or not all(
                isinstance(tool["implementation"].get(key), str)
                and tool["implementation"].get(key)
                for key in ("module", "qualname", "code_sha256")
            )
            for tool in expected["tools"]
        )
        or not isinstance(actual, Mapping)
        or dict(expected) != dict(actual)
    ):
        differing_fields = [
            key for key in sorted(required)
            if not isinstance(expected, Mapping) or not isinstance(actual, Mapping)
            or expected.get(key) != actual.get(key)
        ]
        if isinstance(expected, Mapping) and isinstance(actual, Mapping):
            expected_semantics = expected.get("request_semantics")
            actual_semantics = actual.get("request_semantics")
            if isinstance(expected_semantics, Mapping) and isinstance(actual_semantics, Mapping):
                differing_fields.extend(
                    f"request_semantics.{key}" for key in (
                        "thinking_effort", "service_tier", "tools_override", "response_format",
                        "structured_output", "structured_output_mode", "structured_output_attempt",
                        "additional_working_dirs", "_execution_revision_id", "execution_location",
                    ) if expected_semantics.get(key) != actual_semantics.get(key)
                )
        tool_differences = []
        if isinstance(expected, Mapping) and isinstance(actual, Mapping):
            before = expected.get("tools")
            after = actual.get("tools")
            if isinstance(before, list) and isinstance(after, list):
                before_by_name = {
                    tool["name"]: tool for tool in before
                    if isinstance(tool, Mapping) and isinstance(tool.get("name"), str)
                }
                after_by_name = {
                    tool["name"]: tool for tool in after
                    if isinstance(tool, Mapping) and isinstance(tool.get("name"), str)
                }
                for name in sorted(before_by_name.keys() | after_by_name.keys()):
                    old, new = before_by_name.get(name), after_by_name.get(name)
                    if old == new:
                        continue
                    fields = (
                        ["added"] if old is None else ["removed"] if new is None else
                        [key for key in (
                            "description", "parameters", "cache_control", "permission",
                            "approval", "implementation",
                        ) if old.get(key) != new.get(key)]
                    )
                    tool_differences.append(f"{name!r}({','.join(fields) or 'schema'})")
                if before != after and not tool_differences:
                    tool_differences.append("order_or_duplicate_entries")
        tool_detail = (
            "; tools: " + ", ".join(tool_differences[:20])
            + (f"; {len(tool_differences) - 20} more" if len(tool_differences) > 20 else "")
            if tool_differences else ""
        )
        raise RuntimeContractError(
            "continuation_contract_mismatch",
            "durable Agent runtime contract no longer resolves exactly; fields: "
            + ", ".join(differing_fields or ["schema"]) + tool_detail,
        )
