"""Tests for expanded_tool_call/_expand_output_routes.py, on texts split by `parse_shell_text` and a made-up program catalog whose rows the cases name, so that a case does not change when the real catalog gains rows."""

from collections import Counter

import pytest

from tb_internet_use.expanded_tool_call._expand_output_routes import (
    PipeReader,
    expand_output_routes,
    pipe_reader_of,
)
from tb_internet_use.expanded_tool_call._expand_program_invocations import (
    expand_program_invocations,
)
from tb_internet_use.expanded_tool_call.model import (
    OutputRouteEnd,
    OutputVisibility,
)
from tb_internet_use.knowledge.expanded_tool_call_knowledge import (
    ExpandedToolCallKnowledge,
)
from tb_internet_use.tool_call.model import (
    CaptureDestination,
    DiscardDestination,
    FileDestination,
    ParsedShellText,
    PipeDestination,
    ResultDestination,
    ShellCommand,
)
from tb_internet_use.tool_call.parse_shell_text import parse_shell_text

RESULT = ResultDestination()
WHOLE = OutputVisibility.WHOLE
PARTIAL = OutputVisibility.PARTIAL
NONE = OutputVisibility.NONE
UNKNOWN = OutputVisibility.UNKNOWN

# Made-up rows, each named by the program and the cells that differ from the defaults of `conftest.py`.
# curl, jq and xargs leave `visibility_of_piped_input` blank. keep passes on part of its input and writes a file, so it is no tee. mytool has no row.
PROGRAM_BEHAVIOR_ROWS: list[dict[str, str]] = [
    {"program_name": "curl"},
    {"program_name": "jq", "argument_role": "read_file"},
    {
        "program_name": "tail",
        "argument_role": "read_file",
        "visibility_of_piped_input": "partial",
    },
    {
        "program_name": "grep",
        "argument_role": "read_file",
        "first_argument_role": "pattern",
        "visibility_of_piped_input": "partial",
    },
    {
        "program_name": "cat",
        "argument_role": "read_file",
        "visibility_of_piped_input": "whole",
    },
    {
        "program_name": "tee",
        "argument_role": "written_file",
        "visibility_of_piped_input": "whole",
    },
    {
        "program_name": "keep",
        "argument_role": "written_file",
        "visibility_of_piped_input": "partial",
    },
    {"program_name": "tar", "visibility_of_piped_input": "none"},
    {
        "program_name": "sudo",
        "argument_role": "program",
        "options_end_at_first_argument": "yes",
        "exits_with_exit_code_of_next_program": "yes",
        "visibility_of_piped_input": "none",
    },
    {
        "program_name": "xargs",
        "argument_role": "program",
        "options_end_at_first_argument": "yes",
        "gives_arguments_at_run_time": "yes",
    },
    {"program_name": "ls", "argument_role": "size_or_type_file"},
]
# Made-up rows, each named by the program, the option and the cells that differ from the defaults of `conftest.py`.
PROGRAM_OPTION_BEHAVIOR_ROWS: list[dict[str, str]] = [
    {
        "program_name": "tee",
        "option_name": "-a",
        "argument_role_with_option": "appended_file",
    },
    {
        "program_name": "tail",
        "option_name": "-n",
        "takes_value": "yes",
        "value_role": "other",
    },
]

# (shell text, stream of its first curl or ls, expected routes as the first words of the pipe readers, the end and the share at the end)
ROUTE_CASES: list[
    tuple[str, str, list[tuple[list[str], OutputRouteEnd, OutputVisibility]]]
] = [
    ("curl u", "stdout", [([], RESULT, WHOLE)]),
    ("curl u | tail -n 1", "stdout", [(["tail"], RESULT, PARTIAL)]),
    ("curl u 2>&1 | tail -n 1", "stderr", [(["tail"], RESULT, PARTIAL)]),
    # Only stderr goes to the pipe, since stdout is sent to /dev/null after stderr took the pipe.
    ("curl u 2>&1 >/dev/null | tail -n 1", "stderr", [(["tail"], RESULT, PARTIAL)]),
    (
        "curl u 2>&1 >/dev/null | tail -n 1",
        "stdout",
        [([], DiscardDestination(), WHOLE)],
    ),
    ("curl u | cat | cat", "stdout", [(["cat", "cat"], RESULT, WHOLE)]),
    # xargs hands the piped input to the next program as arguments, so cat shows the files it names and tee never reads the pipe.
    ("curl u | xargs cat", "stdout", [(["xargs"], RESULT, UNKNOWN)]),
    ("curl u | xargs tee log", "stdout", [(["xargs"], RESULT, UNKNOWN)]),
    ("ls | xargs cat", "stdout", [(["xargs"], RESULT, UNKNOWN)]),
    ("curl u | mytool", "stdout", [(["mytool"], RESULT, UNKNOWN)]),
    # A reader with a row whose cell is blank is as unknown as one without a row.
    ("curl u | jq .", "stdout", [(["jq"], RESULT, UNKNOWN)]),
    # The least share of the readers wins, whatever their order.
    ("curl u | mytool | tar x", "stdout", [(["mytool", "tar"], RESULT, NONE)]),
    ("curl u | tar x | mytool", "stdout", [(["tar", "mytool"], RESULT, NONE)]),
    ("curl u | grep a | cat", "stdout", [(["grep", "cat"], RESULT, PARTIAL)]),
    ("curl u | cat | grep a", "stdout", [(["cat", "grep"], RESULT, PARTIAL)]),
    # A reader in the middle counts as much as the first and the last.
    ("curl u | cat | tar x | cat", "stdout", [(["cat", "tar", "cat"], RESULT, NONE)]),
    (
        "curl u | cat | grep a | cat",
        "stdout",
        [(["cat", "grep", "cat"], RESULT, PARTIAL)],
    ),
    ("curl u | mytool | grep a", "stdout", [(["mytool", "grep"], RESULT, UNKNOWN)]),
    ("curl u | grep a | mytool", "stdout", [(["grep", "mytool"], RESULT, UNKNOWN)]),
    # The share comes from the innermost program, e.g. tail and not sudo.
    ("curl u | sudo tail -n 1", "stdout", [(["sudo"], RESULT, PARTIAL)]),
    (
        "curl u | tee log | tail -n 1",
        "stdout",
        [
            (["tee", "tail"], RESULT, PARTIAL),
            (["tee"], FileDestination("log", False), WHOLE),
        ],
    ),
    (
        "curl u | grep a | tee -a log",
        "stdout",
        [
            (["grep", "tee"], RESULT, PARTIAL),
            (["grep", "tee"], FileDestination("log", True), PARTIAL),
        ],
    ),
    (
        "curl u | tee one two",
        "stdout",
        [
            (["tee"], RESULT, WHOLE),
            (["tee"], FileDestination("one", False), WHOLE),
            (["tee"], FileDestination("two", False), WHOLE),
        ],
    ),
    (
        "curl u | tee log > /dev/null",
        "stdout",
        [
            (["tee"], DiscardDestination(), WHOLE),
            (["tee"], FileDestination("log", False), WHOLE),
        ],
    ),
    # The path of tee stays as written, as a path of `curl -o` does.
    (
        "curl u | tee /dev/null",
        "stdout",
        [
            (["tee"], RESULT, WHOLE),
            (["tee"], FileDestination("/dev/null", False), WHOLE),
        ],
    ),
    (
        "curl u | sudo tee log",
        "stdout",
        [
            (["sudo"], RESULT, WHOLE),
            (["sudo"], FileDestination("log", False), WHOLE),
        ],
    ),
    # keep writes a file but does not pass on all of its input, so its file is not an end of the output.
    ("curl u | keep out", "stdout", [(["keep"], RESULT, PARTIAL)]),
    (
        "curl u > >(tee log)",
        "stdout",
        [
            (["tee"], RESULT, WHOLE),
            (["tee"], FileDestination("log", False), WHOLE),
        ],
    ),
    # Only the first command of a stage reads the pipe.
    ("curl u | { grep a; tar x; }", "stdout", [(["grep"], RESULT, PARTIAL)]),
    ("X=$(curl u)", "stdout", [([], CaptureDestination(), WHOLE)]),
    ("X=$(curl u | tail -n 1)", "stdout", [(["tail"], CaptureDestination(), PARTIAL)]),
]


def _parsed_shell_text_of(shell_text: str) -> ParsedShellText:
    parsed_shell_text = parse_shell_text(shell_text, judgment_rule_use_counts=Counter())
    assert isinstance(parsed_shell_text, ParsedShellText)
    return parsed_shell_text


def _pipe_reader_for(
    shell_command: ShellCommand, knowledge: ExpandedToolCallKnowledge
) -> PipeReader:
    program_invocations, word_roles, program_behaviors = expand_program_invocations(
        shell_command, knowledge=knowledge, judgment_rule_use_counts=Counter()
    )
    return pipe_reader_of(
        shell_command, program_invocations, word_roles, program_behaviors
    )


@pytest.mark.parametrize(("shell_text", "stream", "routes"), ROUTE_CASES)
def test_output_is_followed_through_its_pipe_readers_to_each_end_with_the_share_left_there(
    catalogs_dir, shell_text, stream, routes
):
    knowledge = ExpandedToolCallKnowledge(catalogs_dir=catalogs_dir)
    shell_commands = _parsed_shell_text_of(shell_text).commands
    shell_commands_by_id = {command.id: command for command in shell_commands}
    pipe_readers_by_command_id = {
        command.id: _pipe_reader_for(command, knowledge) for command in shell_commands
    }
    followed_command = next(
        command for command in shell_commands if command.words[0] in ("curl", "ls")
    )
    output_routes = expand_output_routes(
        getattr(followed_command, stream), pipe_readers_by_command_id
    )
    assert [
        (
            [
                shell_commands_by_id[command_id].words[0]
                for command_id in route.pipe_reader_command_ids
            ],
            route.end,
            route.visibility_at_end,
        )
        for route in output_routes
    ] == routes


@pytest.mark.parametrize(
    ("shell_text", "pipe_reader_command_ids_of_routes"),
    [
        ("cat a | curl u | tee log | tail -n 1", [(2, 3), (2,)]),
        ("cat a | curl u | cat | grep a | cat", [(2, 3, 4)]),
    ],
)
def test_route_holds_the_ids_of_its_pipe_readers_in_order(
    catalogs_dir, shell_text, pipe_reader_command_ids_of_routes
):
    knowledge = ExpandedToolCallKnowledge(catalogs_dir=catalogs_dir)
    shell_commands = _parsed_shell_text_of(shell_text).commands
    pipe_readers_by_command_id = {
        command.id: _pipe_reader_for(command, knowledge) for command in shell_commands
    }
    output_routes = expand_output_routes(
        shell_commands[1].stdout, pipe_readers_by_command_id
    )
    assert [
        route.pipe_reader_command_ids for route in output_routes
    ] == pipe_reader_command_ids_of_routes


def test_reader_without_a_program_word_passes_on_an_unknown_share():
    reader = ShellCommand(1, ())
    pipe_reader = pipe_reader_of(reader, (), (), ())
    assert pipe_reader == PipeReader(reader, UNKNOWN, ())
    output_routes = expand_output_routes(PipeDestination(1), {1: pipe_reader})
    assert [route.visibility_at_end for route in output_routes] == [UNKNOWN]
