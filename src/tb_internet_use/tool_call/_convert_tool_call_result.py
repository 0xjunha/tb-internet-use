"""Build the `ToolCallResult` of one tool call from the result format that its harness declares for the tool and that `ToolCallKnowledge` finds the result to have."""

from collections import Counter
from typing import TYPE_CHECKING, Any

from tb_internet_use.tool_call import judgment_rules
from tb_internet_use.tool_call.model import (
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
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
    *,
    judgment_rule_use_counts: Counter[str],
) -> ToolCallResult:
    """Build the `ToolCallResult` of a tool result from the declared format that `ToolCallKnowledge.harness_result_format` found for it, or keep its raw text when no format matched.

    A format that names a rule of `judgment_rules.py` gets its status from that rule, which counts the use in `judgment_rule_use_counts`.
    """
    if isinstance(harness_result_format, UnmatchedFormat):
        return _result_from_unmatched_format(
            tool_result_raw_text, harness_result_format
        )
    return _result_from_matched_format(
        harness_result_format.format,
        harness_result_format.matched_values,
        judgment_rule_use_counts=judgment_rule_use_counts,
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
    fmt: HarnessResultFormat[Any],
    values: MatchedValues,
    *,
    judgment_rule_use_counts: Counter[str],
) -> ToolCallResult:
    """Turn a matched format and its matched values into common types, with the status the format states or the one its judgment rule decides."""
    tool_call_result = ToolCallResult(
        tool_output_text=fmt.tool_output_text_of(values),
        # A format without a status names a judgment rule, which building the format checks, and the rule decides the status below.
        execution_status=ExecutionStatus.UNKNOWN if fmt.status is None else fmt.status,
        exit_code=_int_from_matched_values(values, "exit_code"),
        http_status=_int_from_matched_values(values, "http_status"),
        handles=_handles_from_matched_values(fmt.handle_kind_of(values), values),
        output_path=str(values["output_path"]) if values.get("output_path") else None,
        is_truncated=fmt.is_truncated_of(values),
        harness_result_format=MatchedFormat(fmt.name),
    )
    if fmt.judgment_rule is None:
        return tool_call_result
    # A test checks that every rule a declared format names is a function of `judgment_rules.py`.
    judgment_rule = getattr(judgment_rules, fmt.judgment_rule)
    return judgment_rule(tool_call_result, use_counts=judgment_rule_use_counts)


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
