"""Tests for tool_call/_convert_tool_call_action.py, which turns the arguments of a call into the fields of its action, with made-up calls of tools in the catalog."""

from collections import Counter

import pytest

from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge
from tb_internet_use.tool_call._convert_tool_calls import convert_one_tool_call
from tb_internet_use.tool_call.harnesses import converter_for
from tb_internet_use.tool_call.model import (
    EditFileAction,
    HarnessTool,
    HarnessToolCall,
    ReadFileAction,
    ToolCallKey,
    WebFetchAction,
    WriteFileAction,
)

# (tool of Claude Code, arguments of a call, action of the call), one case per kind of field value.
FIELD_VALUE_CASES = [
    # One URL becomes a tuple of URLs.
    ("WebFetch", {"url": "http://x"}, WebFetchAction(("http://x",))),
    # A limit that is no whole number is dropped.
    (
        "Read",
        {"file_path": "/a", "offset": 2, "limit": "x"},
        ReadFileAction("/a", 2, None),
    ),
    # Any other field takes the argument as it is.
    ("Write", {"file_path": "/a", "content": "x"}, WriteFileAction("/a", "x")),
    (
        "Edit",
        {"file_path": "/a", "old_string": "o", "new_string": "n"},
        EditFileAction("/a", "o", "n"),
    ),
]


@pytest.mark.parametrize(("tool", "args", "action"), FIELD_VALUE_CASES)
def test_each_argument_takes_the_type_of_its_action_field(tool, args, action):
    harness_tool_call = HarnessToolCall(
        ToolCallKey("t", "main", 1, 0),
        HarnessTool("claude-code", tool),
        "id",
        args,
        None,
    )
    tool_call = convert_one_tool_call(
        harness_tool_call,
        converter_for("claude-code"),
        knowledge=ToolCallKnowledge(),
        judgment_rule_use_counts=Counter(),
    )
    assert tool_call.action == action
