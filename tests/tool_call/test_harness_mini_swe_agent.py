"""Test the conversion of mini-swe-agent tool calls, which use the shared converter, with made-up results shaped as in the trajectories."""

import json
from collections import Counter
from typing import Any

import pytest

from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge
from tb_internet_use.tool_call import convert_tool_calls
from tb_internet_use.tool_call._convert_tool_calls import convert_one_tool_call
from tb_internet_use.tool_call.harnesses import converter_for
from tb_internet_use.tool_call.model import (
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    MatchedFormat,
    RunCommandAction,
    ToolCallAction,
    ToolCallKey,
    ToolCallResult,
    UnmatchedFormat,
)
from tb_internet_use.tool_call.parse_shell_text import parse_shell_text

S = ExecutionStatus
CONVERTER = converter_for("mini-swe-agent")
_TIMED_OUT = "An error occurred while executing the command: Command 'x' timed out after 60 seconds"

# One made-up result per declared result format of mini-swe-agent, built from the format, and the `ToolCallResult` it converts to.
# (tool, result object of the JSON text in the trajectory, expected result)
RESULT_FORMAT_CASES: list[tuple[str, dict[str, Any], ToolCallResult]] = [
    (
        "bash",
        {"output": "", "returncode": -1, "exception_info": "action was not executed"},
        ToolCallResult(
            "", S.NOT_RUN, harness_result_format=MatchedFormat("not_executed")
        ),
    ),
    (
        "bash",
        {"output": "partial", "returncode": -1, "exception_info": _TIMED_OUT},
        ToolCallResult(
            "partial", S.TIMED_OUT, harness_result_format=MatchedFormat("timed_out")
        ),
    ),
    (
        "bash",
        {
            "output_head": "a\n",
            "output_tail": "z",
            "elided_chars": 10,
            "returncode": -1,
            "exception_info": _TIMED_OUT,
        },
        ToolCallResult(
            "a\nz",
            S.TIMED_OUT,
            is_truncated=True,
            harness_result_format=MatchedFormat("timed_out_truncated"),
        ),
    ),
    (
        "bash",
        {"output": "x", "returncode": -9},
        ToolCallResult("x", S.KILLED, harness_result_format=MatchedFormat("killed")),
    ),
    (
        "bash",
        {"output_head": "a", "output_tail": "z", "elided_chars": 5, "returncode": -15},
        ToolCallResult(
            "a\nz",
            S.KILLED,
            is_truncated=True,
            harness_result_format=MatchedFormat("killed_truncated"),
        ),
    ),
    (
        "bash",
        {"output": "ok\n", "returncode": 0},
        ToolCallResult(
            "ok\n", S.FINISHED, 0, harness_result_format=MatchedFormat("exited")
        ),
    ),
    (
        "bash",
        {
            "output_head": "a\n",
            "output_tail": "z",
            "elided_chars": 5000,
            "returncode": 1,
        },
        ToolCallResult(
            "a\nz",
            S.FINISHED,
            1,
            is_truncated=True,
            harness_result_format=MatchedFormat("exited_truncated"),
        ),
    ),
]


# A made-up call of each tool with argument rows in the harness tool catalog, or whose action is a poll, and the `ToolCallAction` it converts to without a result.
# Every argument row has a case, and every `PollAction` states its `terminate`.
# (tool, arguments in the trajectory, expected action)
ACTION_CASES: list[tuple[str, dict[str, Any], ToolCallAction]] = [
    (
        "bash",
        {"command": "ls /app"},
        RunCommandAction(
            "ls /app", parse_shell_text("ls /app", judgment_rule_use_counts=Counter())
        ),
    ),
]


def _converted_result(tool: str, result: dict[str, Any]) -> ToolCallResult | None:
    harness_tool_call = HarnessToolCall(
        ToolCallKey("t", "main", 1, 0),
        HarnessTool("mini-swe-agent", tool),
        "id",
        {"command": "x"},
        result,
    )
    return convert_one_tool_call(
        harness_tool_call,
        CONVERTER,
        knowledge=ToolCallKnowledge(),
        judgment_rule_use_counts=Counter(),
    ).result


def _action_of_call_without_result(tool: str, args: dict[str, Any]) -> ToolCallAction:
    """Convert one call of mini-swe-agent without a result through `convert_tool_calls`, which picks the converter of the harness, and give its action."""
    [tool_call] = convert_tool_calls(
        [
            HarnessToolCall(
                ToolCallKey("t", "main", 1, 0),
                HarnessTool("mini-swe-agent", tool),
                "id",
                args,
                None,
            )
        ],
        knowledge=ToolCallKnowledge(),
        judgment_rule_use_counts=Counter(),
    )
    return tool_call.action


def _bash(result: dict[str, Any]) -> ToolCallResult | None:
    return _converted_result("bash", {"content": json.dumps(result)})


@pytest.mark.parametrize(("tool", "args", "expected"), ACTION_CASES)
def test_a_call_of_each_tool_converts_to_the_action_of_its_arguments(
    tool: str, args: dict[str, Any], expected: ToolCallAction
):
    assert _action_of_call_without_result(tool, args) == expected


@pytest.mark.parametrize(("tool", "result", "expected"), RESULT_FORMAT_CASES)
def test_a_result_of_each_declared_format_converts_to_its_fields(
    tool: str, result: dict[str, Any], expected: ToolCallResult
):
    assert _converted_result(tool, {"content": json.dumps(result)}) == expected


@pytest.mark.parametrize("head", ["a\n", "a"])  # a new line is added only when missing
def test_long_output_is_joined_from_head_and_tail_and_flagged(head: str):
    tool_call_result = _bash(
        {
            "output_head": head,
            "output_tail": "z",
            "elided_chars": 5000,
            "returncode": 1,
            "warning": "Output too long.",
        }
    )
    assert tool_call_result is not None
    assert (
        tool_call_result.tool_output_text,
        tool_call_result.is_truncated,
        tool_call_result.exit_code,
    ) == (
        "a\nz",
        True,
        1,
    )


def test_plain_text_result_of_a_json_tool_is_unknown_format():
    tool_call_result = _converted_result("bash", {"content": "not json"})
    assert tool_call_result is not None and (
        tool_call_result.harness_result_format,
        tool_call_result.execution_status,
    ) == (UnmatchedFormat.UNKNOWN, S.UNKNOWN)


def test_unexpected_shape_is_unknown_format_not_a_guess():
    tool_call_result = _bash({"output": "", "returncode": 0, "exception_info": "other"})
    assert tool_call_result is not None
    assert tool_call_result.harness_result_format == UnmatchedFormat.UNKNOWN
