"""Tests for the shared converter hooks in harnesses/base.py."""

from tb_internet_use.toolcall.harnesses.mini_swe_agent import MiniSweAgentConverter
from tb_internet_use.toolcall.model import HarnessTool, RawToolCall, ToolCallKey

CONVERTER = MiniSweAgentConverter()  # its bash tool has JSON formats


def _raw(tool: str) -> RawToolCall:
    return RawToolCall(
        ToolCallKey("t", "main", 1, 0),
        HarnessTool("mini-swe-agent", tool),
        "id",
        {},
        None,
    )


def test_extract_tool_result_json_decodes_only_a_json_object_for_a_json_tool():
    bash = _raw("bash")
    assert CONVERTER.extract_tool_result_json(bash, {"content": '{"a": 1}'}) == {"a": 1}
    assert CONVERTER.extract_tool_result_json(bash, {"content": "[1]"}) is None
    assert CONVERTER.extract_tool_result_json(bash, {"content": "plain"}) is None
    assert CONVERTER.extract_tool_result_json(bash, {}) is None
    other = _raw("submit")  # a tool without JSON formats has no JSON object
    assert CONVERTER.extract_tool_result_json(other, {"content": '{"a": 1}'}) is None
