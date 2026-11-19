"""Convert the tool calls of Copilot CLI, reading the result text without the JSON line that ends it and splitting the calls of `view` and `apply_patch` by what they did."""

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from tb_internet_use.tool_call.harnesses.harness_tool_call_converter import (
    HarnessToolCallConverter,
)
from tb_internet_use.tool_call.model import (
    ChangeFilesAction,
    HarnessToolCall,
    ListFilesAction,
    ReadFileAction,
    ToolCallAction,
    ToolCallResult,
    UnknownAction,
)
from tb_internet_use.tool_call.parse_patch import parse_patch

if TYPE_CHECKING:
    # The door is passed in and named in annotations only, so that `convert_tool_calls` never loads `knowledge/` itself.
    from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge

# The kind of path that Copilot CLI says in the telemetry of a `view` result that it listed, a folder.
_FOLDER_VIEW_TYPE = "directory"


class CopilotCliConverter(HarnessToolCallConverter):
    def tool_result_raw_text_of(
        self, harness_tool_call: HarnessToolCall, tool_result: dict[str, Any]
    ) -> str | None:
        """Read the result text that Copilot CLI gave the model, which is `content` without its last line.

        Every result in the trajectory ends with a line that holds a JSON object, the rest of Copilot CLI's result, e.g. `{"detailedContent": "...", "structuredContent": {"shellId": "4"}}`, or `{"code": "failure"}` for a failed call.
        A content that does not end in such a line gives None, so that it matches no format.
        """
        content = super().tool_result_raw_text_of(harness_tool_call, tool_result)
        if content is None:
            return None
        text, _, last_line = content.rpartition("\n")
        return text if _is_json_object(last_line) else None

    def is_marked_as_error(
        self, harness_tool_call: HarnessToolCall, tool_result: dict[str, Any]
    ) -> bool:
        """Tell whether Copilot CLI marked the call as failed with `success: false` in the `extra` of its result."""
        return _extra_of(tool_result).get("success") is False

    def action_of_deferred_tool(
        self,
        harness_tool_call: HarnessToolCall,
        tool_call_result: ToolCallResult | None,
        *,
        knowledge: ToolCallKnowledge,
    ) -> ToolCallAction:
        """Decide the action of a `view`, which reads a file or lists a folder, or of an `apply_patch`, which changes files.

        A `view` is a `ListFilesAction` when Copilot CLI says in the telemetry of its result that the path was a folder, and a `ReadFileAction` otherwise.
        An `apply_patch` is a `ChangeFilesAction` with the file changes of its patch, e.g. a `WriteFileAction` for an added file, and an `UnknownAction` when the patch gives no file change.
        """
        args = harness_tool_call.args
        match harness_tool_call.tool.name:
            case "view":
                path = args.get("path")
                path = path if isinstance(path, str) else None
                if _view_type_of(harness_tool_call.result) == _FOLDER_VIEW_TYPE:
                    return ListFilesAction(path)
                return ReadFileAction(path)
            case "apply_patch":
                patch = args.get("value")
                file_changes = parse_patch(patch) if isinstance(patch, str) else []
                if not file_changes:
                    return UnknownAction()
                return ChangeFilesAction(tuple(file_changes))
            case _:
                return super().action_of_deferred_tool(
                    harness_tool_call, tool_call_result, knowledge=knowledge
                )


def _view_type_of(tool_result: Mapping[str, Any] | None) -> Any:
    """Read the kind of path that the telemetry of a `view` result names, e.g. `file`, `image` or `directory`, or None without one."""
    telemetry = _extra_of(tool_result or {}).get("toolTelemetry") or {}
    properties = telemetry.get("properties") or {}
    return properties.get("viewType")


def _extra_of(tool_result: Mapping[str, Any]) -> Mapping[str, Any]:
    return tool_result.get("extra") or {}


def _is_json_object(text: str) -> bool:
    try:
        decoded = json.loads(text)
    except ValueError:
        return False
    return isinstance(decoded, dict)
