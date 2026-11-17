"""Build the `ToolCallResult` of one tool call from the result format that its harness declares for the tool and that `ToolCallKnowledge` finds the result to have."""

from collections import Counter
from typing import TYPE_CHECKING, Any

from tb_internet_use.tool_call.model import (
    ExecutionHandle,
    ExecutionHandleKind,
    HarnessToolCall,
    MatchedFormat,
    ToolCallResult,
    UnmatchedFormat,
    handles_from_ids,
)

if TYPE_CHECKING:
    # The door and the declaration types are named in annotations only, so that `convert_tool_calls` never loads `knowledge/` itself.
    from tb_internet_use.knowledge.harness_result_format_declaration import (
        HarnessResultFormat,
        MatchedHarnessResultFormat,
        MatchedValues,
    )
    from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge

    # `harnesses/harness_tool_call_converter.py` imports this module, so importing the converters here when the module runs would be a cycle.
    from tb_internet_use.tool_call.harnesses.harness_tool_call_converter import (
        HarnessToolCallConverter,
    )


def convert_tool_call_result(
    harness_tool_call: HarnessToolCall,
    converter: HarnessToolCallConverter,
    *,
    knowledge: ToolCallKnowledge,
    judgment_rule_use_counts: Counter[str],
) -> ToolCallResult | None:
    """Build the `ToolCallResult` of one call through the converter of its harness, or None for a call whose trajectory has no result."""
    if harness_tool_call.result is None:
        return None
    return converter.convert_result(
        harness_tool_call,
        harness_tool_call.result,
        knowledge=knowledge,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )


def result_from_harness_result_format(
    tool_result_raw_text: str | None,
    harness_result_format: MatchedHarnessResultFormat | UnmatchedFormat,
) -> ToolCallResult:
    """Build the `ToolCallResult` of a tool result from the declared format that `ToolCallKnowledge.harness_result_format` found for it, or keep its raw text when no format matched."""
    if isinstance(harness_result_format, UnmatchedFormat):
        return _result_from_unmatched_format(
            tool_result_raw_text, harness_result_format
        )
    return _result_from_matched_format(
        harness_result_format.format, harness_result_format.matched_values
    )


def _result_from_unmatched_format(
    tool_result_raw_text: str | None, harness_result_format: UnmatchedFormat
) -> ToolCallResult:
    """A ToolCallResult that keeps the raw text as `tool_output_text`, for a result no format parsed."""
    return ToolCallResult(
        tool_output_text=tool_result_raw_text,
        harness_result_format=harness_result_format,
    )


def _result_from_matched_format(
    fmt: HarnessResultFormat[Any], values: MatchedValues
) -> ToolCallResult:
    """Turn a matched format and its matched values into common types."""
    return ToolCallResult(
        tool_output_text=fmt.tool_output_text_of(values),
        execution_status=fmt.status,
        exit_code=_int_from_matched_values(values, "exit_code"),
        http_status=_int_from_matched_values(values, "http_status"),
        handles=_handles_from_matched_values(fmt.handle_kind_of(values), values),
        output_path=str(values["output_path"]) if values.get("output_path") else None,
        is_truncated=fmt.is_truncated_of(values),
        harness_result_format=MatchedFormat(fmt.name),
    )


def _int_from_matched_values(values: MatchedValues, name: str) -> int | None:
    value = values.get(name)
    if value is None or isinstance(value, bool):
        return None
    return int(value) if isinstance(value, (int, str)) else None


def _handles_from_matched_values(
    kind: ExecutionHandleKind | None, values: MatchedValues
) -> tuple[ExecutionHandle, ...]:
    if kind is None:
        # A format without a handle kind gives no handle, which building the format checks.
        return ()
    return handles_from_ids(kind, values.get("handle")) + handles_from_ids(
        kind, values.get("handles")
    )
