"""Convert the tool calls of Claude Code, reading the result text and the structured result that Harbor keeps in the trajectory, and the task notifications that report the end of a background task."""

import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from tb_internet_use.tool_call.harnesses.harness_tool_call_converter import (
    HarnessToolCallConverter,
    action_from_harness_message_result,
)
from tb_internet_use.tool_call.judgment_rules import (
    treat_bash_output_without_exit_code_line_as_exit_code_0,
)
from tb_internet_use.tool_call.model import (
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    ToolCallAction,
    ToolCallResult,
    UnknownHarnessReturnCodeInterpretation,
    UnmatchedFormat,
    handles_from_ids,
    join_texts,
)

if TYPE_CHECKING:
    # `ToolCallKnowledge` and the declaration types are named in annotations only, so that `convert_tool_calls` never loads `knowledge/` itself.
    from tb_internet_use.knowledge.harness_result_format_declaration import (
        JsonObject,
    )
    from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge

S = ExecutionStatus

_ITEM_TYPES = (
    "text",
    "image",
    "tool_reference",
    "document",
)  # content items Harbor writes as JSON


class ClaudeCodeConverter(HarnessToolCallConverter):
    def tool_result_raw_text_of(
        self, harness_tool_call: HarnessToolCall, tool_result: dict[str, Any]
    ) -> str | None:
        """Read Claude Code's own result text, which Harbor keeps in `extra.tool_result_metadata.raw_tool_result`.

        `content` is read only when that is missing.
        Text from `raw_tool_result` loses its edge whitespace, and content items are joined.
        """
        return _raw_text_and_content_items_of(tool_result)[0]

    def tool_result_json_of(
        self, harness_tool_call: HarnessToolCall, tool_result: dict[str, Any]
    ) -> JsonObject | None:
        """Read the structured result of `TaskOutput`, and the only content item of a `Read` result without text, e.g. the image a `Read` of an image file returns.

        Any other `Read` result has text, which its text formats read, so it gives None.
        Any other tool with JSON formats, e.g. `TaskStop`, gets the default, the raw text decoded as a JSON object.
        """
        name = harness_tool_call.tool.name
        if name == "TaskOutput":
            return structured_result_of(tool_result) or None  # {} has nothing to match
        if name == "Read":
            return _only_content_item_of_result_without_text(tool_result)
        return super().tool_result_json_of(harness_tool_call, tool_result)

    def is_marked_as_error(
        self, harness_tool_call: HarnessToolCall, tool_result: dict[str, Any]
    ) -> bool:
        return bool(_extra_of(tool_result).get("tool_result_is_error"))

    def convert_result(
        self,
        harness_tool_call: HarnessToolCall,
        tool_result: dict[str, Any],
        *,
        knowledge: ToolCallKnowledge,
        judgment_rule_use_counts: Counter[str],
    ) -> ToolCallResult:
        name = harness_tool_call.tool.name
        structured_result = structured_result_of(tool_result)
        tool_call_result = super().convert_result(
            harness_tool_call,
            tool_result,
            knowledge=knowledge,
            judgment_rule_use_counts=judgment_rule_use_counts,
        )
        if isinstance(tool_call_result.harness_result_format, UnmatchedFormat):
            return tool_call_result
        if name == "Bash" and structured_result:
            return _result_from_structured_bash(
                tool_call_result,
                structured_result,
                harness_tool_call.tool,
                knowledge=knowledge,
                judgment_rule_use_counts=judgment_rule_use_counts,
            )
        if name == "Read":
            return _result_from_structured_read(
                tool_call_result, structured_result.get("file") or {}
            )
        if name == "WebFetch":
            return _result_from_structured_web_fetch(
                tool_call_result, structured_result
            )
        return tool_call_result

    def action_of_deferred_tool(
        self,
        harness_tool_call: HarnessToolCall,
        tool_call_result: ToolCallResult | None,
        *,
        knowledge: ToolCallKnowledge,
    ) -> ToolCallAction:
        """Build the action of a `task-notification` block, the only Deferred tool of Claude Code, a poll of the task it names."""
        return action_from_harness_message_result(tool_call_result)


def _only_content_item_of_result_without_text(
    tool_result: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Find the one content item of a result that has no text, or None for a result with text or with another number of items."""
    raw_text, items = _raw_text_and_content_items_of(tool_result)
    if raw_text is None and len(items) == 1:
        return items[0]
    return None


def _raw_text_and_content_items_of(
    tool_result: Mapping[str, Any],
) -> tuple[str | None, list[dict[str, Any]]]:
    """Read Claude Code's own result text and the content items it had, e.g. one image item."""
    block = _metadata_of(tool_result).get("raw_tool_result")
    if isinstance(block, dict):
        content = block.get("content")
        if isinstance(content, list):
            items = [item for item in content if isinstance(item, dict)]
            return _join_content_items(content), items
        if not isinstance(content, str):
            return None, []
        return content.strip() or None, []
    content = tool_result.get("content")
    if not isinstance(content, str):
        return None, []
    items = _harbor_items_from_content(content)
    if items:
        return _join_content_items(items), items
    return content, []


def _harbor_items_from_content(content: str) -> list[dict[str, Any]] | None:
    """Read the content items that Harbor wrote as JSON, one per paragraph, or None when the content is plain text."""
    items: list[dict[str, Any]] = []
    for part in content.split("\n\n"):
        try:
            item = json.loads(part)
        except ValueError:
            return None
        if not (isinstance(item, dict) and item.get("type") in _ITEM_TYPES):
            return None
        items.append(item)
    return items


def _join_content_items(items: Any) -> str | None:
    """Join the text of a list of content items such as `{"type": "text", "text": ...}`. Images give nothing."""
    if not isinstance(items, list):
        return None
    return join_texts(
        str(item.get("text") or "")
        for item in items
        if isinstance(item, dict) and item.get("type") == "text"
    )


def structured_result_of(tool_result: Mapping[str, Any]) -> dict[str, Any]:
    """Read Claude Code's structured result (`tool_use_result`), which most calls carry, or {} without one."""
    structured_result = _metadata_of(tool_result).get("tool_use_result")
    return structured_result if isinstance(structured_result, dict) else {}


def _metadata_of(tool_result: Mapping[str, Any]) -> Mapping[str, Any]:
    """Read the part of a result in the trajectory where Harbor keeps Claude Code's own result."""
    return _extra_of(tool_result).get("tool_result_metadata") or {}


def _extra_of(tool_result: Mapping[str, Any]) -> Mapping[str, Any]:
    return tool_result.get("extra") or {}


def _result_from_structured_bash(
    tool_call_result: ToolCallResult,
    structured_result: Mapping[str, Any],
    tool: HarnessTool,
    *,
    knowledge: ToolCallKnowledge,
    judgment_rule_use_counts: Counter[str],
) -> ToolCallResult:
    """Prefer the structured stdout, task id and saved-output path over what the text showed."""
    saved_to = structured_result.get("persistedOutputPath")
    task_id = structured_result.get("backgroundTaskId")
    if (
        tool_call_result.exit_code is None
        and tool_call_result.execution_status is S.FINISHED
    ):
        tool_call_result = _result_with_exit_code_from_structured_bash(
            tool_call_result,
            structured_result,
            tool,
            knowledge=knowledge,
            judgment_rule_use_counts=judgment_rule_use_counts,
        )
    # stdout is the whole tool output, since its stderr only holds the cwd notice.
    stdout = structured_result.get("stdout") or ""
    return replace(
        tool_call_result,
        tool_output_text=stdout,
        handles=handles_from_ids(ExecutionHandleKind.COMMAND, task_id)
        or tool_call_result.handles,
        output_path=saved_to or tool_call_result.output_path,
        is_truncated=True if saved_to else tool_call_result.is_truncated,
    )


def _result_with_exit_code_from_structured_bash(
    tool_call_result: ToolCallResult,
    structured_result: Mapping[str, Any],
    tool: HarnessTool,
    *,
    knowledge: ToolCallKnowledge,
    judgment_rule_use_counts: Counter[str],
) -> ToolCallResult:
    """Give an exit code to a finished command that Claude Code did not judge an error, which its result text leaves out.

    Grep, find, diff and the like exit 1 without an error.
    Claude Code then names that meaning in `returnCodeInterpretation`, e.g. `No matches found`, and `knowledge` tells which exit code the text stands for.
    Any value of the key other than null is looked up, so that an empty text or a value that is no text finds no row and is counted as an unknown input instead of getting 0.
    A text that `knowledge` does not know leaves the exit code unknown.
    An interrupted command keeps no exit code, and any other gets 0 by a judgment rule.
    """
    if structured_result.get("interrupted"):
        return tool_call_result
    return_code_interpretation = structured_result.get("returnCodeInterpretation")
    if return_code_interpretation is not None:
        exit_code = knowledge.exit_code_of_harness_return_code_interpretation(
            tool, str(return_code_interpretation)
        )
        if isinstance(exit_code, UnknownHarnessReturnCodeInterpretation):
            return tool_call_result
        return replace(tool_call_result, exit_code=exit_code)
    return treat_bash_output_without_exit_code_line_as_exit_code_0(
        tool_call_result, use_counts=judgment_rule_use_counts
    )


def _result_from_structured_read(
    tool_call_result: ToolCallResult, file: Mapping[str, Any]
) -> ToolCallResult:
    """Prefer the structured file content, and mark a read Claude Code cut at its token cap."""
    content = file.get("content")
    if isinstance(content, str):
        tool_call_result = replace(tool_call_result, tool_output_text=content)
    if file.get("truncatedByTokenCap") is True:
        tool_call_result = replace(tool_call_result, is_truncated=True)
    return tool_call_result


def _result_from_structured_web_fetch(
    tool_call_result: ToolCallResult, structured_result: Mapping[str, Any]
) -> ToolCallResult:
    """Take the HTTP status from the structured result, which has it even when the text does not."""
    code = structured_result.get("code")
    if isinstance(code, int) and not isinstance(code, bool):
        return replace(tool_call_result, http_status=code)
    return tool_call_result
