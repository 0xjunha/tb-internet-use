"""Tests for scripts/audit_expanded_tool_calls.py, with made-up trials expanded on a made-up program catalog, broken inputs made from one such expansion, each of which makes at least the equation it names differ, and made-up trial folders run through `audit_trial` and `main`."""

import copy
import csv
import dataclasses
import importlib.util
import inspect
import json
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any, ClassVar, Self

import pytest

from tb_internet_use.expanded_tool_call import expand_tool_calls
from tb_internet_use.expanded_tool_call.model import (
    ExpandedToolCall,
    FileText,
    FileUseKind,
    FileUseWithoutKnownWriter,
    OutputPlace,
    OutputVisibility,
    PollInputText,
    ProgramInvocation,
    RanCommand,
    RanShellText,
    UnknownProgramInvocation,
    VariableValues,
)
from tb_internet_use.knowledge.catalog import KnowledgeUses
from tb_internet_use.knowledge.expanded_tool_call_knowledge import (
    ExpandedToolCallKnowledge,
)
from tb_internet_use.tool_call.model import (
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    PollAction,
    ReadFileAction,
    RunCommandAction,
    ToolCall,
    ToolCallAction,
    ToolCallKey,
    ToolCallResult,
    UnreadableShellText,
    WriteFileAction,
)
from tb_internet_use.tool_call.parse_shell_text import parse_shell_text

_SPEC = importlib.util.spec_from_file_location(
    "audit_expanded_tool_calls",
    Path(__file__).parents[2] / "scripts/audit_expanded_tool_calls.py",
)
assert _SPEC is not None and _SPEC.loader is not None
audit = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = audit  # registered as an import would do
_SPEC.loader.exec_module(audit)

FINISHED = ToolCallResult(
    tool_output_text="", execution_status=ExecutionStatus.FINISHED, exit_code=0
)
TASK_1 = ExecutionHandle(ExecutionHandleKind.COMMAND, "task-1")

# Made-up rows, each named by the program and the cells that differ from the defaults of `conftest.py`. mytool has no row, tail has no row for `-5`, and printf leaves blank whether its options end at its first argument.
PROGRAM_BEHAVIOR_ROWS: list[dict[str, str]] = [
    {
        "program_name": "bash",
        "first_argument_role": "run_file",
        "stdin_role": "run_text",
        "options_end_at_first_argument": "yes",
    },
    {
        "program_name": "cat",
        "argument_role": "read_file",
        "stdin_role": "read_file",
        "visibility_of_piped_input": "whole",
    },
    {
        "program_name": "tail",
        "argument_role": "read_file",
        "visibility_of_piped_input": "partial",
    },
    {"program_name": "curl", "argument_role": ""},
    {"program_name": "echo"},
    {"program_name": "printf", "options_end_at_first_argument": ""},
    {
        "program_name": "python",
        "first_argument_role": "run_file",
        "stdin_role": "run_text",
        "options_end_at_first_argument": "yes",
    },
    {
        "program_name": "env",
        "argument_role": "program",
        "skips_assignment_words": "yes",
        "options_end_at_first_argument": "yes",
    },
    {"program_name": "wc", "argument_role": "size_or_type_file"},
    {
        "program_name": "grep",
        "argument_role": "read_file",
        "first_argument_role": "pattern",
    },
    {"program_name": "tar", "first_argument_role": "option_cluster"},
]
PROGRAM_OPTION_BEHAVIOR_ROWS: list[dict[str, str]] = [
    {
        "program_name": "bash",
        "option_name": "-c",
        "first_argument_role_with_option": "run_text",
    },
    {
        "program_name": "curl",
        "option_name": "-o",
        "takes_value": "yes",
        "value_role": "",
    },
    {
        "program_name": "grep",
        "option_name": "-c",
        "argument_role_with_option": "used_file",
    },
    {
        "program_name": "tar",
        "option_name": "-f",
        "takes_value": "yes",
        "value_role": "",
    },
]
CODE_RUNNER_ROWS: list[dict[str, str]] = [
    {"runner_kind": "program_name", "runner": "bash"},
    {"runner_kind": "program_name", "runner": "python", "ran_text_language": "python"},
]


def _key(step_id: int, trajectory_id: str = "main") -> ToolCallKey:
    return ToolCallKey("t1", trajectory_id, step_id, 0)


SUBAGENT_KEY = _key(1, "main/sub0")


def _call(
    step_id: int, action: ToolCallAction | str, result: ToolCallResult | None = FINISHED
) -> ToolCall:
    if isinstance(action, str):
        action = RunCommandAction(
            action, parse_shell_text(action, judgment_rule_use_counts=Counter())
        )
    return ToolCall(
        HarnessToolCall(_key(step_id), HarnessTool("harness", "tool"), "", {}, None),
        action,
        result,
    )


@pytest.fixture
def knowledge(catalogs_dir: Path) -> ExpandedToolCallKnowledge:
    return ExpandedToolCallKnowledge(catalogs_dir=catalogs_dir)


def _checked(
    knowledge: ExpandedToolCallKnowledge,
    tool_calls: tuple[ToolCall, ...],
    expanded_tool_calls: tuple[ExpandedToolCall, ...] | None = None,
    *,
    added_rule_uses: Counter[str] | None = None,
) -> Any:
    """Check made-up calls as `audit_trial` does, with the expansion that `expand_tool_calls` gives unless the test passes one, and give the trial audit.

    `added_rule_uses` adds to the rule uses that the expansion counted, as a broken expansion would.
    """
    judgment_rule_use_counts: Counter[str] = Counter()
    # The door's uses start empty, so that the unknown inputs are those of this expansion.
    knowledge.uses = KnowledgeUses()
    expanded = expand_tool_calls(
        tool_calls,
        knowledge=knowledge,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )
    judgment_rule_use_counts.update(added_rule_uses or Counter())
    trial_audit = audit.TrialAudit(
        "t1",
        audit.EXPANDED,
        harness="harness",
        task="4-0-0 terminal-bench/a",
        judgment_rule_use_counts=judgment_rule_use_counts,
        knowledge_uses=knowledge.uses,
    )
    # The checker asks a door of its own, as `audit_trial` gives it, so that its lookups do not count as lookups of the expansion.
    own_knowledge = copy.copy(knowledge)
    own_knowledge.uses = KnowledgeUses()
    audit.TrialChecker(
        trial_audit,
        tool_calls,
        expanded if expanded_tool_calls is None else expanded_tool_calls,
        own_knowledge,
    ).check()
    return trial_audit


def _differing_equations(trial_audit: Any) -> set[str]:
    return {
        equation
        for equation, _ in trial_audit.equation_sides
        if trial_audit.equation_sides[equation, "left"]
        != trial_audit.equation_sides[equation, "right"]
    }


# A made-up trial with calls for each equation. The comments name what the later calls add.
_MADE_UP_TRIAL = (
    _call(1, WriteFileAction("fetch.sh", "curl a")),
    _call(
        2,
        "bash fetch.sh > fetch.log 2>&1; cat x | tail; mytool y",
        ToolCallResult(
            tool_output_text="",
            execution_status=ExecutionStatus.RUNNING,
            handles=(TASK_1,),
            output_path="/tmp/b1.output",
        ),
    ),
    _call(3, PollAction((TASK_1,)), FINISHED),
    _call(4, "cat fetch.log notes.md"),
    _call(5, ReadFileAction("fetch.log")),
    _call(6, "bash -c 'curl b'"),
    # A command action without a text and one whose text could not be split.
    _call(7, RunCommandAction()),
    _call(8, RunCommandAction(")))", UnreadableShellText())),
    # tail has no row for `-5`, so the rest of its words are unread.
    _call(9, "tail -5 run.log"),
    # A later read of the harness output file of call 2.
    _call(10, "cat /tmp/b1.output"),
    # Text typed into mytool, the last command of call 2, whose language is not known.
    _call(11, PollAction((TASK_1,), input="hello"), FINISHED),
    # A subagent writes sub.sh, which the main trajectory then runs without being linked to it.
    ToolCall(
        HarnessToolCall(
            SUBAGENT_KEY,
            HarnessTool("harness", "tool"),
            "",
            {},
            None,
            is_subagent=True,
        ),
        WriteFileAction("sub.sh", "echo s"),
        FINISHED,
    ),
    _call(13, "bash sub.sh"),
    # printf leaves `-v` unread for want of a cell of its row, which the door counts.
    _call(14, "printf a -v x"),
)


def test_every_equation_holds_on_a_made_up_trial_of_the_kinds_it_counts(knowledge):
    trial_audit = _checked(knowledge, _MADE_UP_TRIAL)

    assert _differing_equations(trial_audit) == set()
    assert trial_audit.counts["all", "calls"] == 14
    assert trial_audit.counts["harness", "ran_texts shell from FileText"] == 1
    assert trial_audit.counts["all", "unknown_program_invocations"] == 1
    assert trial_audit.counts["all", "program_invocations_with_unread_words"] == 2
    # bash fetch.sh, bash -c and bash sub.sh each run a text, the last one unknown since no call of its trajectory wrote sub.sh.
    assert trial_audit.counts["all", "commands_of_runner_names runs a text"] == 3
    # Both arguments of the later cat count, one as a use of a written file and one without a known writer.
    assert trial_audit.equation_sides["cat_arguments_equal_file_uses", "left"] == 3
    assert (
        trial_audit.equation_sides[
            "harness_output_file_reads_are_output_places", "left"
        ]
        == 1
    )
    assert trial_audit.counts["all", "poll inputs a text starts from it"] == 1
    assert (
        trial_audit.equation_sides["other_trajectory_rule_uses_equal_recount", "left"]
        == 1
    )
    # Every other equation has a value on its left side, so that each holds on something.
    assert {
        equation
        for equation in audit.EQUATIONS
        if trial_audit.equation_sides[equation, "left"] == 0
    } == {
        "calls_not_run_reach_nothing",
        "harness_output_file_reads_are_no_uses_without_writer",
        "values_in_turn_only_in_loops",
    }


def test_every_equation_has_its_definition_above_its_name():
    source_lines = inspect.getsource(audit).splitlines()
    equations_start = source_lines.index("EQUATIONS = (")
    equations_without_definition = [
        equation
        for equation in audit.EQUATIONS
        if not source_lines[
            source_lines.index(f'    "{equation}",', equations_start) - 1
        ].startswith("    # ")
    ]

    assert equations_without_definition == []


def _with_fields_of(
    expanded_tool_calls: tuple[ExpandedToolCall, ...], index: int, **changes
) -> tuple[ExpandedToolCall, ...]:
    changed = dataclasses.replace(expanded_tool_calls[index], **changes)
    return (*expanded_tool_calls[:index], changed, *expanded_tool_calls[index + 1 :])


def _with_ran_command(
    expanded_tool_calls: tuple[ExpandedToolCall, ...],
    index: int,
    command_index: int,
    change: Callable[[RanCommand], RanCommand],
) -> tuple[ExpandedToolCall, ...]:
    """Change one command of the call's own text, i.e. its first ran text."""
    own_text, *other_texts = expanded_tool_calls[index].ran_texts
    assert isinstance(own_text, RanShellText)
    commands = list(own_text.ran_commands)
    commands[command_index] = change(commands[command_index])
    return _with_fields_of(
        expanded_tool_calls,
        index,
        ran_texts=(RanShellText(own_text.source, tuple(commands)), *other_texts),
    )


def _expanded(knowledge: ExpandedToolCallKnowledge) -> tuple[ExpandedToolCall, ...]:
    return expand_tool_calls(
        _MADE_UP_TRIAL, knowledge=knowledge, judgment_rule_use_counts=Counter()
    )


# A broken input is the tool calls and the expansion to check, and the rule uses to add, made from the expansion of `_MADE_UP_TRIAL`.
BrokenInput = tuple[tuple[ToolCall, ...], tuple[ExpandedToolCall, ...], Counter[str]]


def _input_with(expanded: tuple[ExpandedToolCall, ...]) -> BrokenInput:
    return _MADE_UP_TRIAL, expanded, Counter()


def _another_tool_call_in_place(expanded) -> BrokenInput:
    return _input_with(_with_fields_of(expanded, 0, tool_call=_MADE_UP_TRIAL[1]))


def _last_call_dropped(expanded) -> BrokenInput:
    return _input_with(expanded[:-1])


def _command_of_call_text_dropped(expanded) -> BrokenInput:
    own_text = expanded[1].ran_texts[0]
    assert isinstance(own_text, RanShellText)
    return _input_with(
        _with_fields_of(
            expanded,
            1,
            ran_texts=(
                RanShellText(own_text.source, own_text.ran_commands[1:]),
                *expanded[1].ran_texts[1:],
            ),
        )
    )


def _missing_text_dropped(expanded) -> BrokenInput:
    return _input_with(_with_fields_of(expanded, 6, ran_texts=()))


def _unreadable_text_dropped(expanded) -> BrokenInput:
    return _input_with(_with_fields_of(expanded, 7, ran_texts=()))


def _file_text_dropped(expanded) -> BrokenInput:
    return _input_with(
        _with_fields_of(expanded, 1, ran_texts=expanded[1].ran_texts[:1])
    )


def _argument_of_cat_dropped(expanded) -> BrokenInput:
    def drop_argument(cat_command: RanCommand) -> RanCommand:
        (cat,) = cat_command.program_invocations
        assert isinstance(cat, ProgramInvocation)
        return dataclasses.replace(
            cat_command,
            program_invocations=(
                dataclasses.replace(cat, arguments=cat.arguments[:1]),
            ),
        )

    return _input_with(_with_ran_command(expanded, 3, 0, drop_argument))


def _use_without_writer_dropped(expanded) -> BrokenInput:
    return _input_with(_with_fields_of(expanded, 3, file_uses_without_known_writer=()))


def _unknown_program_read_as_known(expanded) -> BrokenInput:
    def read_as_known(mytool_command: RanCommand) -> RanCommand:
        (mytool,) = mytool_command.program_invocations
        assert isinstance(mytool, UnknownProgramInvocation)
        return dataclasses.replace(
            mytool_command,
            program_invocations=(
                ProgramInvocation("mytool", (), (), mytool.words, False, (), False),
            ),
        )

    return _input_with(_with_ran_command(expanded, 1, 3, read_as_known))


def _unread_words_dropped(expanded) -> BrokenInput:
    def drop_unread_words(tail_command: RanCommand) -> RanCommand:
        (tail,) = tail_command.program_invocations
        assert isinstance(tail, ProgramInvocation) and tail.unread_words
        return dataclasses.replace(
            tail_command,
            program_invocations=(dataclasses.replace(tail, unread_words=()),),
        )

    return _input_with(_with_ran_command(expanded, 8, 0, drop_unread_words))


def _place_outside_the_trial(expanded) -> BrokenInput:
    return _input_with(
        _with_fields_of(expanded, 0, output_places=(OutputPlace(_key(99), ()),))
    )


def _route_without_reader_made_partial(expanded) -> BrokenInput:
    def make_partial(cat_command: RanCommand) -> RanCommand:
        (route,) = cat_command.stdout_routes
        partial_route = dataclasses.replace(route)
        # `OutputRoute` refuses such a route when it is made, so the field is set past that check, as a broken check would let it through.
        object.__setattr__(partial_route, "visibility_at_end", OutputVisibility.PARTIAL)
        return dataclasses.replace(cat_command, stdout_routes=(partial_route,))

    return _input_with(_with_ran_command(expanded, 3, 0, make_partial))


def _route_that_hides_what_its_reader_passes_on(expanded) -> BrokenInput:
    def make_whole(cat_x: RanCommand) -> RanCommand:
        (route,) = cat_x.stdout_routes
        return dataclasses.replace(
            cat_x,
            stdout_routes=(
                dataclasses.replace(route, visibility_at_end=OutputVisibility.WHOLE),
            ),
        )

    return _input_with(_with_ran_command(expanded, 1, 1, make_whole))


def _values_in_turn_outside_a_loop(expanded) -> BrokenInput:
    def add_values(cat_command: RanCommand) -> RanCommand:
        return dataclasses.replace(
            cat_command,
            variable_values=(VariableValues("U", ("a", "b"), True, False),),
        )

    return _input_with(_with_ran_command(expanded, 3, 0, add_values))


def _tool_written_file_dropped(expanded) -> BrokenInput:
    return _input_with(_with_fields_of(expanded, 0, written_files=()))


def _file_text_of_a_writer_without_the_file(expanded) -> BrokenInput:
    file_text = expanded[1].ran_texts[1]
    assert isinstance(file_text.source, FileText)
    return _input_with(
        _with_fields_of(
            expanded,
            1,
            ran_texts=(
                expanded[1].ran_texts[0],
                dataclasses.replace(
                    file_text,
                    source=dataclasses.replace(
                        file_text.source, writer_tool_call_key=_key(5)
                    ),
                ),
            ),
        )
    )


def _call_marked_not_run(expanded) -> BrokenInput:
    tool_calls = list(_MADE_UP_TRIAL)
    tool_calls[3] = dataclasses.replace(
        tool_calls[3],
        result=ToolCallResult(execution_status=ExecutionStatus.NOT_RUN),
    )
    return (
        tuple(tool_calls),
        _with_fields_of(expanded, 3, tool_call=tool_calls[3]),
        Counter(),
    )


def _place_of_output_file_read_dropped(expanded) -> BrokenInput:
    return _input_with(
        _with_fields_of(
            expanded,
            1,
            output_places=tuple(
                output_place
                for output_place in expanded[1].output_places
                if output_place.showing_tool_call_key != _key(10)
            ),
        )
    )


def _output_file_read_as_use_without_writer(expanded) -> BrokenInput:
    return _input_with(
        _with_fields_of(
            expanded,
            9,
            file_uses_without_known_writer=(
                FileUseWithoutKnownWriter(
                    0, "/tmp/b1.output", FileUseKind.SHOWS_CONTENT
                ),
            ),
        )
    )


def _poll_input_text_dropped(expanded) -> BrokenInput:
    assert isinstance(expanded[10].ran_texts[0].source, PollInputText)
    return _input_with(_with_fields_of(expanded, 10, ran_texts=()))


def _written_file_of_subagent_dropped(expanded) -> BrokenInput:
    return _input_with(_with_fields_of(expanded, 11, written_files=()))


def _place_in_another_trajectory(expanded) -> BrokenInput:
    return _input_with(
        _with_fields_of(expanded, 0, output_places=(OutputPlace(SUBAGENT_KEY, ()),))
    )


def _rule_of_another_step_counted(expanded) -> BrokenInput:
    return (
        _MADE_UP_TRIAL,
        expanded,
        Counter({"treat_bash_output_without_exit_code_line_as_finished": 1}),
    )


# (equation, broken input that makes it differ), one per equation of the script in its order.
BROKEN_INPUT_CASES: list[tuple[str, Callable[..., BrokenInput]]] = [
    ("expanded_calls_equal_tool_calls", _another_tool_call_in_place),
    ("expanded_calls_equal_tool_calls_in_number", _last_call_dropped),
    ("ran_commands_equal_commands_of_call_texts", _command_of_call_text_dropped),
    ("missing_texts_equal_command_actions_without_text", _missing_text_dropped),
    ("unreadable_texts_equal_unreadable_call_texts", _unreadable_text_dropped),
    ("commands_of_runner_names_fall_in_a_branch", _file_text_dropped),
    (
        "program_invocations_hold_the_words_of_their_command",
        _argument_of_cat_dropped,
    ),
    ("cat_arguments_equal_file_uses", _use_without_writer_dropped),
    (
        "unknown_program_invocations_equal_unknown_program_lookups",
        _unknown_program_read_as_known,
    ),
    ("unread_words_equal_unknown_option_lookups", _unread_words_dropped),
    ("pointers_stay_inside_trial", _place_outside_the_trial),
    ("routes_without_pipe_reader_are_whole", _route_without_reader_made_partial),
    (
        "route_visibility_follows_pipe_readers",
        _route_that_hides_what_its_reader_passes_on,
    ),
    ("values_in_turn_only_in_loops", _values_in_turn_outside_a_loop),
    ("tool_written_files_equal_tool_paths", _tool_written_file_dropped),
    ("file_text_writers_hold_the_file", _file_text_of_a_writer_without_the_file),
    ("calls_not_run_reach_nothing", _call_marked_not_run),
    (
        "harness_output_file_reads_are_output_places",
        _place_of_output_file_read_dropped,
    ),
    (
        "harness_output_file_reads_are_no_uses_without_writer",
        _output_file_read_as_use_without_writer,
    ),
    ("poll_inputs_fall_in_a_branch", _poll_input_text_dropped),
    ("other_trajectory_rule_uses_equal_recount", _written_file_of_subagent_dropped),
    ("pointers_stay_inside_trajectory", _place_in_another_trajectory),
    ("judgment_rule_names_are_of_this_step", _rule_of_another_step_counted),
]


def test_every_equation_has_a_broken_input():
    assert [equation for equation, _ in BROKEN_INPUT_CASES] == list(audit.EQUATIONS)


@pytest.mark.parametrize(
    ("equation", "broken_input_of"),
    BROKEN_INPUT_CASES,
    ids=[equation for equation, _ in BROKEN_INPUT_CASES],
)
def test_a_broken_input_makes_its_equation_differ(knowledge, equation, broken_input_of):
    tool_calls, broken, added_rule_uses = broken_input_of(_expanded(knowledge))

    trial_audit = _checked(
        knowledge, tool_calls, broken, added_rule_uses=added_rule_uses
    )

    assert equation in _differing_equations(trial_audit)


def test_text_typed_into_a_program_that_runs_no_text_is_counted_by_the_row_of_that_program(
    knowledge,
):
    tool_calls = (
        _call(
            1,
            "cat > notes.txt",
            ToolCallResult(
                tool_output_text="",
                execution_status=ExecutionStatus.RUNNING,
                handles=(TASK_1,),
            ),
        ),
        _call(2, PollAction((TASK_1,), input="curl a\n"), FINISHED),
    )

    trial_audit = _checked(knowledge, tool_calls)

    assert _differing_equations(trial_audit) == set()
    assert (
        trial_audit.counts["all", "poll inputs typed into a program that runs no text"]
        == 1
    )
    assert trial_audit.equation_sides["poll_inputs_fall_in_a_branch", "left"] == 1


def _running_result(output_path: str) -> ToolCallResult:
    return ToolCallResult(
        tool_output_text="",
        execution_status=ExecutionStatus.RUNNING,
        handles=(TASK_1,),
        output_path=output_path,
    )


# (equation, made-up calls of a shape that the full data of 2026-10-08 showed, with the expansion right and the recount once wrong). The comments name the shape.
SHAPES_THAT_HOLD: list[tuple[str, tuple[ToolCall, ...]]] = [
    # `python - 2>&1 | tail <<'EOF'` gives the heredoc to tail, so python reads no text.
    (
        "commands_of_runner_names_fall_in_a_branch",
        (_call(1, "python - 2>&1 | tail <<'EOF'\nprint(1)\nEOF"),),
    ),
    # An assignment before the program can end with the program name.
    (
        "program_invocations_hold_the_words_of_their_command",
        (_call(1, "env X=/opt/cat cat log"),),
    ),
    # A `${D}` is no brace list, and the value of D is filled.
    (
        "cat_arguments_equal_file_uses",
        (_call(1, "D=/app; cat ${D}/a.txt"),),
    ),
    # cat reads the file of its stdin, e.g. `/dev/tcp/kafka/9092`.
    ("cat_arguments_equal_file_uses", (_call(1, "cat < /dev/tcp/h/80"),)),
    # A variable whose one value is the harness output file of an earlier call.
    (
        "cat_arguments_equal_file_uses",
        (
            _call(1, "sleep 9", _running_result("/tmp/b1.output")),
            _call(2, 'F=/tmp/b1.output; cat "$F"'),
        ),
    ),
    # Two arguments that each fit two written files are two files.
    (
        "cat_arguments_equal_file_uses",
        (
            _call(1, WriteFileAction("/a/x.log", "1")),
            _call(2, WriteFileAction("/b/x.log", "2")),
            _call(3, WriteFileAction("/a/y.log", "3")),
            _call(4, WriteFileAction("/b/y.log", "4")),
            _call(5, "cat x.log y.log"),
        ),
    ),
    # Two paths of one file that no call wrote are two uses without a known writer.
    ("cat_arguments_equal_file_uses", (_call(1, "cat ~/.h /root/.h"),)),
    # Two arguments that can name one written file are one use of it.
    (
        "cat_arguments_equal_file_uses",
        (_call(1, WriteFileAction("x.py", "1")), _call(2, "cat d/x.py x.py")),
    ),
    # A base name alone ends a longer relative path, so run.sh is the file written as d/run.sh.
    (
        "file_text_writers_hold_the_file",
        (_call(1, WriteFileAction("d/run.sh", "echo a")), _call(2, "bash run.sh")),
    ),
    # wc shows the size of the harness output file, not its content. In this catalog `-l` has no row, so its words stay unread and the read already counts on neither side before the role of wc is asked.
    (
        "harness_output_file_reads_are_output_places",
        (
            _call(1, "mytool", _running_result("/tmp/b1.output")),
            _call(2, "wc -l /tmp/b1.output"),
        ),
    ),
    # A read of the output file of a command whose output all goes to a log shows nothing of it.
    (
        "harness_output_file_reads_are_output_places",
        (
            _call(1, "mytool > /tmp/m.log 2>&1", _running_result("/tmp/b1.output")),
            _call(2, "cat /tmp/b1.output"),
        ),
    ),
    # `grep -c` shows a count, not the content.
    (
        "harness_output_file_reads_are_output_places",
        (
            _call(1, "mytool", _running_result("/tmp/b1.output")),
            _call(2, "grep -c x /tmp/b1.output"),
        ),
    ),
    # An option with a row that takes a value is the last word, so no unknown input.
    ("unread_words_equal_unknown_option_lookups", (_call(1, "curl u -o"),)),
    # The cluster letter c and --exclude both lack a row, so one run gives two unknown inputs.
    (
        "unread_words_equal_unknown_option_lookups",
        (_call(1, "tar cf - --exclude=x ."),),
    ),
    # An expansion word ends with the name of a program that a word as written names.
    (
        "unknown_program_invocations_equal_unknown_program_lookups",
        (_call(1, "mytool $D/mytool"),),
    ),
]


@pytest.mark.parametrize(
    ("equation", "tool_calls"),
    SHAPES_THAT_HOLD,
    ids=[f"{equation}-{index}" for index, (equation, _) in enumerate(SHAPES_THAT_HOLD)],
)
def test_a_shape_of_the_full_data_holds_its_equation(knowledge, equation, tool_calls):
    trial_audit = _checked(knowledge, tool_calls)

    assert equation not in _differing_equations(trial_audit)


@pytest.mark.parametrize(
    ("path", "other_path", "is_same"),
    [
        ("fetch.sh", "fetch.sh", True),
        ("scripts/fetch.sh", "/app/scripts/fetch.sh", True),
        ("fetch.sh", "/app/fetch.sh", True),
        ("$LOG/out", "/var/log/out", True),
        ("/a/fetch.sh", "/b/fetch.sh", False),
        ("a/f", "b/f", False),
        ("f", "a/f", True),
        ("./f", "/app/f", True),
        ("logs/../f", "/app/f", True),
        ('$(dirname "$0")/f.sh', "/app/f.sh", True),
        ("/$D/f", "/f", False),
    ],
)
def test_two_path_texts_name_one_file_in_the_way_of_the_rule(path, other_path, is_same):
    assert audit._is_same_file(path, other_path) is is_same


def _csv_rows(path: Path) -> list[list[str]]:
    with path.open(newline="") as csv_file:
        return list(csv.reader(csv_file))


def test_writes_unknown_inputs_with_commands_trials_and_tasks_most_first(tmp_path):
    total = audit.TrialAuditTotal()
    for trial_id, task, lookups in [
        ("t1", "4-0-0 a", {("program_behaviors.csv", ("mytool", "")): 3}),
        ("t2", "4-0-0 a", {("program_behaviors.csv", ("mytool", "")): 1}),
        (
            "t3",
            "4-0-0 b",
            {
                ("program_option_behaviors.csv", ("curl", "", "-s")): 9,
                ("program_behaviors.csv", ("mytool", "")): 1,
            },
        ),
    ]:
        total.add_trial(
            audit.TrialAudit(
                trial_id,
                audit.EXPANDED,
                task=task,
                knowledge_uses=KnowledgeUses(unknown_input_counts=Counter(lookups)),
            )
        )

    audit.write_audit_files(total, tmp_path)

    assert _csv_rows(tmp_path / "unknown_inputs.csv") == [
        [
            "catalog",
            "program_name",
            "subcommand",
            "option_name",
            "command_count",
            "trial_count",
            "task_count",
        ],
        ["program_option_behaviors.csv", "curl", "", "-s", "9", "1", "1"],
        ["program_behaviors.csv", "mytool", "", "", "5", "3", "2"],
    ]


def test_unknown_touches_count_each_command_once(knowledge, tmp_path):
    # The pipe reader mytool makes both routes of `cat x 2>&1` unknown, which are two routes of one command.
    tool_calls = (_call(1, "cat x 2>&1 | mytool"), _call(2, "cat y | mytool"))
    trial_audit = _checked(knowledge, tool_calls)
    total = audit.TrialAuditTotal()
    total.add_trial(trial_audit)

    audit.write_audit_files(total, tmp_path)

    assert _csv_rows(tmp_path / "unknown_touch_programs.csv") == [
        ["list", "program_name", "command_count", "trial_count", "task_count"],
        ["pipe reader of unknown visibility", "mytool", "2", "1", "1"],
    ]


def test_writes_each_differing_call_with_its_trial_and_exits_1_only_then(tmp_path):
    differing = audit.TrialAudit("t1", audit.EXPANDED)
    differing.add_sides("tool_written_files_equal_tool_paths", 1, 0, _key(3))
    holding = audit.TrialAudit("t2", audit.EXPANDED)
    holding.add_sides("tool_written_files_equal_tool_paths", 1, 1, _key(3))
    total_of_holding = audit.TrialAuditTotal()
    total_of_holding.add_trial(holding)
    total = audit.TrialAuditTotal()
    total.add_trial(differing)
    total.add_trial(holding)

    audit.write_audit_files(total, tmp_path)

    assert _csv_rows(tmp_path / "equation_examples.csv") == [
        ["equation", "trial_id", "tool_call_key"],
        ["tool_written_files_equal_tool_paths", "t1", "main:3:0"],
    ]
    assert not total_of_holding.has_exception_or_differing_equation()
    assert total.has_exception_or_differing_equation()


def test_every_equation_starts_at_zero_for_a_trial_that_was_not_expanded():
    trial_audit = audit.TrialAudit("t1", audit.NOT_FOUND)

    assert trial_audit.equation_sides == Counter()
    assert list(trial_audit.equation_sides) == [
        (equation, side) for equation in audit.EQUATIONS for side in ("left", "right")
    ]


def test_an_equation_no_trial_reaches_is_written_with_zero_sides(tmp_path):
    audit.write_audit_files(audit.TrialAuditTotal(), tmp_path)

    assert _csv_rows(tmp_path / "equations.csv") == [
        ["equation", "left", "right", "holds"],
        *([equation, "0", "0", "yes"] for equation in audit.EQUATIONS),
    ]


def test_an_unknown_equation_name_raises():
    with pytest.raises(ValueError, match="no equation"):
        audit.TrialAudit("t1", audit.EXPANDED).add_sides("commands", 1, 1, None)


# Made-up Claude Code calls of a trial folder, a `Write` of /app/fetch.sh and a `Bash` call that runs fetch.sh, each with a result.
_TRAJECTORY = {
    "schema_version": "ATIF-v1.7",
    "agent": {"name": "claude-code"},
    "steps": [
        {
            "step_id": 1,
            "tool_calls": [
                {
                    "tool_call_id": "a",
                    "function_name": "Write",
                    "arguments": {
                        "file_path": "/app/fetch.sh",
                        "content": "cat notes.txt",
                    },
                }
            ],
            "observation": {
                "results": [
                    {
                        "source_call_id": "a",
                        "content": "File created successfully at: /app/fetch.sh",
                    }
                ]
            },
        },
        {
            "step_id": 2,
            "tool_calls": [
                {
                    "tool_call_id": "b",
                    "function_name": "Bash",
                    "arguments": {"command": "bash fetch.sh"},
                }
            ],
            "observation": {"results": [{"source_call_id": "b", "content": "hello"}]},
        },
    ],
}


def _raw_trials_dir(tmp_path: Path) -> Path:
    """Make a raw trials folder with the made-up trial t1 of `_TRAJECTORY`."""
    trial_dir = tmp_path / "raw" / "t1"
    trial_dir.mkdir(parents=True)
    (trial_dir / "detail.json").write_text(
        json.dumps(
            {
                "id": "t1",
                "task_name": "terminal-bench/fix-git",
                "agent_info": {
                    "name": "claude-code",
                    "version": "2.1.0",
                    "model_info": {"name": "model-a"},
                },
                "verifier_result": {"rewards": {"reward": 1.0}},
            }
        )
    )
    (trial_dir / "status.json").write_text(
        json.dumps(
            {
                "trial_id": "t1",
                "memberships": [{"version": "4-0-0", "row_id": "row-1"}],
                "assets": {"trajectory": {"status": "downloaded"}},
            }
        )
    )
    (trial_dir / "trajectory.json").write_text(json.dumps(_TRAJECTORY))
    return tmp_path / "raw"


def test_audit_trial_expands_and_checks_a_trial_folder(tmp_path):
    trial_audit = audit.audit_trial(_raw_trials_dir(tmp_path) / "t1")

    assert trial_audit.outcome == audit.EXPANDED
    assert trial_audit.harness == "claude-code"
    assert trial_audit.task == "4-0-0 terminal-bench/fix-git"
    assert _differing_equations(trial_audit) == set()
    assert trial_audit.counts["all", "ran_texts shell from FileText"] == 1
    # fetch.sh is matched to /app/fetch.sh to follow its text and to record its use.
    assert trial_audit.judgment_rule_use_counts == Counter(
        {"treat_path_that_ends_another_as_same_file": 2}
    )


def test_audit_trial_gives_the_same_lookups_for_a_trial_audited_twice(tmp_path):
    trial_dir = _raw_trials_dir(tmp_path) / "t1"

    first = audit.audit_trial(trial_dir)
    second = audit.audit_trial(trial_dir)

    assert first.knowledge_uses.row_use_counts
    assert second.knowledge_uses == first.knowledge_uses


def test_audit_trial_names_a_missing_folder_apart_from_a_missing_trajectory(
    tmp_path,
):
    raw_trials_dir = _raw_trials_dir(tmp_path)
    (raw_trials_dir / "t2").mkdir()

    assert audit.audit_trial(raw_trials_dir / "t9").outcome == audit.NOT_FOUND
    assert audit.audit_trial(raw_trials_dir / "t2").outcome == "unreadable missing"


def test_audit_trial_names_the_type_of_an_exception(tmp_path, monkeypatch):
    def raise_error(*arguments: object, **keywords: object) -> None:
        raise RuntimeError

    monkeypatch.setattr(audit, "run_steps_to_expanded_tool_calls", raise_error)

    trial_audit = audit.audit_trial(_raw_trials_dir(tmp_path) / "t1")

    assert trial_audit.outcome == "exception RuntimeError"


class _InProcessPool:
    """Stand-in for the process pool of `main`, which maps in the test process so that a function that a test replaces is replaced in the run too, and keeps the process count it was asked for."""

    # The process counts that `main` asked for, kept across instances.
    process_counts: ClassVar[list[int]] = []

    def __init__(self, process_count: int) -> None:
        self.process_counts.append(process_count)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exception: object) -> None:
        pass

    def map(
        self, function: Callable[[Path], Any], items: Iterable[Path], chunksize: int
    ) -> Iterator[Any]:
        return map(function, items)


def _run_main(
    monkeypatch: pytest.MonkeyPatch, raw_trials_dir: Path, out_dir: Path
) -> None:
    """Run `main` on the trial ids t1, t1 again and t9, which names no folder."""
    trial_ids_file = raw_trials_dir.parent / "trial_ids.txt"
    trial_ids_file.write_text("t1\tclaude-code\nt1\nt9\n")
    monkeypatch.setattr(audit, "ProcessPoolExecutor", _InProcessPool)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "audit_expanded_tool_calls",
            str(raw_trials_dir),
            "--trial-ids",
            str(trial_ids_file),
            "--out-dir",
            str(out_dir),
        ],
    )
    audit.main()


def test_main_runs_a_repeated_trial_once_and_names_a_missing_one(tmp_path, monkeypatch):
    _InProcessPool.process_counts.clear()
    out_dir = tmp_path / "out"

    _run_main(monkeypatch, _raw_trials_dir(tmp_path), out_dir)

    assert _InProcessPool.process_counts
    assert max(_InProcessPool.process_counts) <= 4
    assert _csv_rows(out_dir / "trial_outcomes.csv") == [
        ["outcome", "trial_count", "first_trial_ids"],
        ["expanded", "1", "t1"],
        ["not found", "1", "t9"],
        ["repeated trial id, run once", "1", "t1"],
    ]
    assert _csv_rows(out_dir / "trials_not_expanded.csv") == [
        ["trial_id", "outcome"],
        ["t9", "not found"],
    ]
    equation_rows = _csv_rows(out_dir / "equations.csv")[1:]
    assert [row[0] for row in equation_rows] == list(audit.EQUATIONS)
    assert {row[3] for row in equation_rows} == {"yes"}
    assert _csv_rows(out_dir / "equation_examples.csv") == [
        ["equation", "trial_id", "tool_call_key"]
    ]
    assert _csv_rows(out_dir / "judgment_rule_uses.csv") == [
        ["judgment_rule", "use_count", "trial_count"],
        ["treat_path_that_ends_another_as_same_file", "2", "1"],
    ]
    knowledge_row_uses = _csv_rows(out_dir / "knowledge_row_uses.csv")
    assert knowledge_row_uses[0] == ["catalog", "row_key", "use_count", "trial_count"]
    # bash and cat are each asked once, on the one trial that ran, though t1 was given twice.
    assert ["program_behaviors.csv", "bash ", "1", "1"] in knowledge_row_uses
    assert ["program_behaviors.csv", "cat ", "1", "1"] in knowledge_row_uses


def test_main_names_a_trial_that_raised_and_exits_1(tmp_path, monkeypatch):
    def raise_error(*arguments: object, **keywords: object) -> None:
        raise RuntimeError

    monkeypatch.setattr(audit, "run_steps_to_expanded_tool_calls", raise_error)
    out_dir = tmp_path / "out"

    with pytest.raises(SystemExit) as exit_info:
        _run_main(monkeypatch, _raw_trials_dir(tmp_path), out_dir)

    assert exit_info.value.code == 1
    assert _csv_rows(out_dir / "trials_not_expanded.csv") == [
        ["trial_id", "outcome"],
        ["t1", "exception RuntimeError"],
        ["t9", "not found"],
    ]
