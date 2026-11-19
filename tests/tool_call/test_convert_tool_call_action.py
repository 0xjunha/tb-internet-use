"""Tests for tool_call/_convert_tool_call_action.py, which turns the arguments of a call into the fields of its action, with made-up calls of tools in the catalog."""

from collections import Counter
from typing import Any

import pytest

from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge
from tb_internet_use.tool_call import convert_tool_calls
from tb_internet_use.tool_call._convert_tool_calls import convert_one_tool_call
from tb_internet_use.tool_call.harnesses import converter_for
from tb_internet_use.tool_call.judgment_rules import (
    treat_lines_joined_after_three_repairs_as_left_joined,
)
from tb_internet_use.tool_call.model import (
    EditFileAction,
    ExitOutcome,
    FileDestination,
    HarnessTool,
    HarnessToolCall,
    ParsedShellText,
    ReadFileAction,
    RunCommandAction,
    RunCondition,
    RunToolScriptAction,
    ShellCommand,
    ToolCallAction,
    ToolCallKey,
    VariableAssignment,
    WebFetchAction,
    WriteFileAction,
)


def _action_and_judgment_rule_use_counts_from(
    harness: str, tool: str, args: dict[str, Any]
) -> tuple[ToolCallAction, Counter[str]]:
    """Convert one call without a result through `convert_tool_calls`, giving its action and the uses of judgment rules that `convert_tool_calls` counts."""
    judgment_rule_use_counts: Counter[str] = Counter()
    (tool_call,) = convert_tool_calls(
        [
            HarnessToolCall(
                ToolCallKey("t", "main", 1, 0),
                HarnessTool(harness, tool),
                "id",
                args,
                None,
            )
        ],
        knowledge=ToolCallKnowledge(),
        judgment_rule_use_counts=judgment_rule_use_counts,
    )
    return tool_call.action, judgment_rule_use_counts


def _command_ids_of(action: ToolCallAction) -> list[int]:
    assert isinstance(action, RunCommandAction)
    assert isinstance(action.parsed_shell_text, ParsedShellText)
    return [command.id for command in action.parsed_shell_text.commands]


# (tool of Claude Code, arguments of a call, action of the call), for a field of several values, a whole number field and fields that take the argument as it is.
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


def test_command_string_of_a_labeled_tool_is_split_as_a_shell_text_of_its_own():
    # The shell text is split with ids from 0, without a runner and without `set` arguments at its start, so `cd` does not decide whether `curl` runs.
    shell_text = "U=u; cd /app; curl -s $U > log 2>&1 && tail -1 log"
    action, _judgment_rule_use_counts = _action_and_judgment_rule_use_counts_from(
        "claude-code", "Bash", {"command": shell_text}
    )
    assert action == RunCommandAction(
        shell_text,
        ParsedShellText(
            (
                ShellCommand(0, ("cd", "/app")),
                ShellCommand(
                    1,
                    ("curl", "-s", "$U"),
                    expansion_word_indexes=(2,),
                    stdout=FileDestination("log", False),
                    stderr=FileDestination("log", False),
                    succeeded_if_text_exits_zero=True,
                ),
                ShellCommand(
                    2,
                    ("tail", "-1", "log"),
                    runs_if=(RunCondition((1,), ExitOutcome.SUCCESS),),
                    succeeded_if_text_exits_zero=True,
                ),
            ),
            (VariableAssignment("U", "u", 0, None),),
        ),
    )


def test_command_string_of_a_labeled_tool_is_split_and_its_rule_uses_counted(
    shell_text_joined_after_three_repairs: str,
):
    action, judgment_rule_use_counts = _action_and_judgment_rule_use_counts_from(
        "claude-code", "Bash", {"command": shell_text_joined_after_three_repairs}
    )
    assert isinstance(action, RunCommandAction)
    assert isinstance(action.parsed_shell_text, ParsedShellText)
    assert all(
        command.structure_may_be_wrong for command in action.parsed_shell_text.commands
    )
    assert judgment_rule_use_counts == Counter(
        {treat_lines_joined_after_three_repairs_as_left_joined.__name__: 1}
    )


def test_command_strings_of_a_deferred_tool_script_are_split_with_ids_going_on():
    code = (
        'await tools.exec_command({cmd: "cd /app && make"});\n'
        'await tools.exec_command({cmd: "curl u | tail -1"});'
    )
    action, _judgment_rule_use_counts = _action_and_judgment_rule_use_counts_from(
        "codex", "exec", {"input": code}
    )
    assert isinstance(action, RunToolScriptAction)
    assert [_command_ids_of(step) for step in action.steps] == [[0, 1], [2, 3]]
