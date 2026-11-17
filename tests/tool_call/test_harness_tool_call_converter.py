"""Tests for the shared converter hooks in harnesses/harness_tool_call_converter.py."""

from collections import Counter

from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge
from tb_internet_use.tool_call.harnesses.harness_tool_call_converter import (
    HarnessToolCallConverter,
)
from tb_internet_use.tool_call.model import (
    ExecutionHandle,
    ExecutionHandleKind,
    HarnessTool,
    HarnessToolCall,
    HarnessToolLabel,
    MatchedFormat,
    PollAction,
    ToolCallKey,
    ToolCallResult,
)

CONVERTER = HarnessToolCallConverter()


def _harness_tool_call(harness: str, tool: str) -> HarnessToolCall:
    return HarnessToolCall(
        ToolCallKey("t", "main", 1, 0),
        HarnessTool(harness, tool),
        "id",
        {},
        None,
    )


def test_tool_result_json_of_decodes_only_a_json_object():
    bash = _harness_tool_call("mini-swe-agent", "bash")
    assert CONVERTER.tool_result_json_of(bash, {"content": '{"a": 1}'}) == {"a": 1}
    assert CONVERTER.tool_result_json_of(bash, {"content": "[1]"}) is None
    assert CONVERTER.tool_result_json_of(bash, {"content": "plain"}) is None
    assert CONVERTER.tool_result_json_of(bash, {}) is None
    assert CONVERTER.tool_result_json_of(bash, {"content": ' {"a": 1}'}) == {"a": 1}
    # An empty object has nothing to match, and broken JSON is no object.
    assert CONVERTER.tool_result_json_of(bash, {"content": "{}"}) is None
    assert CONVERTER.tool_result_json_of(bash, {"content": "{not json"}) is None


def test_tool_result_raw_text_of_reads_only_content_that_is_a_string():
    bash = _harness_tool_call("mini-swe-agent", "bash")
    assert CONVERTER.tool_result_raw_text_of(bash, {"content": "x"}) == "x"
    assert CONVERTER.tool_result_raw_text_of(bash, {"content": ["x"]}) is None


def test_a_tool_without_json_formats_holds_json_text_against_its_text_formats():
    # Claude Code `Bash` has text formats only, so a result that looks like JSON is still its bare output.
    result = {"content": '{"a": 1}'}
    tool_call_result = CONVERTER.convert_result(
        _harness_tool_call("claude-code", "Bash"),
        result,
        knowledge=ToolCallKnowledge(),
        judgment_rule_use_counts=Counter(),
    )
    assert (
        tool_call_result.harness_result_format,
        tool_call_result.tool_output_text,
    ) == (
        MatchedFormat("bare_output"),
        '{"a": 1}',
    )


def test_refine_action_keeps_the_kind_of_the_handles_that_the_result_names():
    label = HarnessToolLabel("PollAction", {}, False, ExecutionHandleKind.COMMAND)
    named = (ExecutionHandle(ExecutionHandleKind.SUBAGENT, "a1"),)
    action = CONVERTER.refine_action(
        _harness_tool_call("muse-code", "subagent_status"),
        PollAction((ExecutionHandle(ExecutionHandleKind.UNKNOWN, "a1"),)),
        ToolCallResult(handles=named),
        label,
    )
    assert action == PollAction(named)
