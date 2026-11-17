"""Tests for scripts/audit_parsed_shell_texts.py, with made-up actions whose `parsed_shell_text` breaks each check and made-up calls whose shell texts are counted per harness."""

import importlib.util
import sys
from collections import Counter
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Any, Never

import pytest

from tb_internet_use.tool_call._convert_parsed_shell_texts import (
    convert_parsed_shell_texts,
)
from tb_internet_use.tool_call.model import (
    ExitOutcome,
    HarnessTool,
    HarnessToolCall,
    ParsedShellText,
    PipeDestination,
    RunCommandAction,
    RunCondition,
    RunToolScriptAction,
    ShellCommand,
    ToolCall,
    ToolCallAction,
    ToolCallKey,
    VariableAssignment,
)
from tb_internet_use.tool_call.parse_shell_text import parse_shell_text
from tb_internet_use.trial.model import UnreadableTrajectory, UnreadableTrajectoryReason

_SPEC = importlib.util.spec_from_file_location(
    "audit_parsed_shell_texts",
    Path(__file__).parents[2] / "scripts/audit_parsed_shell_texts.py",
)
assert _SPEC is not None and _SPEC.loader is not None
audit = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = audit  # dataclasses look the module up while it loads
_SPEC.loader.exec_module(audit)

ParsedShellTextCheck = audit.ParsedShellTextCheck


def _violation_counts_of(action: ToolCallAction) -> Counter:
    _checked_counts, violation_counts = audit.checked_and_violation_counts_of_action(
        action
    )
    return violation_counts


def _action_of_commands(
    *commands: ShellCommand,
    variable_assignments: tuple[VariableAssignment, ...] = (),
) -> RunCommandAction:
    return RunCommandAction("made up", ParsedShellText(commands, variable_assignments))


def _run_command_action_from(shell_text: str) -> RunCommandAction:
    """Split a shell text with ids from 0, as for the first shell text of a call."""
    return RunCommandAction(
        shell_text, parse_shell_text(shell_text, judgment_rule_use_counts=Counter())
    )


def _claude_code_bash_call(call_index: int, args: dict[str, Any]) -> HarnessToolCall:
    return HarnessToolCall(
        ToolCallKey("t", "main", 1, call_index),
        HarnessTool("claude-code", "Bash"),
        "id",
        args,
        None,
    )


def _read_trajectory_raising(trial_dir: Path) -> Never:
    raise ValueError(trial_dir.name)


# (made-up action, the check that one of its values breaks), one case per half of each check.
VIOLATING_ACTIONS = [
    pytest.param(
        RunCommandAction("a", None),
        ParsedShellTextCheck.PARSED_SHELL_TEXT_IS_NONE_EXACTLY_WHEN_COMMAND_STR_IS_NONE,
        id="command string left unsplit",
    ),
    pytest.param(
        RunCommandAction(None, ParsedShellText((), ())),
        ParsedShellTextCheck.PARSED_SHELL_TEXT_IS_NONE_EXACTLY_WHEN_COMMAND_STR_IS_NONE,
        id="split without a command string",
    ),
    pytest.param(
        RunToolScriptAction(
            "code", (_run_command_action_from("a; b"), _run_command_action_from("c"))
        ),
        ParsedShellTextCheck.COMMAND_IDS_CONTINUE_WITHIN_CALL,
        id="a step whose ids start again from 0",
    ),
    pytest.param(
        _action_of_commands(ShellCommand(0, ("a",)), ShellCommand(2, ("b",))),
        ParsedShellTextCheck.COMMAND_IDS_CONTINUE_WITHIN_CALL,
        id="a gap in the ids",
    ),
    pytest.param(
        _action_of_commands(ShellCommand(0, ("curl", "u"), stdout=PipeDestination(1))),
        ParsedShellTextCheck.PIPE_READER_AND_DECIDING_COMMAND_IDS_ARE_COMMANDS_OF_SHELL_TEXT,
        id="a pipe reader outside the shell text",
    ),
    pytest.param(
        _action_of_commands(ShellCommand(0, ("curl", "u"), stderr=PipeDestination(1))),
        ParsedShellTextCheck.PIPE_READER_AND_DECIDING_COMMAND_IDS_ARE_COMMANDS_OF_SHELL_TEXT,
        id="a stderr pipe reader outside the shell text",
    ),
    pytest.param(
        _action_of_commands(
            ShellCommand(0, ("a",)),
            ShellCommand(1, ("b",), runs_if=(RunCondition((5,), ExitOutcome.SUCCESS),)),
        ),
        ParsedShellTextCheck.PIPE_READER_AND_DECIDING_COMMAND_IDS_ARE_COMMANDS_OF_SHELL_TEXT,
        id="a deciding command outside the shell text",
    ),
    pytest.param(
        RunToolScriptAction(
            "code",
            (
                _run_command_action_from("a; b"),
                RunCommandAction(
                    "made up",
                    ParsedShellText(
                        (
                            ShellCommand(
                                2,
                                ("c",),
                                runs_if=(RunCondition((0,), ExitOutcome.SUCCESS),),
                            ),
                        ),
                        (),
                    ),
                ),
            ),
        ),
        ParsedShellTextCheck.PIPE_READER_AND_DECIDING_COMMAND_IDS_ARE_COMMANDS_OF_SHELL_TEXT,
        id="a deciding command of an earlier step",
    ),
    pytest.param(
        _action_of_commands(
            ShellCommand(0, ("a",), runs_if=(RunCondition((1,), ExitOutcome.SUCCESS),)),
            ShellCommand(1, ("b",)),
        ),
        ParsedShellTextCheck.PIPE_READER_AND_DECIDING_COMMAND_IDS_ARE_COMMANDS_OF_SHELL_TEXT,
        id="a deciding command after the one it decides",
    ),
    pytest.param(
        _action_of_commands(
            ShellCommand(0, ("echo", "plain"), expansion_word_indexes=(1,))
        ),
        ParsedShellTextCheck.EXPANSION_WORD_INDEXES_POINT_AT_EXPANSIONS,
        id="an index at a plain word",
    ),
    pytest.param(
        _action_of_commands(
            ShellCommand(0, ("echo", "$A"), expansion_word_indexes=(1, 2))
        ),
        ParsedShellTextCheck.EXPANSION_WORD_INDEXES_POINT_AT_EXPANSIONS,
        id="an index beyond the words",
    ),
    pytest.param(
        _action_of_commands(
            ShellCommand(0, ("echo", "$A", "$B"), expansion_word_indexes=(2, 1))
        ),
        ParsedShellTextCheck.EXPANSION_WORD_INDEXES_POINT_AT_EXPANSIONS,
        id="indexes that do not rise",
    ),
    pytest.param(
        _action_of_commands(
            ShellCommand(0, ("echo", "$A"), expansion_word_indexes=(1, 1))
        ),
        ParsedShellTextCheck.EXPANSION_WORD_INDEXES_POINT_AT_EXPANSIONS,
        id="an index repeated",
    ),
    pytest.param(
        _action_of_commands(
            ShellCommand(0, ("a",)),
            ShellCommand(1, ("b",), structure_may_be_wrong=True),
        ),
        ParsedShellTextCheck.STRUCTURE_MARKS_AGREE_WITHIN_SHELL_TEXT,
        id="a mark on one command of two",
    ),
    pytest.param(
        _action_of_commands(
            ShellCommand(0, ("curl", "$U"), expansion_word_indexes=(1,)),
            variable_assignments=(VariableAssignment("U", "x", 2, None),),
        ),
        ParsedShellTextCheck.ASSIGNMENT_POSITIONS_ARE_IN_SHELL_TEXT,
        id="an assignment after the end of its shell text",
    ),
    pytest.param(
        RunToolScriptAction(
            "code",
            (
                _run_command_action_from("a; b"),
                RunCommandAction(
                    "made up",
                    ParsedShellText(
                        (ShellCommand(2, ("c",)),),
                        (VariableAssignment("U", "x", 1, None),),
                    ),
                ),
            ),
        ),
        ParsedShellTextCheck.ASSIGNMENT_POSITIONS_ARE_IN_SHELL_TEXT,
        id="an assignment before the first id of its step",
    ),
    pytest.param(
        RunToolScriptAction(
            "code",
            (
                _run_command_action_from("a; b"),
                RunCommandAction(
                    "made up",
                    ParsedShellText(
                        (ShellCommand(2, ("c",)),),
                        (VariableAssignment("U", "x", 4, None),),
                    ),
                ),
            ),
        ),
        ParsedShellTextCheck.ASSIGNMENT_POSITIONS_ARE_IN_SHELL_TEXT,
        id="an assignment after the end of a later step",
    ),
    pytest.param(
        _action_of_commands(
            ShellCommand(0, ("a",)),
            ShellCommand(1, ("b",)),
            variable_assignments=(VariableAssignment("p", "A", 1, 0),),
        ),
        ParsedShellTextCheck.ASSIGNMENT_POSITIONS_ARE_IN_SHELL_TEXT,
        id="a for loop item whose loop ends before it",
    ),
]


# (text, kind of its first character), one case per kind.
FIRST_CHARACTER_KIND_CASES = [
    ("", "empty"),
    ("curl u", "letter"),
    ("2>&1", "digit"),
    (" a", "whitespace"),
    ("\x00a", "control"),
    ("\x7fa", "control"),
    (")))", ")"),
    ("é", "letter"),
    ("→", "other"),
]


# (made-up `read_trajectory`, outcome of the trial), one case per outcome without converted calls.
TRIAL_OUTCOME_CASES = [
    pytest.param(lambda trial_dir: (), "converted without tool calls", id="no calls"),
    pytest.param(
        lambda trial_dir: UnreadableTrajectory(UnreadableTrajectoryReason.MISSING),
        "unreadable missing",
        id="unreadable",
    ),
    pytest.param(_read_trajectory_raising, "exception ValueError", id="exception"),
]


def test_shell_texts_of_a_script_split_as_convert_tool_calls_splits_them_break_no_check():
    # The assignments sit in a later step, so their positions are checked from the first id of that step.
    script = RunToolScriptAction(
        "code",
        (
            RunCommandAction("a || b"),
            RunCommandAction(),
            RunCommandAction(
                "for p in A B; do pip install $p 2>&1 | tail -1; done && U=x; curl $U"
            ),
        ),
    )
    split_script = convert_parsed_shell_texts(
        script, judgment_rule_use_counts=Counter()
    )
    assert _violation_counts_of(split_script) == Counter()


def test_a_for_loop_without_commands_in_its_body_breaks_no_check():
    # The loop body gives no command, so the items of p take the id of c, 0, as their next id and as the id after the loop.
    action = _run_command_action_from("for p in A B; do X=$p; done; c")
    assert isinstance(action.parsed_shell_text, ParsedShellText)
    assert action.parsed_shell_text.variable_assignments[0] == VariableAssignment(
        "p", "A", 0, 0
    )
    assert _violation_counts_of(action) == Counter()


def test_an_assignment_after_the_last_command_breaks_no_check():
    # `a; U=x` gives the assignment the id one past the last command, i.e. 1.
    action = _action_of_commands(
        ShellCommand(0, ("a",)),
        variable_assignments=(VariableAssignment("U", "x", 1, None),),
    )
    assert _violation_counts_of(action) == Counter()


@pytest.mark.parametrize(("action", "check"), VIOLATING_ACTIONS)
def test_a_made_up_violation_breaks_its_check_once(
    action: ToolCallAction, check: StrEnum
):
    assert _violation_counts_of(action) == Counter({check: 1})


def test_shell_texts_and_commands_are_counted_per_harness(
    monkeypatch: pytest.MonkeyPatch, shell_text_joined_after_three_repairs: str
):
    harness_tool_calls_by_trial = {
        "first": (
            _claude_code_bash_call(
                0, {"command": shell_text_joined_after_three_repairs}
            ),
            _claude_code_bash_call(1, {"command": ""}),
            _claude_code_bash_call(2, {"command": " "}),
            _claude_code_bash_call(3, {"command": "# note"}),
            _claude_code_bash_call(4, {"command": ")))"}),
            _claude_code_bash_call(5, {}),
        ),
        "second": (_claude_code_bash_call(0, {"command": "a | b"}),),
    }
    monkeypatch.setattr(
        audit,
        "read_trajectory",
        lambda trial_dir: harness_tool_calls_by_trial[trial_dir.name],
    )
    total = audit.TrialAuditTotal()
    for trial_id in harness_tool_calls_by_trial:
        total.add_trial(audit.audit_trial(Path(trial_id)))

    assert total.outcome_counts == Counter({"converted": 2})
    assert total.shell_text_counts_by_harness == {
        "claude-code": audit.ShellTextCounts(
            trial_count=2,
            run_command_action_count=7,
            run_command_action_without_command_str_count=1,
            shell_text_count=6,
            # All but `""` and `" "`.
            non_whitespace_shell_text_count=4,
            unreadable_shell_text_count=1,
            empty_or_whitespace_shell_text_without_commands_count=2,
            non_whitespace_shell_text_without_commands_count=1,
            # The 26 commands of the joined shell text and the 2 of `a | b`.
            command_count=28,
            command_with_structure_may_be_wrong_count=26,
            shell_text_with_structure_may_be_wrong_count=1,
            judgment_rule_use_count=1,
        )
    }
    parsed_shell_text_count = 5
    assert total.checked_counts == Counter(
        {
            ParsedShellTextCheck.PARSED_SHELL_TEXT_IS_NONE_EXACTLY_WHEN_COMMAND_STR_IS_NONE: 7,
            ParsedShellTextCheck.COMMAND_IDS_CONTINUE_WITHIN_CALL: parsed_shell_text_count,
            ParsedShellTextCheck.PIPE_READER_AND_DECIDING_COMMAND_IDS_ARE_COMMANDS_OF_SHELL_TEXT: parsed_shell_text_count,
            ParsedShellTextCheck.EXPANSION_WORD_INDEXES_POINT_AT_EXPANSIONS: 28,
            ParsedShellTextCheck.STRUCTURE_MARKS_AGREE_WITHIN_SHELL_TEXT: parsed_shell_text_count,
        }
    )
    assert total.violation_counts == Counter()
    assert total.unreadable_shell_text_shapes == [("claude-code", 3, ")")]


def test_a_violating_call_reaches_the_violation_counts_of_the_total(
    monkeypatch: pytest.MonkeyPatch,
):
    harness_tool_call = _claude_code_bash_call(0, {"command": "a"})
    monkeypatch.setattr(
        audit, "read_trajectory", lambda trial_dir: (harness_tool_call,)
    )
    monkeypatch.setattr(
        audit,
        "convert_tool_calls",
        lambda harness_tool_calls, **_keywords: [
            ToolCall(harness_tool_call, RunCommandAction("a", None), None)
        ],
    )
    total = audit.TrialAuditTotal()
    total.add_trial(audit.audit_trial(Path("violating")))
    check = (
        ParsedShellTextCheck.PARSED_SHELL_TEXT_IS_NONE_EXACTLY_WHEN_COMMAND_STR_IS_NONE
    )
    assert total.violation_counts == Counter({check: 1})
    assert total.violation_examples == [(check, "violating", "main:1:0")]


@pytest.mark.parametrize(("read_trajectory", "outcome"), TRIAL_OUTCOME_CASES)
def test_a_trial_without_converted_calls_has_its_own_outcome(
    monkeypatch: pytest.MonkeyPatch, read_trajectory: Callable, outcome: str
):
    monkeypatch.setattr(audit, "read_trajectory", read_trajectory)
    trial_audit = audit.audit_trial(Path("t"))
    assert trial_audit.outcome == outcome
    assert trial_audit.shell_text_counts_by_harness == {}


@pytest.mark.parametrize(("text", "kind"), FIRST_CHARACTER_KIND_CASES)
def test_the_first_character_is_named_by_its_kind(text: str, kind: str):
    assert audit.first_character_kind_of(text) == kind


def test_trial_ids_are_the_first_column_of_lines_that_are_not_comments():
    file_text = "# trial_id\tharness\nt1\tcodex\tfirst\n\nt2\n#t3\n"
    assert audit.trial_ids_from_file_text(file_text) == ["t1", "t2"]
