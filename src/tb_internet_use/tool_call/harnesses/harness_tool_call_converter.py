"""Define the tool call converter that each harness subclasses, with the default of every part that differs by harness."""

import json
from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from tb_internet_use.tool_call._convert_tool_call_result import (
    result_from_harness_result_format,
)
from tb_internet_use.tool_call.model import (
    HarnessToolCall,
    HarnessToolLabel,
    PollAction,
    ToolCallAction,
    ToolCallResult,
)

if TYPE_CHECKING:
    # The door and the declaration types are named in annotations only, so that `convert_tool_calls` never loads `knowledge/` itself.
    from tb_internet_use.knowledge.harness_result_format_declaration import (
        JsonObject,
    )
    from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge


class HarnessToolCallConverter:
    """Converter of the parts of tool call conversion that differ by harness, one per harness, called by `convert_tool_calls`.

    The result formats of each harness tool are declared in `knowledge/`, and `convert_result` asks `ToolCallKnowledge` which of them a result has.

    The shared flow in _convert_tool_calls.py, _convert_tool_call_result.py and _convert_tool_call_action.py calls
    - `convert_result`, which builds a `ToolCallResult` from the declared formats through `tool_result_raw_text_of`, `tool_result_json_of` and `is_marked_as_error`.
      A harness overrides a hook when its trajectory differs, and `convert_result` itself to add what formats cannot express.
    - `refine_action` and `action_of_deferred_tool`, which fill the `ToolCallAction` fields that the action type and the argument fields of a label alone cannot express.
    """

    def convert_result(
        self,
        harness_tool_call: HarnessToolCall,
        tool_result: dict[str, Any],
        *,
        knowledge: ToolCallKnowledge,
        judgment_rule_use_counts: Counter[str],
    ) -> ToolCallResult:
        """Convert a tool call result in the trajectory into a ToolCallResult.

        By default, it asks `knowledge` which declared format the result has, from what the hooks `tool_result_raw_text_of`, `tool_result_json_of` and `is_marked_as_error` return, and builds the result with `result_from_harness_result_format`.
        A harness overrides those hooks when its trajectory differs, and this method to add what formats cannot express.
        An override that applies a rule of `judgment_rules.py` passes it `judgment_rule_use_counts`.
        """
        tool_result_raw_text = self.tool_result_raw_text_of(
            harness_tool_call, tool_result
        )
        tool_result_json = (
            self.tool_result_json_of(harness_tool_call, tool_result)
            if knowledge.has_json_result_formats(harness_tool_call.tool)
            else None
        )
        harness_result_format = knowledge.harness_result_format(
            harness_tool_call.tool,
            tool_result_raw_text,
            tool_result_json,
            is_marked_as_error=self.is_marked_as_error(harness_tool_call, tool_result),
        )
        return result_from_harness_result_format(
            tool_result_raw_text, harness_result_format
        )

    def tool_result_json_of(
        self, harness_tool_call: HarnessToolCall, tool_result: dict[str, Any]
    ) -> JsonObject | None:
        """Read the JSON object of the tool result. `convert_result` asks only for a tool with JSON formats.

        By default, it is the raw text decoded as a JSON object, or None when the raw text holds no JSON object.
        """
        raw_text = self.tool_result_raw_text_of(harness_tool_call, tool_result)
        return _decode_json(raw_text) or None  # {} has nothing to match

    def tool_result_raw_text_of(
        self, harness_tool_call: HarnessToolCall, tool_result: dict[str, Any]
    ) -> str | None:
        """Read the tool result text from the trajectory.

        By default, it is the result's `content` if that is a string, else None.
        """
        content = tool_result.get("content")
        return content if isinstance(content, str) else None

    def is_marked_as_error(
        self, harness_tool_call: HarnessToolCall, tool_result: dict[str, Any]
    ) -> bool:
        """Tell whether the harness marked the result as an error, which picks the tool's formats for such results when it has them.

        By default, it is False. Claude Code reads its mark from the trajectory.
        """
        return False

    def refine_action(
        self,
        harness_tool_call: HarnessToolCall,
        action: ToolCallAction,
        tool_call_result: ToolCallResult | None,
        label: HarnessToolLabel,
    ) -> ToolCallAction:
        """Fill fields of a `ToolCallAction` that the action type and the argument fields of its tool's label cannot express.

        By default, a `PollAction` takes the handles the result named, which carry their kind.
        When the result names none, its argument handles take the `argument_handle_kind` of the label, if the label has one.
        The `PollAction` of a tool whose label says `stops_execution` is a terminate.
        """
        if not isinstance(action, PollAction):
            return action
        if tool_call_result is not None and tool_call_result.handles:
            action = replace(action, handles=tool_call_result.handles)
        elif label.argument_handle_kind is not None:
            kind = label.argument_handle_kind
            handles = tuple(replace(handle, kind=kind) for handle in action.handles)
            action = replace(action, handles=handles)
        if label.stops_execution:
            action = replace(action, terminate=True)
        return action

    def action_of_deferred_tool(
        self,
        harness_tool_call: HarnessToolCall,
        tool_call_result: ToolCallResult | None,
        *,
        knowledge: ToolCallKnowledge,
    ) -> ToolCallAction:
        """Decide the `ToolCallAction` of a tool labeled Deferred.

        Only harnesses with Deferred tools override this.
        It gets `knowledge` since a call can hold calls of other tools, e.g. the steps of a Codex `exec` script, whose labels it must ask for.
        """
        raise NotImplementedError(f"no Deferred handling for {harness_tool_call.tool}")


def _decode_json(raw_text: str | None) -> dict[str, Any] | None:
    """Decode the raw text as a JSON object. None when it is missing or not a JSON object."""
    if raw_text is None or not raw_text.lstrip().startswith("{"):
        return None
    try:
        decoded = json.loads(raw_text)
    except ValueError:
        return None
    return decoded if isinstance(decoded, dict) else None
