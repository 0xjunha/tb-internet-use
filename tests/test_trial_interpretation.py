"""Tests for trial_interpretation.py, with the four calls of docs/pipeline-example.md."""

from tb_internet_use.interpret.observation.model import (
    Observation,
    ObservationKind,
    OutputLine,
)
from tb_internet_use.network.model import Host, HostKind, PrintingProgram
from tb_internet_use.parse.toolcall.model import (
    Action,
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    PollAction,
    RawToolCall,
    ReadFileAction,
    RunCommandAction,
    ToolCall,
    ToolCallKey,
    ToolCallOutput,
    WriteFileAction,
)
from tb_internet_use.trial_interpretation import interpret_trial_before_linking

FINISHED = ExecutionStatus.FINISHED


def _call(step_id: int, action: Action, output: ToolCallOutput) -> ToolCall:
    key = ToolCallKey("trial", "main", step_id, 0)
    return ToolCall(
        RawToolCall(key, HarnessTool("h", "t"), "", {}, None), action, output
    )


def _observation(
    call: ToolCall,
    line_index: int,
    kind: ObservationKind,
    *,
    printing_programs: frozenset[PrintingProgram] = frozenset(),
    is_printed_by_other_programs_too: bool = True,
    host: Host | None = None,
    package_names: frozenset[str] = frozenset(),
) -> Observation:
    return Observation(
        call=call.raw.key,
        place=OutputLine(line_index, None),
        kind=kind,
        printing_programs=printing_programs,
        is_printed_by_other_programs_too=is_printed_by_other_programs_too,
        host=host,
        package_names=package_names,
        missing_program=None,
        status_code=None,
    )


def test_example_of_the_pipeline_doc():
    task = ExecutionHandle(ExecutionHandleKind.COMMAND, "task-1")
    c1 = _call(
        1,
        WriteFileAction("fetch.sh", "curl -sS -O https://data.example.org/a.tgz"),
        ToolCallOutput(execution_status=FINISHED),
    )
    c2 = _call(
        2,
        RunCommandAction("bash fetch.sh > fetch.log 2>&1 || pip install requests"),
        ToolCallOutput(execution_status=ExecutionStatus.RUNNING, handles=(task,)),
    )
    c3 = _call(
        3,
        PollAction(handles=(ExecutionHandle(ExecutionHandleKind.UNKNOWN, "task-1"),)),
        ToolCallOutput(
            execution_status=FINISHED,
            tool_output_text="Downloading requests-2.32.3\nSuccessfully installed requests-2.32.3",
        ),
    )
    c4 = _call(
        4,
        ReadFileAction("fetch.log"),
        ToolCallOutput(
            execution_status=FINISHED,
            tool_output_text="curl: (6) Could not resolve host: data.example.org",
        ),
    )
    result = interpret_trial_before_linking([c1, c2, c3, c4])
    assert [run.call for run in result.call_runs] == [c1, c2, c3, c4]
    assert [(r.call, r.program_name) for r in result.candidate_requests] == [
        (c2.raw.key, "pip"),
        (c2.raw.key, "curl"),
    ]
    # The doc reads data.example.org as PUBLIC, though its real kind is RESERVED.
    assert result.observations == (
        _observation(
            c3,
            0,
            ObservationKind.DOWNLOAD_STARTED,
            printing_programs=frozenset(
                {
                    PrintingProgram.PIP,
                    PrintingProgram.UV,
                    PrintingProgram.PLAYWRIGHT,
                    PrintingProgram.GIT,
                    PrintingProgram.CODE,
                }
            ),
            package_names=frozenset({"requests"}),
        ),
        _observation(
            c3,
            1,
            ObservationKind.INSTALLED,
            printing_programs=frozenset({PrintingProgram.PIP}),
            is_printed_by_other_programs_too=False,
            package_names=frozenset({"requests"}),
        ),
        _observation(
            c4,
            0,
            ObservationKind.NAME_NOT_RESOLVED,
            host=Host("data.example.org", HostKind.RESERVED),
        ),
    )
