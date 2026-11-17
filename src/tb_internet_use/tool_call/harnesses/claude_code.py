"""Convert the tool calls of Claude Code, reading the result text and the structured result that Harbor keeps in the trajectory."""

import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from tb_internet_use.tool_call.harnesses.harness_tool_call_converter import (
    HarnessToolCallConverter,
)
from tb_internet_use.tool_call.model import (
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessToolCall,
    MatchedFormat,
    ToolCallResult,
    UnmatchedFormat,
    handles_from_ids,
    join_texts,
)

if TYPE_CHECKING:
    # The door and the declaration types are named in annotations only, so that `convert_tool_calls` never loads `knowledge/` itself.
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
        return _original_text_of(tool_result)[0]

    def tool_result_json_of(
        self, harness_tool_call: HarnessToolCall, tool_result: dict[str, Any]
    ) -> JsonObject | None:
        if harness_tool_call.tool.name == "TaskOutput":
            return structured_result_of(tool_result) or None  # {} has nothing to match
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
        if name == "Read":
            raw_text, item_kinds = _original_text_of(tool_result)
            if raw_text is None and "image" in item_kinds:
                return ToolCallResult(
                    execution_status=S.FINISHED,
                    harness_result_format=MatchedFormat("image"),
                )
        structured = structured_result_of(tool_result)
        tool_call_result = super().convert_result(
            harness_tool_call,
            tool_result,
            knowledge=knowledge,
            judgment_rule_use_counts=judgment_rule_use_counts,
        )
        if isinstance(tool_call_result.harness_result_format, UnmatchedFormat):
            return tool_call_result
        if name == "Bash" and structured:
            return _result_from_structured_bash(tool_call_result, structured)
        if name == "Read":
            return _result_from_structured_read(
                tool_call_result, structured.get("file") or {}
            )
        if name == "WebFetch":
            return _result_from_structured_web_fetch(tool_call_result, structured)
        return tool_call_result


def _original_text_of(tool_result: Mapping[str, Any]) -> tuple[str | None, set[str]]:
    """Read Claude Code's own result text and the kinds of content items it had, e.g. `{"image"}`."""
    block = _metadata_of(tool_result).get("raw_tool_result")
    if isinstance(block, dict):
        content = block.get("content")
        if isinstance(content, list):
            kinds = {
                str(item.get("type")) for item in content if isinstance(item, dict)
            }
            return _join_content_items(content), kinds
        if not isinstance(content, str):
            return None, set()
        return content.strip() or None, set()
    content = tool_result.get("content")
    if not isinstance(content, str):
        return None, set()
    items = _harbor_items_from_content(content)
    if items:
        return _join_content_items(items), {str(item.get("type")) for item in items}
    return content, set()


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
    structured = _metadata_of(tool_result).get("tool_use_result")
    return structured if isinstance(structured, dict) else {}


def _metadata_of(tool_result: Mapping[str, Any]) -> Mapping[str, Any]:
    """Read the part of a result in the trajectory where Harbor keeps Claude Code's own result."""
    return _extra_of(tool_result).get("tool_result_metadata") or {}


def _extra_of(tool_result: Mapping[str, Any]) -> Mapping[str, Any]:
    return tool_result.get("extra") or {}


def _result_from_structured_bash(
    tool_call_result: ToolCallResult, structured: Mapping[str, Any]
) -> ToolCallResult:
    """Prefer the structured stdout, task id and saved-output path over what the text showed."""
    saved_to = structured.get("persistedOutputPath")
    task_id = structured.get("backgroundTaskId")
    exit_code = tool_call_result.exit_code
    if exit_code is None and tool_call_result.execution_status is S.FINISHED:
        exit_code = _exit_code_from_structured_bash(structured)
    # stdout is the whole tool output, since its stderr only holds the cwd notice.
    stdout = structured.get("stdout") or ""
    return replace(
        tool_call_result,
        tool_output_text=stdout,
        exit_code=exit_code,
        handles=handles_from_ids(ExecutionHandleKind.COMMAND, task_id)
        or tool_call_result.handles,
        output_path=saved_to or tool_call_result.output_path,
        is_truncated=True if saved_to else tool_call_result.is_truncated,
    )


def _exit_code_from_structured_bash(structured: Mapping[str, Any]) -> int | None:
    """Derive the exit code of a finished command that Claude Code did not judge an error.

    Grep, find, diff and the like exit 1 without an error.
    Claude Code then names that meaning in `returnCodeInterpretation`, and writes it only for code 1.
    """
    if structured.get("interrupted"):
        return None
    return 1 if structured.get("returnCodeInterpretation") else 0


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
    tool_call_result: ToolCallResult, structured: Mapping[str, Any]
) -> ToolCallResult:
    """Take the HTTP status from the structured result, which has it even when the text does not."""
    code = structured.get("code")
    if isinstance(code, int) and not isinstance(code, bool):
        return replace(tool_call_result, http_status=code)
    return tool_call_result
