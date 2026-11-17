"""Tests for tool_call/harnesses/__init__.py, which picks the converter of each harness, against the harness tool catalog and with made-up results."""

import csv
import json
from collections import Counter
from typing import Any

from tb_internet_use.knowledge.tool_call_knowledge import (
    DEFERRED,
    HARNESS_TOOLS_CSV,
    TOOL_CALL_CATALOGS_DIR,
    HarnessToolLabel,
    ToolCallKnowledge,
)
from tb_internet_use.tool_call import convert_tool_calls
from tb_internet_use.tool_call.harnesses import CONVERTERS, converter_for
from tb_internet_use.tool_call.model import (
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    OtherAction,
    RunToolScriptAction,
    ToolCallKey,
    ToolCallResult,
    UnknownAction,
)


def _catalog_tools() -> list[HarnessTool]:
    """List the tools with a row in the committed catalog, read from the CSV itself since a door only answers lookups."""
    with (TOOL_CALL_CATALOGS_DIR / HARNESS_TOOLS_CSV).open(newline="") as f:
        return [HarnessTool(row["harness"], row["tool"]) for row in csv.DictReader(f)]


CATALOG_TOOLS = _catalog_tools()
# The action of each Deferred tool for a call without arguments.
DEFERRED_ACTION_WITHOUT_ARGUMENTS = {
    HarnessTool("codex", "exec"): RunToolScriptAction(),
    HarnessTool("codex", "web_search_call"): UnknownAction(),
    HarnessTool("cursor-cli", "mcpToolCall"): OtherAction(),
}
# Muse Code ends a truncated shell output with this reminder.
MUSE_REMINDER = (
    "\n<system-reminder>\nFull output saved to: /tmp/out.log\n"
    "Full output is longer than the visible window.\n"
    "Use bash tools like head, tail, cat, sed, or grep to inspect and search the full output.\n"
    "</system-reminder>"
)


def _harness_tool_call(
    harness: str, tool: str, args: dict[str, Any], result: dict[str, Any] | None
) -> HarnessToolCall:
    return HarnessToolCall(
        ToolCallKey("t", "main", 1, 0), HarnessTool(harness, tool), "id", args, result
    )


def _converted_result(
    harness_tool_call: HarnessToolCall, judgment_rule_use_counts: Counter[str]
) -> ToolCallResult:
    """Convert one call through `convert_tool_calls`, which picks the converter of its harness."""
    [tool_call] = convert_tool_calls(
        [harness_tool_call],
        knowledge=ToolCallKnowledge(),
        judgment_rule_use_counts=judgment_rule_use_counts,
    )
    assert tool_call.result is not None
    return tool_call.result


def test_every_harness_of_the_catalog_has_a_converter():
    assert set(CONVERTERS) == {tool.harness for tool in CATALOG_TOOLS}


def test_every_deferred_tool_gets_its_action_even_without_arguments():
    knowledge = ToolCallKnowledge()
    deferred_tools = {
        tool
        for tool in CATALOG_TOOLS
        if isinstance(label := knowledge.harness_tool_label(tool), HarnessToolLabel)
        and label.action_type == DEFERRED
    }
    assert deferred_tools == set(DEFERRED_ACTION_WITHOUT_ARGUMENTS)
    for tool, action in DEFERRED_ACTION_WITHOUT_ARGUMENTS.items():
        harness_tool_call = _harness_tool_call(tool.harness, tool.name, {}, None)
        converter = converter_for(tool.harness)
        assert (
            converter.action_of_deferred_tool(
                harness_tool_call, None, knowledge=knowledge
            )
            == action
        ), tool


def test_claude_code_calls_get_the_claude_code_converter():
    # Only the Claude Code converter reads the stdout of the structured result in place of the shown text.
    metadata = {
        "raw_tool_result": {"type": "tool_result", "content": "shown"},
        "tool_use_result": {"stdout": "full\n", "interrupted": False},
    }
    result = {"content": "(harbor view)", "extra": {"tool_result_metadata": metadata}}
    harness_tool_call = _harness_tool_call(
        "claude-code", "Bash", {"command": "x"}, result
    )
    tool_call_result = _converted_result(harness_tool_call, Counter())
    assert tool_call_result.tool_output_text == "full\n"


def test_grok_build_calls_get_the_grok_build_converter():
    # Only the Grok Build converter reads the tasks of a wait on several tasks, by its judgment rule.
    raw_text = "=== Multi-wait (wait_all) ===\n--- Task a1 [completed] ---\nx\n--- Task b2 [completed] ---\ny\n2/2 tasks completed (wait_all)"
    harness_tool_call = _harness_tool_call(
        "grok-build",
        "get_command_or_subagent_output",
        {"task_ids": ["a1", "b2"]},
        {"content": raw_text},
    )
    use_counts: Counter[str] = Counter()
    tool_call_result = _converted_result(harness_tool_call, use_counts)
    assert tool_call_result.execution_status is ExecutionStatus.FINISHED
    assert use_counts == Counter(
        {"treat_wait_on_several_tasks_as_their_shared_status": 1}
    )


def test_muse_code_calls_get_the_muse_code_converter():
    # Only the Muse Code converter cuts the reminder that names the file of the full output.
    content = json.dumps(
        {
            "terminal_status": "completed",
            "exit_code": 0,
            "output": "first lines" + MUSE_REMINDER,
            "truncated": True,
        }
    )
    harness_tool_call = _harness_tool_call(
        "muse-code", "bash", {"command": "x"}, {"content": content}
    )
    tool_call_result = _converted_result(harness_tool_call, Counter())
    assert tool_call_result.output_path == "/tmp/out.log"
