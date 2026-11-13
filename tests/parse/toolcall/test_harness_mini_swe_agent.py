"""mini-swe-agent converter tests, with made-up results shaped as in the trajectories."""

import json
from typing import Any

import pytest

from tb_internet_use.parse.toolcall.convert import convert_call
from tb_internet_use.parse.toolcall.harnesses.mini_swe_agent import (
    MiniSweAgentConverter,
)
from tb_internet_use.parse.toolcall.model import (
    ExecutionStatus,
    HarnessTool,
    RawToolCall,
    ToolCallKey,
    UnmatchedFormat,
)

S = ExecutionStatus
CONVERTER = MiniSweAgentConverter()


def _bash(result: dict[str, Any]):
    raw = RawToolCall(
        ToolCallKey("t", "main", 1, 0),
        HarnessTool("mini-swe-agent", "bash"),
        "id",
        {"command": "x"},
        {"content": json.dumps(result)},
    )
    return convert_call(raw, CONVERTER).output


def test_exited():
    output = _bash({"output": "ok\n", "returncode": 0})
    assert output is not None
    assert (
        output.execution_status,
        output.exit_code,
        output.tool_output_text,
        output.is_truncated,
    ) == (S.FINISHED, 0, "ok\n", None)


@pytest.mark.parametrize("head", ["a\n", "a"])  # a new line is added only when missing
def test_long_output_is_joined_from_head_and_tail_and_flagged(head: str):
    output = _bash(
        {
            "output_head": head,
            "output_tail": "z",
            "elided_chars": 5000,
            "returncode": 1,
            "warning": "Output too long.",
        }
    )
    assert output is not None
    assert (output.tool_output_text, output.is_truncated, output.exit_code) == (
        "a\nz",
        True,
        1,
    )


def test_timeout_and_signal_and_refusal_have_no_exit_code():
    output = _bash(
        {
            "output": "",
            "returncode": -1,
            "exception_info": "An error occurred while executing the command: Command 'x' timed out after 60 seconds",
        }
    )
    assert output is not None and (output.execution_status, output.exit_code) == (
        S.TIMED_OUT,
        None,
    )
    output = _bash({"output": "", "returncode": -9})
    assert output is not None and (output.execution_status, output.exit_code) == (
        S.KILLED,
        None,
    )
    output = _bash(
        {"output": "", "returncode": -1, "exception_info": "action was not executed"}
    )
    assert output is not None and (
        output.execution_status,
        output.exit_code,
        output.tool_output_text,
    ) == (
        S.NOT_RUN,
        None,
        "",
    )


def test_plain_text_result_of_a_json_tool_is_unknown_format():
    raw = RawToolCall(
        ToolCallKey("t", "main", 1, 0),
        HarnessTool("mini-swe-agent", "bash"),
        "id",
        {},
        {"content": "not json"},
    )
    output = convert_call(raw, CONVERTER).output
    assert output is not None and (
        output.harness_result_format,
        output.execution_status,
    ) == (UnmatchedFormat.UNKNOWN, S.UNKNOWN)


def test_unexpected_shape_is_unknown_format_not_a_guess():
    output = _bash({"output": "", "returncode": 0, "exception_info": "other"})
    assert output is not None
    assert output.harness_result_format == UnmatchedFormat.UNKNOWN
