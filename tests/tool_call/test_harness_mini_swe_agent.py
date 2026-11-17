"""mini-swe-agent converter tests, with made-up results shaped as in the trajectories."""

import json
from collections import Counter
from typing import Any

import pytest

from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge
from tb_internet_use.tool_call._convert_tool_calls import convert_one_tool_call
from tb_internet_use.tool_call.harnesses import converter_for
from tb_internet_use.tool_call.model import (
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    ToolCallKey,
    UnmatchedFormat,
)

S = ExecutionStatus
CONVERTER = converter_for("mini-swe-agent")


def _bash(result: dict[str, Any]):
    harness_tool_call = HarnessToolCall(
        ToolCallKey("t", "main", 1, 0),
        HarnessTool("mini-swe-agent", "bash"),
        "id",
        {"command": "x"},
        {"content": json.dumps(result)},
    )
    return convert_one_tool_call(
        harness_tool_call,
        CONVERTER,
        knowledge=ToolCallKnowledge(),
        judgment_rule_use_counts=Counter(),
    ).result


def test_exited():
    tool_call_result = _bash({"output": "ok\n", "returncode": 0})
    assert tool_call_result is not None
    assert (
        tool_call_result.execution_status,
        tool_call_result.exit_code,
        tool_call_result.tool_output_text,
        tool_call_result.is_truncated,
    ) == (S.FINISHED, 0, "ok\n", None)


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


def test_timeout_and_signal_and_refusal_have_no_exit_code():
    tool_call_result = _bash(
        {
            "output": "",
            "returncode": -1,
            "exception_info": "An error occurred while executing the command: Command 'x' timed out after 60 seconds",
        }
    )
    assert tool_call_result is not None and (
        tool_call_result.execution_status,
        tool_call_result.exit_code,
    ) == (
        S.TIMED_OUT,
        None,
    )
    tool_call_result = _bash({"output": "", "returncode": -9})
    assert tool_call_result is not None and (
        tool_call_result.execution_status,
        tool_call_result.exit_code,
    ) == (
        S.KILLED,
        None,
    )
    tool_call_result = _bash(
        {"output": "", "returncode": -1, "exception_info": "action was not executed"}
    )
    assert tool_call_result is not None and (
        tool_call_result.execution_status,
        tool_call_result.exit_code,
        tool_call_result.tool_output_text,
    ) == (
        S.NOT_RUN,
        None,
        "",
    )


def test_plain_text_result_of_a_json_tool_is_unknown_format():
    harness_tool_call = HarnessToolCall(
        ToolCallKey("t", "main", 1, 0),
        HarnessTool("mini-swe-agent", "bash"),
        "id",
        {},
        {"content": "not json"},
    )
    tool_call_result = convert_one_tool_call(
        harness_tool_call,
        CONVERTER,
        knowledge=ToolCallKnowledge(),
        judgment_rule_use_counts=Counter(),
    ).result
    assert tool_call_result is not None and (
        tool_call_result.harness_result_format,
        tool_call_result.execution_status,
    ) == (UnmatchedFormat.UNKNOWN, S.UNKNOWN)


def test_unexpected_shape_is_unknown_format_not_a_guess():
    tool_call_result = _bash({"output": "", "returncode": 0, "exception_info": "other"})
    assert tool_call_result is not None
    assert tool_call_result.harness_result_format == UnmatchedFormat.UNKNOWN
