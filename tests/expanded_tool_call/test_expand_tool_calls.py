"""Tests for expanded_tool_call/_expand_tool_calls.py, on made-up trials and a made-up program catalog whose rows the cases name, so that a case does not change when the real catalog gains rows.

The first cases follow the made-up trial of `docs/pipeline-example.md` through the entry function. The next four check an empty trial, calls that run nothing, the order of the calls and the counts of the pieces. The others take one row each of the two case tables of the step, i.e. what a call ran and where its output shows up.
"""

from collections import Counter
from pathlib import Path

import pytest

from tb_internet_use.expanded_tool_call import expand_tool_calls
from tb_internet_use.expanded_tool_call.model import (
    ArgumentText,
    CallCommandText,
    CodeLanguage,
    CommandTextStatus,
    ExpandedToolCall,
    FileText,
    FileTextWithoutKnownWriter,
    FileUse,
    FileUseKind,
    FileUseWithoutKnownWriter,
    FileWriteChannel,
    OutputPlace,
    OutputRoute,
    OutputRouteEnd,
    OutputVisibility,
    ProgramInvocation,
    ProgramOption,
    RanCodeText,
    RanCommand,
    RanShellText,
    RanText,
    StdinText,
    UnknownExitsWithExitCodeOfNextProgram,
    UnknownProgramInvocation,
    UnknownRanText,
    UnknownRanTextReason,
    VariableValues,
    WrittenFile,
    WrittenFileWriter,
)
from tb_internet_use.knowledge.expanded_tool_call_knowledge import (
    ExpandedToolCallKnowledge,
)
from tb_internet_use.tool_call.model import (
    DiscardDestination,
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    FileDestination,
    HarnessTool,
    HarnessToolCall,
    ParsedShellText,
    PollAction,
    ReadFileAction,
    ResultDestination,
    RunCommandAction,
    ShellCommand,
    StartSubagentAction,
    ToolCall,
    ToolCallAction,
    ToolCallKey,
    ToolCallResult,
    WriteFileAction,
)
from tb_internet_use.tool_call.parse_shell_text import parse_shell_text

Reason = UnknownRanTextReason
Channel = FileWriteChannel
UseKind = FileUseKind
WHOLE = OutputVisibility.WHOLE
TASK_1 = ExecutionHandle(ExecutionHandleKind.COMMAND, "task-1")
FINISHED = ToolCallResult(
    tool_output_text="", execution_status=ExecutionStatus.FINISHED, exit_code=0
)

# Made-up rows, each named by the program and the cells that differ from the defaults of `conftest.py`. mytool has no row.
PROGRAM_BEHAVIOR_ROWS: list[dict[str, str]] = [
    {
        "program_name": "bash",
        "first_argument_role": "run_file",
        "stdin_role": "run_text",
        "options_end_at_first_argument": "yes",
    },
    {
        "program_name": "sudo",
        "argument_role": "program",
        "options_end_at_first_argument": "yes",
        "exits_with_exit_code_of_next_program": "yes",
    },
    {
        "program_name": "curl",
        "argument_role": "",
        "exits_with_exit_code_of_next_program": "",
    },
    {
        "program_name": "pip",
        "subcommand": "install",
        "argument_role": "",
        "first_argument_role": "",
        "last_argument_role": "",
        "exits_with_exit_code_of_next_program": "",
    },
    {"program_name": "echo"},
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
    {"program_name": "chmod"},
    {
        "program_name": "sed",
        "argument_role": "read_file",
        "first_argument_role": "pattern",
    },
    {"program_name": "make", "default_run_file": "Makefile"},
    {
        "program_name": "python",
        "first_argument_role": "run_file",
        "stdin_role": "run_text",
        "options_end_at_first_argument": "yes",
    },
    {"program_name": "ls", "argument_role": "size_or_type_file"},
    {"program_name": "tar", "first_argument_role": "option_cluster"},
]
# Made-up rows, each named by the program, the option and the cells that differ from the defaults of `conftest.py`.
PROGRAM_OPTION_BEHAVIOR_ROWS: list[dict[str, str]] = [
    {
        "program_name": "bash",
        "option_name": "-c",
        "first_argument_role_with_option": "run_text",
    },
    {"program_name": "curl", "option_name": "-s"},
    {"program_name": "curl", "option_name": "-S"},
    {
        "program_name": "curl",
        "option_name": "-O",
        "argument_role_with_option": "written_file_source",
    },
    {
        "program_name": "curl",
        "option_name": "-o",
        "takes_value": "yes",
        "value_role": "written_file",
    },
    {
        "program_name": "curl",
        "option_name": "--connect-timeout",
        "takes_value": "yes",
        "value_role": "other",
    },
    {"program_name": "chmod", "option_name": "+x"},
    {
        "program_name": "sed",
        "option_name": "-i",
        "argument_role_with_option": "changed_file",
    },
    {"program_name": "tar", "option_name": "-x"},
    {"program_name": "tar", "option_name": "-z"},
    {
        "program_name": "tar",
        "option_name": "-f",
        "takes_value": "yes",
        "value_role": "used_file",
    },
]
# Made-up code runner rows, with the cells that differ from the defaults of `conftest.py`.
CODE_RUNNER_ROWS: list[dict[str, str]] = [
    {"runner_kind": "program_name", "runner": "bash"},
    {"runner_kind": "file_extension", "runner": ".sh"},
    {
        "runner_kind": "program_name",
        "runner": "python",
        "ran_text_language": "python",
    },
]


def _key(step_id: int) -> ToolCallKey:
    return ToolCallKey("t1", "main", step_id, 0)


K1, K2, K3, K4, K5, K6 = (_key(step_id) for step_id in range(1, 7))


def _command(text: str) -> RunCommandAction:
    return RunCommandAction(
        text, parse_shell_text(text, judgment_rule_use_counts=Counter())
    )


def _call(
    step_id: int,
    action: ToolCallAction | str,
    result: ToolCallResult | None = FINISHED,
) -> ToolCall:
    """Make a call at a step of the main trajectory, taking a string as the command of a `RunCommandAction`."""
    return ToolCall(
        HarnessToolCall(_key(step_id), HarnessTool("harness", "tool"), "", {}, None),
        _command(action) if isinstance(action, str) else action,
        result,
    )


def _shell_commands_of(tool_call: ToolCall) -> tuple[ShellCommand, ...]:
    """Give the commands that `parse_shell_text` split the call's own command text into."""
    assert isinstance(tool_call.action, RunCommandAction)
    parsed_shell_text = tool_call.action.parsed_shell_text
    assert isinstance(parsed_shell_text, ParsedShellText)
    return parsed_shell_text.commands


@pytest.fixture
def knowledge(catalogs_dir: Path) -> ExpandedToolCallKnowledge:
    # A new door for each test, so that a test of the counts sees only its own lookups.
    return ExpandedToolCallKnowledge(catalogs_dir=catalogs_dir)


def _expand(
    knowledge: ExpandedToolCallKnowledge,
    *tool_calls: ToolCall,
    judgment_rule_use_counts: Counter[str] | None = None,
) -> tuple[ExpandedToolCall, ...]:
    return expand_tool_calls(
        tool_calls,
        knowledge=knowledge,
        judgment_rule_use_counts=Counter()
        if judgment_rule_use_counts is None
        else judgment_rule_use_counts,
    )


def _words_of_ran_texts(
    expanded_tool_call: ExpandedToolCall,
) -> list[tuple[object, tuple[tuple[str, ...], ...] | UnknownRanTextReason]]:
    """Give each text the call ran as its source and the words of its commands, or its source and the reason it is unknown."""
    return [
        (
            ran_text.source,
            tuple(
                ran_command.shell_command.words for ran_command in ran_text.ran_commands
            ),
        )
        if isinstance(ran_text, RanShellText)
        else (ran_text.source, _reason_of(ran_text))
        for ran_text in expanded_tool_call.ran_texts
    ]


def _first_ran_command_of(expanded_tool_call: ExpandedToolCall) -> RanCommand:
    """Give the first command of the call's own text."""
    ran_shell_text = expanded_tool_call.ran_texts[0]
    assert isinstance(ran_shell_text, RanShellText)
    return ran_shell_text.ran_commands[0]


def _reason_of(ran_text: RanText) -> UnknownRanTextReason:
    assert isinstance(ran_text, UnknownRanText)
    return ran_text.reason


# The made-up trial of `docs/pipeline-example.md`, with the result texts shortened.
C1_TEXT = "curl -sS --connect-timeout 30 -O https://a.example.org/x.tgz; curl -sS --connect-timeout 30 -O https://b.example.org/y.tgz; echo done"
FETCH_SH_CONTENT = "curl -sS -O https://data.example.org/a.tgz"
C3_TEXT = "bash fetch.sh > fetch.log 2>&1 || pip install requests"


def _example_trial() -> tuple[ToolCall, ...]:
    return (
        _call(1, C1_TEXT),
        _call(2, WriteFileAction("fetch.sh", FETCH_SH_CONTENT)),
        _call(
            3,
            C3_TEXT,
            ToolCallResult(
                tool_output_text="",
                execution_status=ExecutionStatus.RUNNING,
                handles=(TASK_1,),
            ),
        ),
        _call(
            4,
            PollAction((TASK_1,)),
            ToolCallResult(
                tool_output_text="Successfully installed requests-2.32.3",
                execution_status=ExecutionStatus.FINISHED,
                exit_code=0,
                handles=(TASK_1,),
            ),
        ),
        _call(
            5,
            ReadFileAction("fetch.log"),
            ToolCallResult(
                tool_output_text="curl: (6) Could not resolve host",
                execution_status=ExecutionStatus.FINISHED,
            ),
        ),
        _call(6, "bash setup.sh"),
    )


def _route(end: OutputRouteEnd, visibility: OutputVisibility = WHOLE) -> OutputRoute:
    return OutputRoute((), end, visibility)


def _curl(url: str, *options: ProgramOption) -> ProgramInvocation:
    """Give the reading of `curl` with the options and the URL as its one argument."""
    return ProgramInvocation(
        "curl", (), options, (url,), False, (), UnknownExitsWithExitCodeOfNextProgram()
    )


def test_the_example_call_with_two_downloads_runs_only_its_own_text_and_shows_all_in_its_result(
    knowledge,
):
    c1 = _example_trial()[0]
    curl_x, curl_y, echo_done = _shell_commands_of(c1)
    curl_options = (
        ProgramOption("-s", None),
        ProgramOption("-S", None),
        ProgramOption("--connect-timeout", "30"),
        ProgramOption("-O", None),
    )
    result_routes = (_route(ResultDestination()),)

    c1_expanded = _expand(knowledge, *_example_trial())[0]

    assert c1_expanded == ExpandedToolCall(
        tool_call=c1,
        ran_texts=(
            RanShellText(
                CallCommandText(),
                (
                    RanCommand(
                        curl_x,
                        (_curl("https://a.example.org/x.tgz", *curl_options),),
                        (),
                        result_routes,
                        result_routes,
                    ),
                    RanCommand(
                        curl_y,
                        (_curl("https://b.example.org/y.tgz", *curl_options),),
                        (),
                        result_routes,
                        result_routes,
                    ),
                    RanCommand(
                        echo_done,
                        (
                            ProgramInvocation(
                                "echo", (), (), ("done",), False, (), False
                            ),
                        ),
                        (),
                        result_routes,
                        result_routes,
                    ),
                ),
            ),
        ),
        command_text_status=CommandTextStatus(ExecutionStatus.FINISHED, 0, K1),
        output_places=(OutputPlace(K1, (0, 1, 2)),),
        written_files=(
            WrittenFile("x.tgz", (WrittenFileWriter(0, Channel.OWN_OUTPUT_FILE),), ()),
            WrittenFile("y.tgz", (WrittenFileWriter(1, Channel.OWN_OUTPUT_FILE),), ()),
        ),
        file_uses_without_known_writer=(),
    )


def test_the_example_write_tool_call_holds_the_file_that_the_background_call_runs(
    knowledge,
):
    c2 = _example_trial()[1]

    c2_expanded = _expand(knowledge, *_example_trial())[1]

    assert c2_expanded == ExpandedToolCall(
        tool_call=c2,
        ran_texts=(),
        command_text_status=None,
        output_places=(),
        written_files=(
            WrittenFile(
                "fetch.sh",
                (WrittenFileWriter(None, Channel.TOOL_ARGUMENT),),
                (FileUse(K3, 0, UseKind.USES_CONTENT, False),),
            ),
        ),
        file_uses_without_known_writer=(),
    )


def test_the_example_background_call_runs_the_written_file_and_shows_in_its_poll_and_its_log_read(
    knowledge,
):
    c3 = _example_trial()[2]
    bash_fetch_sh, pip_install_requests = _shell_commands_of(c3)
    fetch_log = FileDestination("fetch.log", appends=False)
    # The command of fetch.sh gets the next id of the call and the redirects of `bash fetch.sh`.
    curl_a_tgz = ShellCommand(
        id=2, words=tuple(FETCH_SH_CONTENT.split()), stdout=fetch_log, stderr=fetch_log
    )
    fetch_log_routes = (_route(fetch_log),)
    result_routes = (_route(ResultDestination()),)

    c3_expanded = _expand(knowledge, *_example_trial())[2]

    assert c3_expanded == ExpandedToolCall(
        tool_call=c3,
        ran_texts=(
            RanShellText(
                CallCommandText(),
                (
                    RanCommand(
                        bash_fetch_sh,
                        (
                            ProgramInvocation(
                                "bash", (), (), ("fetch.sh",), False, (), False
                            ),
                        ),
                        (),
                        fetch_log_routes,
                        fetch_log_routes,
                    ),
                    RanCommand(
                        pip_install_requests,
                        (
                            ProgramInvocation(
                                "pip",
                                ("install",),
                                (),
                                ("requests",),
                                False,
                                (),
                                UnknownExitsWithExitCodeOfNextProgram(),
                            ),
                        ),
                        (),
                        result_routes,
                        result_routes,
                    ),
                ),
            ),
            RanShellText(
                FileText(0, "fetch.sh", K2),
                (
                    RanCommand(
                        curl_a_tgz,
                        (
                            _curl(
                                "https://data.example.org/a.tgz",
                                ProgramOption("-s", None),
                                ProgramOption("-S", None),
                                ProgramOption("-O", None),
                            ),
                        ),
                        (),
                        fetch_log_routes,
                        fetch_log_routes,
                    ),
                ),
            ),
        ),
        # c3 returned while running, so the end state is the one c4 saw.
        command_text_status=CommandTextStatus(ExecutionStatus.FINISHED, 0, K4),
        # Only pip's output reaches a result. The output of bash and curl went to fetch.log, which c5 reads.
        output_places=(OutputPlace(K3, (1,)), OutputPlace(K4, (1,))),
        written_files=(
            WrittenFile(
                "fetch.log",
                (
                    WrittenFileWriter(0, Channel.STDOUT),
                    WrittenFileWriter(0, Channel.STDERR),
                    WrittenFileWriter(2, Channel.STDOUT),
                    WrittenFileWriter(2, Channel.STDERR),
                ),
                (FileUse(K5, None, UseKind.SHOWS_CONTENT, False),),
            ),
            WrittenFile("a.tgz", (WrittenFileWriter(2, Channel.OWN_OUTPUT_FILE),), ()),
        ),
        file_uses_without_known_writer=(),
    )


@pytest.mark.parametrize("call_index", [3, 4])
def test_the_example_poll_and_log_read_run_nothing_and_use_only_written_files(
    knowledge, call_index
):
    example_trial = _example_trial()

    expanded_tool_call = _expand(knowledge, *example_trial)[call_index]

    assert expanded_tool_call == ExpandedToolCall(
        example_trial[call_index], (), None, (), (), ()
    )


def test_the_example_call_of_a_script_no_call_wrote_records_it_as_unknown(knowledge):
    c6 = _example_trial()[5]
    (bash_setup_sh,) = _shell_commands_of(c6)
    result_routes = (_route(ResultDestination()),)

    c6_expanded = _expand(knowledge, *_example_trial())[5]

    assert c6_expanded == ExpandedToolCall(
        tool_call=c6,
        ran_texts=(
            RanShellText(
                CallCommandText(),
                (
                    RanCommand(
                        bash_setup_sh,
                        (
                            ProgramInvocation(
                                "bash", (), (), ("setup.sh",), False, (), False
                            ),
                        ),
                        (),
                        result_routes,
                        result_routes,
                    ),
                ),
            ),
            UnknownRanText(
                FileTextWithoutKnownWriter(0, "setup.sh"), Reason.NOT_WRITTEN_IN_TRIAL
            ),
        ),
        command_text_status=CommandTextStatus(ExecutionStatus.FINISHED, 0, K6),
        output_places=(OutputPlace(K6, (0,)),),
        written_files=(),
        file_uses_without_known_writer=(
            FileUseWithoutKnownWriter(0, "setup.sh", UseKind.USES_CONTENT),
        ),
    )


def test_the_example_counts_the_rules_and_the_catalog_rows_it_used(knowledge):
    judgment_rule_use_counts: Counter[str] = Counter()

    _expand(
        knowledge, *_example_trial(), judgment_rule_use_counts=judgment_rule_use_counts
    )

    # c3 has one poll that saw its end, and nothing else in the trial asks a rule.
    assert judgment_rule_use_counts == Counter(
        {"treat_first_poll_that_saw_end_as_command_text_status": 1}
    )
    assert knowledge.uses.row_use_counts[("program_behaviors.csv", ("curl", ""))] == 3
    assert knowledge.uses.row_use_counts[("program_behaviors.csv", ("bash", ""))] == 2
    assert knowledge.uses.unknown_input_counts == Counter()


def test_an_empty_trial_expands_into_nothing(knowledge):
    judgment_rule_use_counts: Counter[str] = Counter()

    assert _expand(knowledge, judgment_rule_use_counts=judgment_rule_use_counts) == ()
    assert judgment_rule_use_counts == Counter()


def test_calls_that_run_nothing_get_empty_fields(knowledge):
    tool_calls = (
        _call(1, StartSubagentAction()),
        _call(2, PollAction((TASK_1,))),
        _call(3, RunCommandAction()),
    )

    expanded_tool_calls = _expand(knowledge, *tool_calls)

    assert expanded_tool_calls[:2] == (
        ExpandedToolCall(tool_calls[0], (), None, (), (), ()),
        ExpandedToolCall(tool_calls[1], (), None, (), (), ()),
    )
    # A command action without a command text ran something that the trajectory does not hold.
    assert expanded_tool_calls[2] == ExpandedToolCall(
        tool_calls[2],
        (UnknownRanText(CallCommandText(), Reason.MISSING_FROM_TRAJECTORY),),
        None,
        (),
        (),
        (),
    )


def test_each_expanded_call_keeps_the_place_of_its_tool_call_in_the_input(knowledge):
    # The steps are out of order, so an expansion that sorts the calls or mixes up their fields fails.
    later_reader = _call(7, "cat log")
    earlier_writer = _call(3, "echo a > log")
    unrelated = _call(5, "bash setup.sh")

    expanded_tool_calls = _expand(knowledge, later_reader, earlier_writer, unrelated)

    assert [
        expanded_tool_call.tool_call for expanded_tool_call in expanded_tool_calls
    ] == [later_reader, earlier_writer, unrelated]
    assert [
        expanded_tool_call.file_uses_without_known_writer
        for expanded_tool_call in expanded_tool_calls
    ] == [
        (FileUseWithoutKnownWriter(0, "log", UseKind.SHOWS_CONTENT),),
        (),
        (FileUseWithoutKnownWriter(0, "setup.sh", UseKind.USES_CONTENT),),
    ]
    assert [
        expanded_tool_call.command_text_status.reporter_tool_call_key
        for expanded_tool_call in expanded_tool_calls
        if expanded_tool_call.command_text_status is not None
    ] == [_key(7), _key(3), _key(5)]
    assert [
        len(expanded_tool_call.written_files)
        for expanded_tool_call in expanded_tool_calls
    ] == [0, 1, 0]


def test_the_counts_of_every_piece_reach_the_counter_of_the_caller(knowledge):
    tool_calls = (
        _call(
            1,
            "curl a; curl b",
            ToolCallResult(
                tool_output_text="",
                execution_status=ExecutionStatus.RUNNING,
                handles=(TASK_1,),
            ),
        ),
        _call(
            2,
            PollAction((TASK_1,)),
            ToolCallResult(
                tool_output_text="",
                execution_status=ExecutionStatus.FINISHED,
                exit_code=0,
                handles=(TASK_1,),
            ),
        ),
        _call(3, "echo x > f.log; echo y > f.log"),
        _call(4, "cat f.log; mytool $X"),
        # c5 starts the handle of c1 again, so the poll c6 asks which start it reads.
        _call(
            5,
            "echo b",
            ToolCallResult(
                tool_output_text="",
                execution_status=ExecutionStatus.RUNNING,
                handles=(TASK_1,),
            ),
        ),
        _call(
            6,
            PollAction((TASK_1,)),
            ToolCallResult(
                tool_output_text="",
                execution_status=ExecutionStatus.RUNNING,
                handles=(TASK_1,),
            ),
        ),
        # The path that c8 runs ends the path that c7 wrote.
        _call(7, WriteFileAction("/app/run.sh", "echo a")),
        _call(8, "bash run.sh"),
    )
    judgment_rule_use_counts: Counter[str] = Counter()

    _expand(knowledge, *tool_calls, judgment_rule_use_counts=judgment_rule_use_counts)

    assert judgment_rule_use_counts == Counter(
        {
            # From `expand_poll_links`, for the handle of c6 that c1 and c5 started.
            "treat_poll_as_reading_latest_earlier_start_of_handle": 1,
            # From `expand_ran_texts`, which matches run.sh to /app/run.sh once to follow its text and once to record its use.
            "treat_path_that_ends_another_as_same_file": 2,
            # From `expand_command_text_status`.
            "treat_first_poll_that_saw_end_as_command_text_status": 1,
            # From `expand_output_places`, for the two commands of c1 in its poll c2.
            "treat_poll_result_as_showing_every_command_of_starter": 1,
        }
    )
    assert knowledge.uses.unknown_input_counts == Counter(
        {("program_behaviors.csv", ("mytool", "")): 1}
    )


# One case per row of the table of what a call ran. The text is followed when the trajectory holds it at the moment it runs, and what is unknown is recorded when it does not.


def test_ran_text_inside_the_same_call_is_followed(knowledge):
    (expanded_tool_call,) = _expand(knowledge, _call(1, "sudo bash -c 'curl u'"))

    assert _words_of_ran_texts(expanded_tool_call) == [
        (CallCommandText(), (("sudo", "bash", "-c", "curl u"),)),
        (ArgumentText(0), (("curl", "u"),)),
    ]
    sudo, bash = _first_ran_command_of(expanded_tool_call).program_invocations
    assert sudo == ProgramInvocation("sudo", (), (), (), False, (), True)
    assert bash == ProgramInvocation(
        "bash", (), (ProgramOption("-c", None),), ("curl u",), False, (), False
    )


def test_a_variable_set_in_the_same_call_gives_its_value(knowledge):
    (expanded_tool_call,) = _expand(knowledge, _call(1, "U=a.org; curl $U"))

    curl = _first_ran_command_of(expanded_tool_call)
    assert curl.shell_command.words == ("curl", "$U")
    assert curl.variable_values == (VariableValues("U", ("a.org",), False, False),)


def test_a_file_an_earlier_call_wrote_and_a_heredoc_are_followed(knowledge):
    writer = _call(1, WriteFileAction("fetch.sh", "curl a"))
    runner = _call(2, "bash fetch.sh")
    heredoc = _call(3, "python - <<EOF\nimport x\nEOF")

    _, runner_expanded, heredoc_expanded = _expand(knowledge, writer, runner, heredoc)

    assert _words_of_ran_texts(runner_expanded)[1] == (
        FileText(0, "fetch.sh", K1),
        (("curl", "a"),),
    )
    assert heredoc_expanded.ran_texts[1:] == (
        RanCodeText(StdinText(0), CodeLanguage.PYTHON, "import x\n"),
    )


def test_a_file_whose_content_is_not_in_the_trajectory_is_run_but_unknown(knowledge):
    expanded_tool_calls = _expand(
        knowledge, _call(1, "bash setup.sh"), _call(2, "make"), _call(3, "./a.out")
    )

    assert [
        expanded_tool_call.ran_texts[1:] for expanded_tool_call in expanded_tool_calls
    ] == [
        (
            UnknownRanText(
                FileTextWithoutKnownWriter(0, "setup.sh"), Reason.NOT_WRITTEN_IN_TRIAL
            ),
        ),
        (
            UnknownRanText(
                FileTextWithoutKnownWriter(0, None), Reason.NOT_WRITTEN_IN_TRIAL
            ),
        ),
        (
            UnknownRanText(
                FileTextWithoutKnownWriter(0, "./a.out"), Reason.NOT_WRITTEN_IN_TRIAL
            ),
        ),
    ]
    assert [
        expanded_tool_call.file_uses_without_known_writer
        for expanded_tool_call in expanded_tool_calls
    ] == [
        (FileUseWithoutKnownWriter(0, "setup.sh", UseKind.USES_CONTENT),),
        (FileUseWithoutKnownWriter(0, "Makefile", UseKind.USES_CONTENT),),
        (FileUseWithoutKnownWriter(0, "./a.out", UseKind.USES_CONTENT),),
    ]


def test_a_value_set_at_run_time_is_unknown(knowledge):
    substitution, built_text = _expand(
        knowledge, _call(1, "curl $(cat urls.txt)"), _call(2, 'bash -c "$CMD"')
    )

    # The substitution is a command of the call's own text, and curl's word keeps it as written, with no value.
    assert _words_of_ran_texts(substitution) == [
        (CallCommandText(), (("curl", "$(cat urls.txt)"), ("cat", "urls.txt")))
    ]
    curl = _first_ran_command_of(substitution)
    assert curl.shell_command.expansion_word_indexes == (1,)
    assert curl.variable_values == ()
    assert built_text.ran_texts[1:] == (
        UnknownRanText(ArgumentText(0), Reason.BUILT_AT_RUN_TIME),
    )


def test_a_program_that_no_fact_covers_runs_nothing_that_is_followed(knowledge):
    (expanded_tool_call,) = _expand(knowledge, _call(1, "mytool run x"))

    assert expanded_tool_call.ran_texts[1:] == ()
    assert _first_ran_command_of(expanded_tool_call).program_invocations == (
        UnknownProgramInvocation("mytool", ("run", "x")),
    )


def test_a_file_that_only_reading_commands_touch_after_its_write_runs_as_written(
    knowledge,
):
    expanded_tool_calls = _expand(
        knowledge,
        _call(1, WriteFileAction("f.sh", "curl a")),
        _call(2, "cat f.sh"),
        _call(3, "chmod +x f.sh"),
        _call(4, "bash f.sh"),
    )

    assert _words_of_ran_texts(expanded_tool_calls[3])[1] == (
        FileText(0, "f.sh", K1),
        (("curl", "a"),),
    )
    assert expanded_tool_calls[0].written_files[0].file_uses == (
        FileUse(K2, 0, UseKind.SHOWS_CONTENT, False),
        FileUse(K4, 0, UseKind.USES_CONTENT, False),
    )


@pytest.mark.parametrize(
    "running_text", ["chmod +x f.sh; ./f.sh", "chmod +x f.sh && bash f.sh"]
)
def test_a_file_that_chmod_makes_executable_runs_as_written_on_the_real_catalog(
    running_text,
):
    """Run on the real catalog folder, whose chmod row says what its file arguments are, so that a blank or wrong role there fails here."""
    expanded_tool_calls = _expand(
        ExpandedToolCallKnowledge(),
        _call(1, WriteFileAction("f.sh", "curl a")),
        _call(2, running_text),
    )

    assert _words_of_ran_texts(expanded_tool_calls[1])[1] == (
        FileText(1, "f.sh" if running_text.endswith("bash f.sh") else "./f.sh", K1),
        (("curl", "a"),),
    )


@pytest.mark.parametrize(
    ("changing_call", "writer_tool_call_key"),
    [
        (_call(2, "sed -i s/a/b/ f.sh"), K2),
        (_call(2, "curl -o f.sh u"), K2),
        (_call(2, "mytool f.sh"), K1),
    ],
)
def test_a_file_that_a_command_with_an_unknown_result_touches_before_it_runs_is_unknown(
    knowledge, changing_call, writer_tool_call_key
):
    expanded_tool_calls = _expand(
        knowledge,
        _call(1, WriteFileAction("f.sh", "curl a")),
        changing_call,
        _call(3, "bash f.sh"),
    )

    assert expanded_tool_calls[2].ran_texts[1:] == (
        UnknownRanText(
            FileText(0, "f.sh", writer_tool_call_key), Reason.CHANGED_BY_UNREAD_COMMAND
        ),
    )


# One case per row of the table of where output shows up. The output is followed when the trajectory holds the place, and gets no place in a later call when it does not.


def _stdout_routes_of_first_command(
    expanded_tool_call: ExpandedToolCall,
) -> tuple[OutputRoute, ...]:
    return _first_ran_command_of(expanded_tool_call).stdout_routes


def test_output_shows_in_the_call_result(knowledge):
    (expanded_tool_call,) = _expand(knowledge, _call(1, "curl u"))

    assert _stdout_routes_of_first_command(expanded_tool_call) == (
        _route(ResultDestination()),
    )
    assert expanded_tool_call.output_places == (OutputPlace(K1, (0,)),)


def test_output_through_a_pipe_shows_in_part(knowledge):
    (expanded_tool_call,) = _expand(knowledge, _call(1, "curl u | tail"))

    assert _stdout_routes_of_first_command(expanded_tool_call) == (
        OutputRoute((1,), ResultDestination(), OutputVisibility.PARTIAL),
    )
    assert expanded_tool_call.output_places == (OutputPlace(K1, (0, 1)),)


def test_output_in_a_file_shows_in_the_later_call_that_reads_the_file(knowledge):
    writer, reader = _expand(knowledge, _call(1, "curl u > log"), _call(2, "cat log"))

    assert writer.written_files == (
        WrittenFile(
            "log",
            (WrittenFileWriter(0, Channel.STDOUT),),
            (FileUse(K2, 0, UseKind.SHOWS_CONTENT, False),),
        ),
    )
    # curl's stderr still goes to the result.
    assert writer.output_places == (OutputPlace(K1, (0,)),)
    assert reader.file_uses_without_known_writer == ()


def test_output_in_the_background_shows_in_the_later_polls_of_its_handle(knowledge):
    running = ToolCallResult(
        tool_output_text="", execution_status=ExecutionStatus.RUNNING, handles=(TASK_1,)
    )
    ended = ToolCallResult(
        tool_output_text="",
        execution_status=ExecutionStatus.FINISHED,
        exit_code=0,
        handles=(TASK_1,),
    )

    starter, _, _ = _expand(
        knowledge,
        _call(1, "curl u", running),
        _call(2, PollAction((TASK_1,)), ended),
        _call(3, PollAction((TASK_1,)), ended),
    )

    assert starter.output_places == (
        OutputPlace(K1, (0,)),
        OutputPlace(K2, (0,)),
        OutputPlace(K3, (0,)),
    )
    assert starter.command_text_status == CommandTextStatus(
        ExecutionStatus.FINISHED, 0, K2
    )


def test_output_thrown_away_or_never_polled_shows_nowhere_else(knowledge):
    discarded, never_polled = _expand(
        knowledge,
        _call(1, "curl u > /dev/null 2>&1"),
        _call(
            2,
            "curl u",
            ToolCallResult(
                tool_output_text="",
                execution_status=ExecutionStatus.RUNNING,
                handles=(TASK_1,),
            ),
        ),
    )

    assert _stdout_routes_of_first_command(discarded) == (_route(DiscardDestination()),)
    assert discarded.output_places == ()
    assert never_polled.output_places == (OutputPlace(K2, (0,)),)
    assert never_polled.command_text_status == CommandTextStatus(
        ExecutionStatus.RUNNING, None, K2
    )


def test_output_that_a_program_no_fact_covers_receives_is_unknown(knowledge):
    (expanded_tool_call,) = _expand(knowledge, _call(1, "curl u | mytool"))

    assert _stdout_routes_of_first_command(expanded_tool_call) == (
        OutputRoute((1,), ResultDestination(), OutputVisibility.UNKNOWN),
    )


def test_a_saved_file_gets_the_later_commands_that_use_it(knowledge):
    saver, *_ = _expand(
        knowledge,
        _call(1, "curl -s -o a.tgz u"),
        _call(2, "tar xzf a.tgz"),
        _call(3, "ls a.tgz"),
        _call(4, "mytool a.tgz"),
    )

    assert saver.written_files == (
        WrittenFile(
            "a.tgz",
            (WrittenFileWriter(0, Channel.OWN_OUTPUT_FILE),),
            (
                FileUse(K2, 0, UseKind.USES_CONTENT, False),
                FileUse(K3, 0, UseKind.SHOWS_SIZE_OR_TYPE, False),
                FileUse(K4, 0, UseKind.UNKNOWN, False),
            ),
        ),
    )


def test_a_call_that_did_not_run_lists_its_writes_and_reaches_no_later_call(knowledge):
    not_run = ToolCallResult(
        tool_output_text="", execution_status=ExecutionStatus.NOT_RUN
    )

    writer, reader = _expand(
        knowledge,
        _call(1, "curl u > log; curl -o a.tgz u", not_run),
        _call(2, "cat log"),
    )

    assert writer.written_files == (
        WrittenFile("log", (WrittenFileWriter(0, Channel.STDOUT),), ()),
        WrittenFile("a.tgz", (WrittenFileWriter(1, Channel.OWN_OUTPUT_FILE),), ()),
    )
    assert writer.output_places == ()
    assert writer.command_text_status == CommandTextStatus(
        ExecutionStatus.NOT_RUN, None, K1
    )
    assert reader.file_uses_without_known_writer == (
        FileUseWithoutKnownWriter(0, "log", UseKind.SHOWS_CONTENT),
    )
