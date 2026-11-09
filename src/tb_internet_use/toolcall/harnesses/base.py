"""Interface for tool call converters that each harness implements."""

import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, ClassVar

from tb_internet_use.toolcall.model import (
    Action,
    ExecutionHandleKind,
    PollAction,
    RawToolCall,
    ToolCallOutput,
)
from tb_internet_use.toolcall.result_formats import (
    HarnessResultFormatList,
    JsonObject,
    parse_output_with_formats,
)

# A tool that has JSON formats but plain text in the trajectory can match nothing, so it gets UnmatchedFormat.UNKNOWN.
_NOTHING_MATCHES = HarnessResultFormatList[str](formats=())


def _decode_json(raw_text: str | None) -> dict[str, Any] | None:
    """Decode the raw text as a JSON object. None when it is missing or not a JSON object."""
    if raw_text is None or not raw_text.lstrip().startswith("{"):
        return None
    try:
        decoded = json.loads(raw_text)
    except ValueError:
        return None
    return decoded if isinstance(decoded, dict) else None


class HarnessToolCallConverter:
    """The parts of tool call conversion that differ by harness.

    Each harness declares
    - `text_formats` and `json_formats`, its result formats per tool
    - `stop_tools`, its tools that stop something started earlier
    - `argument_handle_kinds`, the handle kind of its poll tools' arguments

    The shared flow in convert.py calls
    - `parse_output`, which builds a ToolCallOutput from the declared formats through
      `extract_tool_result_raw_text`, `extract_tool_result_json` and `select_formats`.
      A harness overrides a hook when its trajectory differs, and `parse_output` itself
      to add what formats cannot express.
    - `refine_action` and `deferred_action`, which fill the Action fields that catalog
      labels alone cannot express.
    """

    # Tools that stop something started earlier. Their PollAction gets terminate=True.
    stop_tools: ClassVar[frozenset[str]] = frozenset()
    # The kind of the handles a poll tool takes as arguments, for tools whose
    # arguments always name one kind of target.
    argument_handle_kinds: ClassVar[Mapping[str, ExecutionHandleKind]] = {}
    # Result formats per tool name. Tools absent from both get no formats.
    text_formats: ClassVar[Mapping[str, HarnessResultFormatList[str]]] = {}
    json_formats: ClassVar[Mapping[str, HarnessResultFormatList[JsonObject]]] = {}

    def extract_tool_result_raw_text(
        self, raw: RawToolCall, result: dict[str, Any]
    ) -> str | None:
        """Extract the tool result text from the trajectory.

        By default, it is the result's `content` if that is a string, else None.
        """
        content = result.get("content")
        return content if isinstance(content, str) else None

    def extract_tool_result_json(
        self, raw: RawToolCall, result: dict[str, Any]
    ) -> JsonObject | None:
        """Extract the JSON object of the tool result, for a tool with JSON formats.

        By default, it is the raw text decoded as a JSON object. None for a tool
        without JSON formats, or when the raw text holds no JSON object.
        """
        if raw.tool.name not in self.json_formats:
            return None
        raw_text = self.extract_tool_result_raw_text(raw, result)
        return _decode_json(raw_text) or None  # {} has nothing to match

    def select_formats(
        self,
        raw: RawToolCall,
        result: dict[str, Any],
        tool_result_json: JsonObject | None,
    ) -> HarnessResultFormatList[Any] | None:
        """Select harness result formats for the tool.

        By default, a result with a JSON object gets the JSON list, and one without
        gets the text list. None when the tool has no formats, so nothing is tried. A
        tool with only JSON formats gets an empty list for a result without a JSON
        object, so nothing matches.
        """
        name = raw.tool.name
        if tool_result_json is not None:
            return self.json_formats.get(name)
        formats = self.text_formats.get(name)
        if formats is None and name in self.json_formats:
            return _NOTHING_MATCHES
        return formats

    def parse_output(self, raw: RawToolCall, result: dict[str, Any]) -> ToolCallOutput:
        """Parse a tool call result in the trajectory into a ToolCallOutput.

        By default, it runs `parse_output_with_formats` on what the hooks
        `extract_tool_result_raw_text`, `extract_tool_result_json` and `select_formats`
        return. A harness overrides those hooks when its trajectory differs, and this
        method to add what formats cannot express.
        """
        tool_result_json = self.extract_tool_result_json(raw, result)
        selected_formats = self.select_formats(raw, result, tool_result_json)
        return parse_output_with_formats(
            self.extract_tool_result_raw_text(raw, result),
            tool_result_json,
            selected_formats,
        )

    def refine_action(
        self, raw: RawToolCall, action: Action, output: ToolCallOutput | None
    ) -> Action:
        """Fill fields of an Action that the tool call catalog cannot express.

        By default, a PollAction takes the handles the result named, which carry the
        kind the catalog does not know. When the result names none, its argument
        handles take the kind in `argument_handle_kinds`, if the tool has one. A stop
        tool's PollAction is a terminate.
        """
        if not isinstance(action, PollAction):
            return action
        if output is not None and output.handles:
            action = replace(action, handles=output.handles)
        elif kind := self.argument_handle_kinds.get(raw.tool.name):
            handles = tuple(replace(handle, kind=kind) for handle in action.handles)
            action = replace(action, handles=handles)
        if raw.tool.name in self.stop_tools:
            action = replace(action, terminate=True)
        return action

    def deferred_action(
        self, raw: RawToolCall, output: ToolCallOutput | None
    ) -> Action:
        """Decide the Action of a tool labeled Deferred.

        Only harnesses with Deferred tools override this.
        """
        raise NotImplementedError(f"no Deferred handling for {raw.tool}")

    def declared_formats(self) -> list[tuple[str, HarnessResultFormatList[Any]]]:
        """Every format list with the tool it belongs to, for the catalog."""
        return [*self.text_formats.items(), *self.json_formats.items()]
