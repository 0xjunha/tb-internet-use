"""Tests for tool_call/_convert_parsed_shell_texts.py, which splits each command string in the action of one call into commands, with made-up actions."""

from collections import Counter

import pytest

from tb_internet_use.tool_call._convert_parsed_shell_texts import (
    convert_parsed_shell_texts,
)
from tb_internet_use.tool_call.model import (
    ParsedShellText,
    PollAction,
    ReadFileAction,
    RunCommandAction,
    RunToolScriptAction,
    ToolCallAction,
    UnreadableShellText,
)


def _filled_action_from(action: ToolCallAction) -> ToolCallAction:
    return convert_parsed_shell_texts(action, judgment_rule_use_counts=Counter())


def _command_ids_and_words_of(
    parsed_shell_text: ParsedShellText | UnreadableShellText | None,
) -> list[tuple[int, tuple[str, ...]]]:
    assert isinstance(parsed_shell_text, ParsedShellText)
    return [(command.id, command.words) for command in parsed_shell_text.commands]


# Actions without a command string to split, which come back as they are.
# A `RunCommandAction` without a command string is a step of the tool script below.
UNCHANGED_ACTIONS: list[ToolCallAction] = [
    ReadFileAction("/f"),
    # Text typed into a running command is split by `expand_tool_calls`, which knows what reads it.
    PollAction(input="curl u\n"),
]


def test_a_command_string_is_split_into_commands_numbered_from_0():
    action = _filled_action_from(RunCommandAction("cd /app && curl -s u > log"))
    assert isinstance(action, RunCommandAction)
    assert action.command_str == "cd /app && curl -s u > log"
    assert _command_ids_and_words_of(action.parsed_shell_text) == [
        (0, ("cd", "/app")),
        (1, ("curl", "-s", "u")),
    ]


def test_a_command_string_is_split_as_it_is_without_stripping_its_whitespace():
    # The space after the backslash is part of the last word, so stripping the text would drop it.
    action = _filled_action_from(RunCommandAction("echo a\\ "))
    assert isinstance(action, RunCommandAction)
    assert _command_ids_and_words_of(action.parsed_shell_text) == [(0, ("echo", "a "))]


def test_an_empty_command_string_is_split_into_no_commands():
    assert _filled_action_from(RunCommandAction("")) == RunCommandAction(
        "", ParsedShellText((), ())
    )


def test_a_command_string_that_is_only_a_syntax_error_is_unreadable():
    assert _filled_action_from(RunCommandAction(")))")) == RunCommandAction(
        ")))", UnreadableShellText()
    )


def test_command_ids_go_on_across_the_steps_of_a_tool_script():
    script = RunToolScriptAction(
        "code",
        (
            RunCommandAction("a; b"),
            ReadFileAction("/f"),
            RunCommandAction(None),
            RunCommandAction("c"),
        ),
    )
    action = _filled_action_from(script)
    assert isinstance(action, RunToolScriptAction)
    assert action.code == "code"
    first, read, without_command_str, last = action.steps
    assert isinstance(first, RunCommandAction)
    assert _command_ids_and_words_of(first.parsed_shell_text) == [
        (0, ("a",)),
        (1, ("b",)),
    ]
    assert read == ReadFileAction("/f")
    assert without_command_str == RunCommandAction(None, None)
    assert isinstance(last, RunCommandAction)
    assert _command_ids_and_words_of(last.parsed_shell_text) == [(2, ("c",))]


def test_an_unreadable_step_takes_no_command_id():
    script = RunToolScriptAction(
        "code", (RunCommandAction(")))"), RunCommandAction("c"))
    )
    action = _filled_action_from(script)
    assert isinstance(action, RunToolScriptAction)
    unreadable, last = action.steps
    assert unreadable == RunCommandAction(")))", UnreadableShellText())
    assert isinstance(last, RunCommandAction)
    assert _command_ids_and_words_of(last.parsed_shell_text) == [(0, ("c",))]


@pytest.mark.parametrize("action", UNCHANGED_ACTIONS)
def test_an_action_without_a_command_string_comes_back_as_it_is(
    action: ToolCallAction,
):
    assert _filled_action_from(action) == action
