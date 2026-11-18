"""Tests for _decide_output_place_sources.py, with made-up expanded tool calls of one trial."""

import pytest

from tb_internet_use.expanded_tool_call.model import (
    CallCommandText,
    ExpandedToolCall,
    FileText,
    FileUse,
    FileUseKind,
    FileUseWithoutKnownWriter,
    FileWriteChannel,
    OutputPlace,
    OutputRoute,
    OutputRouteEnd,
    OutputVisibility,
    RanCommand,
    RanShellText,
    ScriptStepText,
    ShellTextSource,
    WrittenFile,
    WrittenFileWriter,
)
from tb_internet_use.network_request_result._decide_output_place_sources import (
    decide_output_place_sources,
)
from tb_internet_use.network_request_result.model import (
    OutputPlaceSourceCommands,
    OutputPlaceSources,
)
from tb_internet_use.tool_call.model import (
    DiscardDestination,
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    FileDestination,
    HarnessTool,
    HarnessToolCall,
    OtherAction,
    PollAction,
    ReadFileAction,
    ResultDestination,
    RunCommandAction,
    RunToolScriptAction,
    ShellCommand,
    ToolCall,
    ToolCallAction,
    ToolCallKey,
    ToolCallResult,
    WebFetchAction,
    WebFindAction,
    WebSearchAction,
)

COMMAND = RunCommandAction("x")
FINISHED = ToolCallResult(
    tool_output_text="out", execution_status=ExecutionStatus.FINISHED
)
STDOUT = FileWriteChannel.STDOUT
SHOWS_CONTENT = FileUseKind.SHOWS_CONTENT
RESULT = ResultDestination()
CALL_COMMAND_TEXT = CallCommandText()


def key_of(step_id: int, trajectory_id: str = "main") -> ToolCallKey:
    return ToolCallKey("trial", trajectory_id, step_id, 0)


def ran_command(
    command_id: int,
    *,
    stdout: OutputRouteEnd = RESULT,
    pipe_reader_command_ids: tuple[int, ...] = (),
) -> RanCommand:
    return RanCommand(
        shell_command=ShellCommand(command_id, ("x",)),
        program_invocations=(),
        variable_values=(),
        stdout_routes=(
            OutputRoute(
                pipe_reader_command_ids,
                ResultDestination() if pipe_reader_command_ids else stdout,
                OutputVisibility.PARTIAL
                if pipe_reader_command_ids
                else OutputVisibility.WHOLE,
            ),
        ),
        stderr_routes=(OutputRoute((), ResultDestination(), OutputVisibility.WHOLE),),
    )


def expanded_tool_call(
    tool_call_key: ToolCallKey,
    *,
    action: ToolCallAction = COMMAND,
    result: ToolCallResult | None = FINISHED,
    ran_commands: tuple[RanCommand, ...] = (),
    ran_text_source: ShellTextSource = CALL_COMMAND_TEXT,
    output_places: tuple[OutputPlace, ...] = (),
    written_files: tuple[WrittenFile, ...] = (),
    file_uses_without_known_writer: tuple[FileUseWithoutKnownWriter, ...] = (),
) -> ExpandedToolCall:
    return ExpandedToolCall(
        tool_call=ToolCall(
            HarnessToolCall(tool_call_key, HarnessTool("h", "t"), "", {}, None),
            action,
            result,
        ),
        ran_texts=(RanShellText(ran_text_source, ran_commands),)
        if ran_commands
        else (),
        command_text_status=None,
        output_places=output_places,
        written_files=written_files,
        file_uses_without_known_writer=file_uses_without_known_writer,
    )


def place(
    showing_tool_call_key: ToolCallKey,
    *source_commands: tuple[ToolCallKey, tuple[int, ...]],
    may_show_file_content: bool = False,
    may_show_page_text: bool = False,
    is_web_tool_result: bool = False,
) -> OutputPlaceSources:
    return OutputPlaceSources(
        showing_tool_call_key=showing_tool_call_key,
        source_commands=tuple(
            OutputPlaceSourceCommands(tool_call_key, command_ids)
            for tool_call_key, command_ids in source_commands
        ),
        may_show_file_content=may_show_file_content,
        may_show_page_text=may_show_page_text,
        is_web_tool_result=is_web_tool_result,
    )


def written_file(
    path: str,
    writers: tuple[WrittenFileWriter, ...],
    *file_uses: FileUse,
) -> WrittenFile:
    return WrittenFile(path, writers, file_uses)


def shows_content_use(
    using_tool_call_key: ToolCallKey, command_id: int | None
) -> FileUse:
    return FileUse(using_tool_call_key, command_id, SHOWS_CONTENT, False)


def call_reading_file(
    tool_call_key: ToolCallKey, *, stdout: OutputRouteEnd = RESULT
) -> ExpandedToolCall:
    """A call of `cat <file>` whose command 0 reads a file, with the place of its own result when its stdout ends there."""
    return expanded_tool_call(
        tool_call_key,
        ran_commands=(ran_command(0, stdout=stdout),),
        output_places=(OutputPlace(tool_call_key, (0,)),)
        if isinstance(stdout, ResultDestination)
        else (),
    )


K1, K2, K3 = key_of(1), key_of(2), key_of(3)


def test_command_whose_output_shows_in_its_own_result_is_the_source_of_that_result():
    # `curl u` in call 1.
    calls = [
        expanded_tool_call(
            K1, ran_commands=(ran_command(0),), output_places=(OutputPlace(K1, (0,)),)
        )
    ]

    assert decide_output_place_sources(calls) == (place(K1, (K1, (0,))),)


def test_two_commands_of_one_call_are_sources_of_the_places_each_one_reaches():
    # Call 1 `curl a > log; curl b`, call 2 `cat log`.
    calls = [
        expanded_tool_call(
            K1,
            ran_commands=(
                ran_command(0, stdout=FileDestination("log", appends=False)),
                ran_command(1),
            ),
            output_places=(OutputPlace(K1, (1,)),),
            written_files=(
                written_file(
                    "log", (WrittenFileWriter(0, STDOUT),), shows_content_use(K2, 0)
                ),
            ),
        ),
        call_reading_file(K2),
    ]

    assert decide_output_place_sources(calls) == (
        place(K1, (K1, (1,))),
        place(K2, (K1, (0,)), (K2, (0,))),
    )


def test_every_command_of_a_pipe_that_prints_into_a_file_is_a_source_of_the_later_read():
    # Call 1 `curl u | tail -1 > log`, where curl's output reaches log through tail, then call 2 `cat log`.
    calls = [
        expanded_tool_call(
            K1,
            ran_commands=(
                ran_command(0, pipe_reader_command_ids=(1,)),
                ran_command(1, stdout=FileDestination("log", appends=False)),
            ),
            written_files=(
                written_file(
                    "log",
                    (WrittenFileWriter(0, STDOUT), WrittenFileWriter(1, STDOUT)),
                    shows_content_use(K2, 0),
                ),
            ),
        ),
        call_reading_file(K2),
    ]

    assert decide_output_place_sources(calls) == (place(K2, (K1, (0, 1)), (K2, (0,))),)


@pytest.mark.parametrize(
    ("case", "writer_channel", "reading_call", "expected_sources"),
    [
        # `make > build.log`, then `cat build.log`.
        ("command read", STDOUT, call_reading_file(K2), ((K1, (0,)), (K2, (0,)))),
        # `make 2> err.log`, then `cat err.log`.
        (
            "stderr file",
            FileWriteChannel.STDERR,
            call_reading_file(K2),
            ((K1, (0,)), (K2, (0,))),
        ),
        # `make > build.log`, then a read tool, whose use has no command.
        (
            "read tool",
            STDOUT,
            expanded_tool_call(K2, action=ReadFileAction("build.log")),
            ((K1, (0,)),),
        ),
    ],
)
def test_file_that_commands_printed_into_gives_its_writers_to_the_later_call_that_shows_it(
    case: str,
    writer_channel: FileWriteChannel,
    reading_call: ExpandedToolCall,
    expected_sources: tuple[tuple[ToolCallKey, tuple[int, ...]], ...],
):
    command_id = (
        None if isinstance(reading_call.tool_call.action, ReadFileAction) else 0
    )
    calls = [
        expanded_tool_call(
            K1,
            ran_commands=(ran_command(0, stdout=FileDestination("f", appends=False)),),
            written_files=(
                written_file(
                    "f",
                    (WrittenFileWriter(0, writer_channel),),
                    shows_content_use(K2, command_id),
                ),
            ),
        ),
        reading_call,
    ]

    assert decide_output_place_sources(calls) == (place(K2, *expected_sources),), case


@pytest.mark.parametrize(
    ("case", "writer", "reading_call", "file_use_kind"),
    [
        # `curl -o page.html u`, then `cat page.html`. curl printed nothing into the file.
        (
            "own output file",
            WrittenFileWriter(0, FileWriteChannel.OWN_OUTPUT_FILE),
            call_reading_file(K2),
            SHOWS_CONTENT,
        ),
        # `make > build.log`, then `cat build.log > /dev/null`, whose result shows nothing of it.
        (
            "read thrown away",
            WrittenFileWriter(0, STDOUT),
            call_reading_file(K2, stdout=DiscardDestination()),
            SHOWS_CONTENT,
        ),
        # `make > build.log`, then `wc -c build.log`.
        (
            "size only",
            WrittenFileWriter(0, STDOUT),
            call_reading_file(K2),
            FileUseKind.SHOWS_SIZE_OR_TYPE,
        ),
        # `make > build.log`, then `cat build.log` in a call without a result in the trajectory.
        (
            "reading call without result",
            WrittenFileWriter(0, STDOUT),
            expanded_tool_call(K2, result=None, ran_commands=(ran_command(0),)),
            SHOWS_CONTENT,
        ),
    ],
)
def test_written_file_gives_no_source_unless_commands_printed_into_it_and_the_later_result_shows_it(
    case: str,
    writer: WrittenFileWriter,
    reading_call: ExpandedToolCall,
    file_use_kind: FileUseKind,
):
    calls = [
        expanded_tool_call(
            K1,
            ran_commands=(ran_command(0, stdout=FileDestination("f", appends=False)),),
            written_files=(
                written_file("f", (writer,), FileUse(K2, 0, file_use_kind, False)),
            ),
        ),
        reading_call,
    ]

    sources_of_k1 = [
        output_place_source_commands
        for output_place_sources in decide_output_place_sources(calls)
        for output_place_source_commands in output_place_sources.source_commands
        if output_place_source_commands.tool_call_key == K1
    ]
    assert sources_of_k1 == [], case


def test_polls_show_the_commands_of_the_starter_and_of_typed_text_grouped_by_call_in_call_order():
    # Call 1 starts `pip install x` in the background, poll call 2 types `curl u` into it, poll call 3 shows both.
    poll = PollAction((ExecutionHandle(ExecutionHandleKind.COMMAND, "s"),))
    calls = [
        expanded_tool_call(
            K1,
            ran_commands=(ran_command(0),),
            output_places=(OutputPlace(K3, (0,)),),
        ),
        expanded_tool_call(
            K2,
            action=poll,
            ran_commands=(ran_command(2), ran_command(1)),
            output_places=(OutputPlace(K3, (2, 1)),),
        ),
        expanded_tool_call(K3, action=poll),
    ]

    assert decide_output_place_sources(calls) == (place(K3, (K1, (0,)), (K2, (1, 2))),)


def test_commands_of_a_ran_script_share_the_place_of_the_command_that_runs_it():
    # Call 1 `bash fetch.sh`, command 0, whose commands 1 and 2 come from fetch.sh.
    calls = [
        ExpandedToolCall(
            tool_call=ToolCall(
                HarnessToolCall(K1, HarnessTool("h", "t"), "", {}, None),
                COMMAND,
                FINISHED,
            ),
            ran_texts=(
                RanShellText(CallCommandText(), (ran_command(0),)),
                RanShellText(
                    FileText(0, "fetch.sh", K1), (ran_command(1), ran_command(2))
                ),
            ),
            command_text_status=None,
            output_places=(OutputPlace(K1, (0, 1, 2)),),
            written_files=(),
            file_uses_without_known_writer=(),
        )
    ]

    assert decide_output_place_sources(calls) == (place(K1, (K1, (0, 1, 2))),)


def test_places_that_no_request_reaches_are_returned_and_results_of_no_run_are_not():
    # Call 1 `ls`, call 2 a Codex `exec` with only a read step, call 3 a web search, all with results.
    # Call 4 is a plan tool, call 5 a web fetch that did not run, call 6 a web search without result text.
    k4, k5, k6 = key_of(4), key_of(5), key_of(6)
    calls = [
        expanded_tool_call(
            K1, ran_commands=(ran_command(0),), output_places=(OutputPlace(K1, (0,)),)
        ),
        expanded_tool_call(
            K2, action=RunToolScriptAction("x", (ReadFileAction("notes.md"),))
        ),
        expanded_tool_call(K3, action=WebSearchAction(("q",))),
        expanded_tool_call(k4, action=OtherAction()),
        expanded_tool_call(
            k5,
            action=WebFetchAction(("https://a.org",)),
            result=ToolCallResult(
                tool_output_text="refused", execution_status=ExecutionStatus.NOT_RUN
            ),
        ),
        expanded_tool_call(
            k6,
            action=WebSearchAction(("q",)),
            result=ToolCallResult(execution_status=ExecutionStatus.FINISHED),
        ),
    ]

    assert decide_output_place_sources(calls) == (
        place(K1, (K1, (0,))),
        place(K2),
        place(K3, is_web_tool_result=True),
    )


def test_calls_of_another_trajectory_with_the_same_step_and_command_ids_stay_apart():
    # The main trajectory and its subagent each run `curl u` as command 0 at step 1.
    subagent_key = key_of(1, "main/sub0")
    calls = [
        expanded_tool_call(
            K1, ran_commands=(ran_command(0),), output_places=(OutputPlace(K1, (0,)),)
        ),
        expanded_tool_call(
            subagent_key,
            ran_commands=(ran_command(0),),
            output_places=(OutputPlace(subagent_key, (0,)),),
        ),
    ]

    assert decide_output_place_sources(calls) == (
        place(K1, (K1, (0,))),
        place(subagent_key, (subagent_key, (0,))),
    )


@pytest.mark.parametrize(
    ("case", "file_use_without_known_writer", "stdout", "expected"),
    [
        # `cat README.md`, a file of the task image.
        (
            "unwritten file shown",
            FileUseWithoutKnownWriter(0, "README.md", SHOWS_CONTENT),
            ResultDestination(),
            True,
        ),
        # A read step of a file of the task image beside the command.
        (
            "unwritten file read by a tool",
            FileUseWithoutKnownWriter(None, "README.md", SHOWS_CONTENT),
            DiscardDestination(),
            True,
        ),
        # `cat README.md > /dev/null`.
        (
            "unwritten file thrown away",
            FileUseWithoutKnownWriter(0, "README.md", SHOWS_CONTENT),
            DiscardDestination(),
            False,
        ),
        # `wc -c README.md`.
        (
            "unwritten file size only",
            FileUseWithoutKnownWriter(0, "README.md", FileUseKind.SHOWS_SIZE_OR_TYPE),
            ResultDestination(),
            False,
        ),
    ],
)
def test_result_may_show_file_content_when_it_shows_a_file_that_no_call_wrote(
    case: str,
    file_use_without_known_writer: FileUseWithoutKnownWriter,
    stdout: OutputRouteEnd,
    expected: bool,
):
    # Command 1 prints to the result so that the call is a place whatever command 0 does.
    calls = [
        expanded_tool_call(
            K1,
            ran_commands=(ran_command(0, stdout=stdout), ran_command(1)),
            output_places=(OutputPlace(K1, (1,)),),
            file_uses_without_known_writer=(file_use_without_known_writer,),
        )
    ]

    (output_place_sources,) = decide_output_place_sources(calls)
    assert output_place_sources.may_show_file_content is expected, case


@pytest.mark.parametrize(
    ("case", "writers", "expected"),
    [
        # A write tool writes notes.md.
        (
            "write tool",
            (WrittenFileWriter(None, FileWriteChannel.TOOL_ARGUMENT),),
            True,
        ),
        # `curl -o page.html u`.
        (
            "own output file",
            (WrittenFileWriter(0, FileWriteChannel.OWN_OUTPUT_FILE),),
            True,
        ),
        # `make > build.log`, whose lines are output of make.
        ("printed only", (WrittenFileWriter(0, STDOUT),), False),
    ],
)
def test_result_may_show_file_content_when_it_shows_a_file_with_content_that_no_command_printed(
    case: str, writers: tuple[WrittenFileWriter, ...], expected: bool
):
    calls = [
        expanded_tool_call(
            K1,
            ran_commands=(ran_command(0, stdout=FileDestination("f", appends=False)),),
            written_files=(written_file("f", writers, shows_content_use(K3, 0)),),
        ),
        call_reading_file(K2),
        call_reading_file(K3),
    ]

    may_show_file_content_by_key = {
        output_place_sources.showing_tool_call_key: output_place_sources.may_show_file_content
        for output_place_sources in decide_output_place_sources(calls)
    }
    # Call 2 shows a file too, but not this one.
    assert may_show_file_content_by_key[K2] is False
    assert may_show_file_content_by_key[K3] is expected, case


@pytest.mark.parametrize(
    ("case", "steps", "expected_page_text", "expected_web_tool_result"),
    [
        (
            "web step beside a command",
            (WebFetchAction(("https://a.org",)), RunCommandAction("curl u")),
            True,
            False,
        ),
        (
            "web step beside a read step",
            (WebFetchAction(("https://a.org",)), ReadFileAction("notes.md")),
            False,
            False,
        ),
        (
            "web steps only",
            (WebSearchAction(("q",)), WebFetchAction(("https://a.org",))),
            False,
            True,
        ),
        ("command steps only", (RunCommandAction("ls"),), False, False),
        ("no steps", (), False, False),
        ("find in a page only", (WebFindAction(("https://a.org",)),), False, True),
    ],
)
def test_tool_script_with_a_web_step_mixes_page_text_into_command_output_or_is_page_text_alone(
    case: str,
    steps: tuple[ToolCallAction, ...],
    expected_page_text: bool,
    expected_web_tool_result: bool,
):
    calls = [expanded_tool_call(K1, action=RunToolScriptAction("x", steps))]

    (output_place_sources,) = decide_output_place_sources(calls)
    assert (
        output_place_sources.may_show_page_text,
        output_place_sources.is_web_tool_result,
    ) == (expected_page_text, expected_web_tool_result), case


@pytest.mark.parametrize(
    ("case", "own_result_command_ids", "expected_sources"),
    [
        # The script's code prints what `cat build.log` printed.
        ("step output shown", (0,), ((K1, (0,)), (K2, (0,)))),
        # The step's stdout ends in the result, but the rule on script steps says the result does not show it.
        ("step output not shown", (), ()),
    ],
)
def test_read_by_a_step_of_a_tool_script_gives_sources_only_when_the_own_result_place_names_it(
    case: str,
    own_result_command_ids: tuple[int, ...],
    expected_sources: tuple[tuple[ToolCallKey, tuple[int, ...]], ...],
):
    # Call 1 `make > build.log`, call 2 a Codex `exec` whose step 0 runs `cat build.log`.
    calls = [
        expanded_tool_call(
            K1,
            ran_commands=(ran_command(0, stdout=FileDestination("f", appends=False)),),
            written_files=(
                written_file(
                    "f", (WrittenFileWriter(0, STDOUT),), shows_content_use(K2, 0)
                ),
            ),
        ),
        expanded_tool_call(
            K2,
            action=RunToolScriptAction("x", (RunCommandAction("cat build.log"),)),
            ran_commands=(ran_command(0),),
            ran_text_source=ScriptStepText(0),
            output_places=(OutputPlace(K2, own_result_command_ids),)
            if own_result_command_ids
            else (),
        ),
    ]

    assert decide_output_place_sources(calls) == (place(K2, *expected_sources),), case


@pytest.mark.parametrize(
    ("case", "file_use_kind", "stdout", "expected"),
    [
        # `wc -c page.html`.
        ("size only", FileUseKind.SHOWS_SIZE_OR_TYPE, ResultDestination(), False),
        # `cat page.html > /dev/null`.
        ("read thrown away", SHOWS_CONTENT, DiscardDestination(), False),
    ],
)
def test_saved_page_may_show_in_the_result_only_when_the_use_shows_its_content_there(
    case: str, file_use_kind: FileUseKind, stdout: OutputRouteEnd, expected: bool
):
    # Call 1 `curl -o page.html u`. Call 2 uses page.html with command 0 and prints with command 1, so the call is a place whatever command 0 does.
    calls = [
        expanded_tool_call(
            K1,
            ran_commands=(ran_command(0, stdout=DiscardDestination()),),
            written_files=(
                written_file(
                    "page.html",
                    (WrittenFileWriter(0, FileWriteChannel.OWN_OUTPUT_FILE),),
                    FileUse(K2, 0, file_use_kind, False),
                ),
            ),
        ),
        expanded_tool_call(
            K2,
            ran_commands=(ran_command(0, stdout=stdout), ran_command(1)),
            output_places=(OutputPlace(K2, (1,)),),
        ),
    ]

    (output_place_sources,) = decide_output_place_sources(calls)
    assert output_place_sources.may_show_file_content is expected, case


def test_file_with_a_printing_writer_and_an_own_output_writer_gives_the_printer_and_may_show_content():
    # Call 1 `curl -o out.txt u; echo done >> out.txt`, call 2 `cat out.txt`.
    calls = [
        expanded_tool_call(
            K1,
            ran_commands=(
                ran_command(0, stdout=DiscardDestination()),
                ran_command(1, stdout=FileDestination("out.txt", appends=True)),
            ),
            written_files=(
                written_file(
                    "out.txt",
                    (
                        WrittenFileWriter(0, FileWriteChannel.OWN_OUTPUT_FILE),
                        WrittenFileWriter(1, STDOUT),
                    ),
                    shows_content_use(K2, 0),
                ),
            ),
        ),
        call_reading_file(K2),
    ]

    assert decide_output_place_sources(calls) == (
        place(K2, (K1, (1,)), (K2, (0,)), may_show_file_content=True),
    )


def test_use_that_fits_several_written_files_gets_the_printers_of_each():
    # Call 1 `make > /a/log; pytest > /b/log`, call 2 `cat log`, whose path fits both.
    use = FileUse(K2, 0, SHOWS_CONTENT, True)
    calls = [
        expanded_tool_call(
            K1,
            ran_commands=(
                ran_command(0, stdout=FileDestination("/a/log", appends=False)),
                ran_command(1, stdout=FileDestination("/b/log", appends=False)),
            ),
            written_files=(
                written_file("/a/log", (WrittenFileWriter(0, STDOUT),), use),
                written_file("/b/log", (WrittenFileWriter(1, STDOUT),), use),
            ),
        ),
        call_reading_file(K2),
    ]

    assert decide_output_place_sources(calls) == (place(K2, (K1, (0, 1)), (K2, (0,))),)


def test_two_calls_that_append_to_one_log_are_both_sources_of_its_later_read():
    # Call 1 `make >> build.log`, call 2 `make test >> build.log`, call 3 `cat build.log`.
    calls = [
        expanded_tool_call(
            tool_call_key,
            ran_commands=(
                ran_command(0, stdout=FileDestination("build.log", appends=True)),
            ),
            written_files=(
                written_file(
                    "build.log",
                    (WrittenFileWriter(0, STDOUT),),
                    shows_content_use(K3, 0),
                ),
            ),
        )
        for tool_call_key in (K1, K2)
    ] + [call_reading_file(K3)]

    assert decide_output_place_sources(calls) == (
        place(K3, (K1, (0,)), (K2, (0,)), (K3, (0,))),
    )
