"""Tests for callrun/expand.py, through which ran_texts.py and file_reads.py are tested too."""

from tb_internet_use.callrun.expand import expand_calls
from tb_internet_use.callrun.model import (
    ArgumentText,
    CallRun,
    CodeLanguage,
    CommandTextStatus,
    FileReader,
    FileText,
    OutputRoute,
    PollInputText,
    RanCodeText,
    RanCommand,
    RanShellText,
    RedirectedOutputReads,
    ScriptStepText,
    StdinText,
)
from tb_internet_use.shell.model import FileDestination, ShellCommand
from tb_internet_use.toolcall.model import (
    Action,
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    PollAction,
    RawToolCall,
    ReadFileAction,
    RunCommandAction,
    RunToolScriptAction,
    ToolCall,
    ToolCallKey,
    ToolCallOutput,
    WriteFileAction,
)

FINISHED = ExecutionStatus.FINISHED
NOT_RUN_OUTPUT = ToolCallOutput(execution_status=ExecutionStatus.NOT_RUN)


def _call(
    step_id: int, action: Action, output: ToolCallOutput | None = None
) -> ToolCall:
    key = ToolCallKey("trial", "main", step_id, 0)
    raw = RawToolCall(key, HarnessTool("h", "t"), "", {}, None)
    return ToolCall(raw, action, output or ToolCallOutput(execution_status=FINISHED))


def _run_of_last_call(*actions: Action) -> CallRun:
    calls = [_call(step_id, action) for step_id, action in enumerate(actions, 1)]
    return expand_calls(calls)[-1]


def _words_of_texts(call_run: CallRun) -> list[list[tuple[str, ...]] | None]:
    """The words of each shell text's commands, None for a text the trial does not hold."""
    return [
        None if text.commands is None else [c.command.words for c in text.commands]
        for text in call_run.shell_texts
    ]


def test_example_of_the_pipeline_doc():
    task = ExecutionHandle(ExecutionHandleKind.COMMAND, "task-1")
    c1 = _call(
        1, WriteFileAction("fetch.sh", "curl -sS -O https://data.example.org/a.tgz")
    )
    c2 = _call(
        2,
        RunCommandAction("bash fetch.sh > fetch.log 2>&1 || pip install requests"),
        ToolCallOutput(execution_status=ExecutionStatus.RUNNING, handles=(task,)),
    )
    c3 = _call(
        3, PollAction(handles=(ExecutionHandle(ExecutionHandleKind.UNKNOWN, "task-1"),))
    )
    c4 = _call(4, ReadFileAction("fetch.log"))
    c2_run = expand_calls([c1, c2, c3, c4])[1]
    log = FileDestination("fetch.log", appends=False)
    curl = RanCommand(
        command=ShellCommand(
            id=2,
            words=("curl", "-sS", "-O", "https://data.example.org/a.tgz"),
            stdout=log,
            stderr=log,
        ),
        variable_values=(),
        stdout_routes=(OutputRoute((), log),),
        stderr_routes=(OutputRoute((), log),),
    )
    assert c2_run.shell_texts[1] == RanShellText(
        FileText(0, "fetch.sh", c1.raw.key), (curl,)
    )
    assert _words_of_texts(c2_run)[0] == [
        ("bash", "fetch.sh"),
        ("pip", "install", "requests"),
    ]
    assert c2_run.command_text_status == CommandTextStatus(FINISHED, None, c3.raw.key)
    assert c2_run.polls == (c3.raw.key,)
    assert c2_run.redirected_output_reads == (
        RedirectedOutputReads("fetch.log", (FileReader(c4.raw.key, None),)),
    )


def test_texts_of_a_tool_script_in_step_order():
    script = RunToolScriptAction(
        steps=(
            WriteFileAction("x.sh", "curl u"),
            RunCommandAction("bash x.sh"),
            RunCommandAction(None),
        )
    )
    call_run = _run_of_last_call(script)
    assert [text.source for text in call_run.shell_texts] == [
        ScriptStepText(1),
        FileText(0, "x.sh", ToolCallKey("trial", "main", 1, 0)),
        ScriptStepText(2),
    ]
    assert _words_of_texts(call_run) == [[("bash", "x.sh")], [("curl", "u")], None]


def test_files_with_unknown_content():
    unwritten = _run_of_last_call(RunCommandAction("bash run.sh"))
    assert unwritten.shell_texts[1] == RanShellText(FileText(0, "run.sh", None), None)
    overwritten = _run_of_last_call(
        WriteFileAction("run.sh", "curl u"),
        RunCommandAction("echo x > run.sh; ./run.sh"),
    )
    assert overwritten.shell_texts[1].commands is None
    assert isinstance(source := overwritten.shell_texts[1].source, FileText)
    assert source.written_by == ToolCallKey("trial", "main", 2, 0)


def test_a_file_that_runs_itself_is_read_once():
    call_run = _run_of_last_call(
        WriteFileAction("loop.sh", "bash loop.sh"), RunCommandAction("bash loop.sh")
    )
    assert _words_of_texts(call_run) == [[("bash", "loop.sh")], [("bash", "loop.sh")]]


def test_a_call_the_tool_did_not_run_writes_nothing():
    rejected = _call(1, WriteFileAction("x.sh", "curl u"), NOT_RUN_OUTPUT)
    call_runs = expand_calls([rejected, _call(2, RunCommandAction("bash x.sh"))])
    assert call_runs[1].shell_texts[1].commands is None


def test_heredoc_run_by_a_shell():
    call_run = _run_of_last_call(RunCommandAction("bash <<EOF\ncurl u\nEOF"))
    assert call_run.shell_texts[1].source == StdinText(0)
    assert _words_of_texts(call_run)[1] == [("curl", "u")]


def test_code_texts():
    write = WriteFileAction("/app/get.py", "import requests")
    text = (
        "python get.py -c cfg; python3 -c 'import x'; python - <<EOF\nprint(1)\nEOF\n"
        "./get.py; node -e 'fetch(u)'; bun install x; python -m pip install x; "
        "uv run python get.py; npx tsx get.ts"
    )
    call_run = _run_of_last_call(write, RunCommandAction(text))
    first_call = ToolCallKey("trial", "main", 1, 0)
    assert call_run.code_texts == (
        RanCodeText(
            FileText(0, "get.py", first_call), CodeLanguage.PYTHON, "import requests"
        ),
        RanCodeText(ArgumentText(1), CodeLanguage.PYTHON, "import x"),
        RanCodeText(StdinText(2), CodeLanguage.PYTHON, "print(1)\n"),
        RanCodeText(
            FileText(3, "./get.py", first_call), CodeLanguage.PYTHON, "import requests"
        ),
        RanCodeText(ArgumentText(4), CodeLanguage.JAVASCRIPT, "fetch(u)"),
        RanCodeText(
            FileText(7, "get.py", first_call), CodeLanguage.PYTHON, "import requests"
        ),
        RanCodeText(FileText(8, "get.ts", None), CodeLanguage.JAVASCRIPT, None),
    )


def test_a_syntax_check_runs_no_file():
    call_run = _run_of_last_call(
        WriteFileAction("f.sh", "curl u"), RunCommandAction("bash -n f.sh")
    )
    assert _words_of_texts(call_run) == [[("bash", "-n", "f.sh")]]


def test_content_after_commands_that_change_a_file():
    written = WriteFileAction("a.sh", "curl a.org")
    copied = _run_of_last_call(written, RunCommandAction("cp a.sh f.sh; bash f.sh"))
    assert _words_of_texts(copied)[1] == [("curl", "a.org")]
    edited = _run_of_last_call(
        written, RunCommandAction("sed -Ei 's/a/b/' a.sh; bash a.sh")
    )
    assert _words_of_texts(edited)[1] is None
    appended = _run_of_last_call(
        WriteFileAction("a.sh", "curl a.org\n"),
        RunCommandAction("cat >> a.sh 2>&1 <<EOF\ncurl b.org\nEOF\nbash a.sh"),
    )
    assert _words_of_texts(appended)[1] == [("curl", "a.org"), ("curl", "b.org")]
    heredoc = _run_of_last_call(
        RunCommandAction("cat > f.sh 2> err.sh <<EOF\ncurl u\nEOF\nbash err.sh")
    )
    assert _words_of_texts(heredoc)[1] is None
    # cat prints the file it names instead of its heredoc, and `-` names stdin.
    named_file = _run_of_last_call(
        RunCommandAction("cat other > f.sh <<EOF\ncurl u\nEOF\nbash f.sh")
    )
    assert _words_of_texts(named_file)[1] is None
    named_stdin = _run_of_last_call(
        RunCommandAction("cat - > f.sh <<EOF\ncurl u\nEOF\nbash f.sh")
    )
    assert _words_of_texts(named_stdin)[1] == [("curl", "u")]


def test_typed_input_is_a_shell_text_of_the_poll():
    session = ExecutionHandle(ExecutionHandleKind.COMMAND, "7")
    start = _call(
        1,
        RunCommandAction("bash"),
        ToolCallOutput(execution_status=ExecutionStatus.RUNNING, handles=(session,)),
    )
    typing = _call(2, PollAction(handles=(session,), input="curl u\n"))
    call_run = expand_calls([start, typing])[1]
    assert call_run.shell_texts[0].source == PollInputText(None, start.raw.key)


def test_readers_of_redirected_output():
    def readers_of_log(*texts: str) -> tuple[FileReader, ...]:
        call_runs = expand_calls(
            [_call(i, RunCommandAction(t)) for i, t in enumerate(texts, 1)]
        )
        reads = call_runs[0].redirected_output_reads
        return reads[0].readers if reads else ()

    second = ToolCallKey("trial", "main", 2, 0)
    third = ToolCallKey("trial", "main", 3, 0)
    assert readers_of_log("curl u > log; tail log") == (
        FileReader(ToolCallKey("trial", "main", 1, 0), 1),
    )
    assert readers_of_log("tail log; curl u > log") == ()
    assert readers_of_log("curl u > log", "cat log") == (FileReader(second, 0),)
    # wc does not show the content.
    assert readers_of_log("curl u > log", "wc -l log") == ()
    assert readers_of_log("curl u > log", "pip install x > log", "cat log") == ()
    assert readers_of_log("curl u > log", "pip install x >> log", "cat log") == (
        FileReader(third, 0),
    )
    assert readers_of_log("bash -c 'curl u > /app/log'", "LOG=log; tail -n 5 $LOG") == (
        FileReader(second, 0),
    )
    assert readers_of_log("LOG=/tmp/x.log; curl u > $LOG 2>&1; tail $LOG") == (
        FileReader(ToolCallKey("trial", "main", 1, 0), 1),
    )
    assert readers_of_log("curl u 2> log", "cat log") == (FileReader(second, 0),)
    assert readers_of_log("curl u > log", "grep x < log") == (FileReader(second, 0),)
    assert readers_of_log("curl u > /tmp/x.log", "L=/tmp/x.log; tail < $L") == (
        FileReader(second, 0),
    )
    # python is no reading program, so its stdin file is not shown as read.
    assert readers_of_log("curl u > log", "python parse.py < log") == ()
    # A command that names a file, a pipe reader and xargs read no stdin file.
    assert readers_of_log("curl u > log", "cat other < log") == ()
    assert (
        readers_of_log("curl u > log", "while read l; do grep $l x; done < log") == ()
    )
    assert readers_of_log("curl u > log", "{ echo a | grep a; } < log") == ()
    assert readers_of_log("curl u > log", "xargs cat < log") == ()
    assert readers_of_log("curl u > log", "cat other - < log") == (
        FileReader(second, 0),
    )
    # The pattern and the line count name no file.
    assert readers_of_log("curl u > log", "grep log other; tail -n log x") == ()


def test_readers_in_run_order_within_a_call():
    def readers_of_log(action: Action) -> tuple[FileReader, ...]:
        writes = WriteFileAction("x.sh", "tail log")
        (_, call_run) = expand_calls([_call(1, writes), _call(2, action)])
        reads = call_run.redirected_output_reads
        return reads[0].readers if reads else ()

    script = RunToolScriptAction(
        steps=(
            RunCommandAction("cat log"),
            RunCommandAction("curl u > log"),
            RunCommandAction("cat log"),
        )
    )
    assert readers_of_log(script) == (
        FileReader(ToolCallKey("trial", "main", 2, 0), 2),
    )
    # A command of a file runs at the place of the command that runs the file.
    assert readers_of_log(RunCommandAction("curl u > log; bash x.sh")) == (
        FileReader(ToolCallKey("trial", "main", 2, 0), 2),
    )
    assert readers_of_log(RunCommandAction("bash x.sh; curl u > log")) == ()


def test_a_write_tool_replaces_the_output_file():
    call_runs = expand_calls(
        [
            _call(1, RunCommandAction("curl u > log")),
            _call(2, WriteFileAction("log", "")),
            _call(3, ReadFileAction("log")),
        ]
    )
    assert call_runs[0].redirected_output_reads == ()


def test_a_call_the_tool_did_not_run_reads_and_writes_no_file():
    curl = _call(1, RunCommandAction("curl u > log"))
    rejected_cat = _call(2, RunCommandAction("cat log"), NOT_RUN_OUTPUT)
    assert expand_calls([curl, rejected_cat])[0].redirected_output_reads == ()
    rejected_write = _call(2, WriteFileAction("log", ""), NOT_RUN_OUTPUT)
    read = _call(3, ReadFileAction("log"))
    assert expand_calls([curl, rejected_write, read])[0].redirected_output_reads == (
        RedirectedOutputReads("log", (FileReader(read.raw.key, None),)),
    )
    rejected_curl = _call(1, RunCommandAction("curl u > log"), NOT_RUN_OUTPUT)
    cat = _call(2, RunCommandAction("cat log"))
    assert expand_calls([rejected_curl, cat])[0].redirected_output_reads == ()


def test_readers_of_the_harness_output_file():
    output = ToolCallOutput(
        execution_status=ExecutionStatus.RUNNING, output_path="/tmp/tasks/b1.output"
    )
    start = _call(1, RunCommandAction("pip install x"), output)
    other = _call(2, RunCommandAction("cat /tmp/tasks/b2.output"))
    read = _call(3, RunCommandAction("cat /tmp/tasks/b1.output"))
    assert expand_calls([start, other, read])[0].harness_output_file_readers == (
        FileReader(read.raw.key, 0),
    )
