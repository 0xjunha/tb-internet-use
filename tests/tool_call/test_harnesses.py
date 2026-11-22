"""Tests for tool_call/harnesses/__init__.py, which picks the converter of each harness, against the harness tool catalog and with made-up results."""

import csv
import functools
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType
from typing import Any

from tb_internet_use.knowledge.tool_call_knowledge import (
    HARNESS_RETURN_CODE_INTERPRETATIONS_CSV,
    HARNESS_TOOL_ARGUMENTS_CSV,
    HARNESS_TOOLS_CSV,
    TOOL_CALL_CATALOGS_DIR,
    ToolCallKnowledge,
)
from tb_internet_use.tool_call import convert_tool_calls
from tb_internet_use.tool_call.harnesses import CONVERTERS, converter_for
from tb_internet_use.tool_call.harnesses.antigravity_cli import (
    AntigravityCliConverter,
)
from tb_internet_use.tool_call.harnesses.claude_code import ClaudeCodeConverter
from tb_internet_use.tool_call.harnesses.codex import CodexConverter
from tb_internet_use.tool_call.harnesses.copilot_cli import CopilotCliConverter
from tb_internet_use.tool_call.harnesses.cursor_cli import CursorCliConverter
from tb_internet_use.tool_call.harnesses.grok_build import GrokBuildConverter
from tb_internet_use.tool_call.harnesses.harness_tool_call_converter import (
    HarnessToolCallConverter,
)
from tb_internet_use.tool_call.harnesses.muse_code import MuseCodeConverter
from tb_internet_use.tool_call.model import (
    DEFERRED,
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    HarnessToolLabel,
    PollAction,
    ReadFileAction,
    RunToolScriptAction,
    ToolCallKey,
    ToolCallResult,
    UnknownAction,
    WriteFileAction,
)

_SPEC = importlib.util.spec_from_file_location(
    "harness_result_format_audit",
    Path(__file__).parents[2] / "scripts/harness_result_format_audit.py",
)
assert _SPEC is not None and _SPEC.loader is not None
harness_result_format_audit = importlib.util.module_from_spec(_SPEC)
# Registered as an import would do, so that the audit scripts loaded by other tests share it.
sys.modules[_SPEC.name] = harness_result_format_audit
_SPEC.loader.exec_module(harness_result_format_audit)


def _catalog_rows(csv_name: str) -> list[dict[str, str]]:
    """Read the rows of one committed catalog CSV, from the file itself since a knowledge class only answers lookups."""
    with (TOOL_CALL_CATALOGS_DIR / csv_name).open(newline="") as f:
        return list(csv.DictReader(f))


CATALOG_TOOLS = [
    HarnessTool(row["harness"], row["tool"]) for row in _catalog_rows(HARNESS_TOOLS_CSV)
]
# The action of each Deferred tool for a call without arguments.
DEFERRED_ACTION_WITHOUT_ARGUMENTS = {
    HarnessTool("antigravity-cli", "manage_task"): UnknownAction(),
    HarnessTool("antigravity-cli", "SYSTEM_MESSAGE"): UnknownAction(),
    HarnessTool("antigravity-cli", "write_file"): WriteFileAction(),
    HarnessTool("claude-code", "task-notification"): UnknownAction(),
    HarnessTool("codex", "exec"): RunToolScriptAction(),
    HarnessTool("codex", "web_search_call"): UnknownAction(),
    HarnessTool("copilot-cli", "apply_patch"): UnknownAction(),
    HarnessTool("copilot-cli", "view"): ReadFileAction(),
    HarnessTool("cursor-cli", "mcpToolCall"): UnknownAction(),
    HarnessTool("grok-build", "system-reminder"): UnknownAction(),
}
# Muse Code ends a truncated shell output with this reminder.
MUSE_REMINDER = (
    "\n<system-reminder>\nFull output saved to: /tmp/out.log\n"
    "Full output is longer than the visible window.\n"
    "Use bash tools like head, tail, cat, sed, or grep to inspect and search the full output.\n"
    "</system-reminder>"
)


@functools.cache
def _test_module_of(harness: str) -> ModuleType:
    """Load the test file of a harness, e.g. `test_harness_grok_build.py` for `grok-build`, to read its case tables."""
    file = Path(__file__).parent / f"test_harness_{harness.replace('-', '_')}.py"
    spec = importlib.util.spec_from_file_location(f"{file.stem}_cases", file)
    assert spec is not None and spec.loader is not None, file
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result_format_case_keys_of(harness: str) -> frozenset[tuple[str, str]]:
    """Read the tool and the expected format name of every row of `RESULT_FORMAT_CASES` in the test file of a harness."""
    return frozenset(
        (tool, str(expected.harness_result_format))
        for tool, _, expected in _test_module_of(harness).RESULT_FORMAT_CASES
    )


def _action_case_keys_of(harness: str) -> frozenset[tuple[str, str]]:
    """Read the tool and every argument name of every row of `ACTION_CASES` in the test file of a harness."""
    return frozenset(
        (tool, argument)
        for tool, args, _ in _test_module_of(harness).ACTION_CASES
        for argument in args
    )


def _return_code_interpretation_case_keys_of(
    harness: str,
) -> frozenset[tuple[str, str, int]]:
    """Read the tool, the text and the exit code of every row of `RETURN_CODE_INTERPRETATION_CASES` in the test file of a harness."""
    return frozenset(_test_module_of(harness).RETURN_CODE_INTERPRETATION_CASES)


def _action_case_tools_of(harness: str) -> frozenset[str]:
    """Read the tool of every row of `ACTION_CASES` in the test file of a harness."""
    return frozenset(tool for tool, _, _ in _test_module_of(harness).ACTION_CASES)


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


def test_every_declared_result_format_has_a_case_in_the_test_file_of_its_harness():
    missing = [
        (harness, tool, harness_result_format.name)
        for harness, tool, harness_result_format in harness_result_format_audit.iter_declared_formats()
        if (tool, harness_result_format.name)
        not in _result_format_case_keys_of(harness)
    ]
    assert not missing, "declared result formats without a row in RESULT_FORMAT_CASES"


def test_every_argument_row_of_the_catalog_has_a_case_in_the_test_file_of_its_harness():
    missing = [
        (row["harness"], row["tool"], row["argument"])
        for row in _catalog_rows(HARNESS_TOOL_ARGUMENTS_CSV)
        if (row["tool"], row["argument"]) not in _action_case_keys_of(row["harness"])
    ]
    assert not missing, "argument rows without a row in ACTION_CASES"


def test_every_return_code_interpretation_row_of_the_catalog_has_a_case_with_its_exit_code():
    missing = [
        (row["harness"], row["tool"], row["return_code_interpretation"])
        for row in _catalog_rows(HARNESS_RETURN_CODE_INTERPRETATIONS_CSV)
        if (row["tool"], row["return_code_interpretation"], int(row["exit_code"]))
        not in _return_code_interpretation_case_keys_of(row["harness"])
    ]
    assert not missing, (
        "return code interpretation rows without a row in RETURN_CODE_INTERPRETATION_CASES"
    )


def test_every_poll_tool_of_the_catalog_has_a_case_that_states_its_terminate():
    # A `stops_execution` that flips would change only `terminate`, which every poll case states.
    missing = [
        (row["harness"], row["tool"])
        for row in _catalog_rows(HARNESS_TOOLS_CSV)
        if row["action_type"] == PollAction.__name__
        and row["tool"] not in _action_case_tools_of(row["harness"])
    ]
    assert not missing, "poll tools without a row in ACTION_CASES"


def test_every_harness_of_the_catalog_has_a_converter():
    assert set(CONVERTERS) == {tool.harness for tool in CATALOG_TOOLS}


def test_each_harness_gets_the_converter_of_its_own_class():
    converter_classes = {
        harness: type(converter_for(harness)) for harness in CONVERTERS
    }
    assert converter_classes == {
        "antigravity-cli": AntigravityCliConverter,
        "claude-code": ClaudeCodeConverter,
        "codex": CodexConverter,
        "copilot-cli": CopilotCliConverter,
        "cursor-cli": CursorCliConverter,
        "devin": HarnessToolCallConverter,
        "grok-build": GrokBuildConverter,
        "mini-swe-agent": HarnessToolCallConverter,
        "muse-code": MuseCodeConverter,
    }


def test_every_deferred_tool_gets_its_action_even_without_arguments():
    knowledge = ToolCallKnowledge()
    deferred_tools = {
        tool
        for tool in CATALOG_TOOLS
        if isinstance(label := knowledge.harness_tool_label(tool, ()), HarnessToolLabel)
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


def test_copilot_cli_calls_get_the_copilot_cli_converter():
    # Only the Copilot CLI converter cuts the JSON line that ends every result.
    content = 'hi\n<shellId: 4 completed with exit code 0>\n{"detailedContent": "hi"}'
    harness_tool_call = _harness_tool_call(
        "copilot-cli", "bash", {"command": "x"}, {"content": content}
    )
    tool_call_result = _converted_result(harness_tool_call, Counter())
    assert (tool_call_result.tool_output_text, tool_call_result.exit_code) == ("hi", 0)


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
