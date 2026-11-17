"""Harness-agnostic common types for tool calls in ATIF trajectories.

Each harness names its tools and writes its results in its own way, e.g. a shell call is `Bash` in Claude Code and `exec_command` in Codex. Later steps read these types, so they work the same for every harness.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import Any, final, get_args

type ToolCallAction = (
    RunCommandAction
    | RunToolScriptAction
    | WriteFileAction
    | EditFileAction
    | DeleteFileAction
    | ReadFileAction
    | SearchFilesAction
    | ListFilesAction
    | WebSearchAction
    | WebFetchAction
    | WebFindAction
    | StartSubagentAction
    | PollAction
    | OtherAction
    | UnknownAction
)


# The format that produced a ToolCallResult. str() gives the name that the table of declared result formats and the result format audit use.
type FormatMatch = MatchedFormat | UnmatchedFormat


class ExecutionStatus(StrEnum):
    """State of the requested work when the tool call returned.

    For a poll, this is the polled target's state, except NOT_RUN, which means the poll itself did nothing.

    A FINISHED result can still have handles. A Codex script can end while a command it started keeps running, and its exec or wait result names that command's session.
    """

    FINISHED = "finished"  # ended on its own, whether it succeeded or not
    RUNNING = "running"  # still going, and the result comes in a later call
    TIMED_OUT = "timed_out"  # stopped by the harness's time limit
    KILLED = "killed"  # stopped by a signal or a stop request
    NOT_RUN = "not_run"  # the tool did no work
    UNKNOWN = "unknown"  # the trajectory does not say


def handles_from_ids(
    kind: ExecutionHandleKind, ids: Any
) -> tuple[ExecutionHandle, ...]:
    """Make handles of one kind from a list of ids or one id, in order and without missing, empty or repeated ones."""
    return tuple(ExecutionHandle(kind, i) for i in strings_from_values(ids))


def join_text_parts(parts: Iterable[str]) -> str:
    """Join pieces of one output in order, starting a new line between them when needed."""
    joined = ""
    for part in parts:
        if joined and not joined.endswith("\n") and part:
            joined += "\n"
        joined += part
    return joined


def join_texts(texts: Iterable[str]) -> str | None:
    """Join separate texts with a blank line, each without its edge whitespace. None when all are empty."""
    return "\n\n".join(text.strip() for text in texts if text.strip()) or None


def indexed_action_steps_of(
    action: ToolCallAction,
) -> tuple[tuple[int | None, ToolCallAction], ...]:
    """List the steps of a tool script with their 0-based index, or the action alone with index None when it is not a script.

    One call can run a script of several tool steps, e.g. a Codex `exec` that runs a command and then fetches a page, and later steps read each step, e.g. to record which step a request came from.
    """
    if isinstance(action, RunToolScriptAction):
        return tuple(enumerate(action.steps))
    return ((None, action),)


def may_have_run(call: ToolCall) -> bool:
    """Tell whether the tool may have run a call, i.e. whether its result is anything but `NOT_RUN`.

    A call without a result may have run, since the trajectory does not say whether the tool ran it.
    """
    return (
        call.result is None or call.result.execution_status != ExecutionStatus.NOT_RUN
    )


def strings_from_values(values: Any) -> tuple[str, ...]:
    """Turn a list of values or one value into the strings of a ToolCallAction field, in order and without missing, empty or repeated ones."""
    listed = values if isinstance(values, list) else [values]
    return tuple(dict.fromkeys(str(v) for v in listed if v not in (None, "")))


@dataclass(frozen=True, slots=True)
class RunCommandAction:
    """Run a string in a shell in one go. It can chain several commands."""

    command_str: str | None = None  # None when the trajectory has none


@dataclass(frozen=True, slots=True)
class RunToolScriptAction:
    """Run code that calls harness tools, e.g. Codex `exec`. The trajectory has one result for all of it."""

    # The code of the script, None when the trajectory has none.
    code: str | None = None
    # The ToolCallActions of the tool calls found in the code, in order. One call can have several steps, e.g. a patch that changes several files.
    # A step field is empty when the script builds the argument at run time, e.g. `tools.exec_command({cmd: "ls /app"})` gives `RunCommandAction("ls /app")`, but `tools.exec_command({cmd: "ls " + dir})` gives `RunCommandAction(None)`.
    steps: tuple[ToolCallAction, ...] = ()


@dataclass(frozen=True, slots=True)
class WriteFileAction:
    """Write a whole file with a dedicated tool."""

    path: str | None = None  # None when the trajectory has none
    content: str | None = None


@dataclass(frozen=True, slots=True)
class EditFileAction:
    """Replace text in a file with a dedicated tool."""

    path: str | None = None  # None when the trajectory has none
    old: str | None = None
    new: str | None = None


@dataclass(frozen=True, slots=True)
class DeleteFileAction:
    """Delete a file with a dedicated tool."""

    path: str | None = None  # None when the trajectory has none


@dataclass(frozen=True, slots=True)
class ReadFileAction:
    """Read a file with a dedicated tool."""

    path: str | None = None  # None when the trajectory has none
    offset: int | None = None  # 1-based line, and a negative one counts from the end
    limit: int | None = None  # number of lines


@dataclass(frozen=True, slots=True)
class SearchFilesAction:
    """Search the content of files with a dedicated tool."""

    # The files or folders searched, empty when the trajectory has none.
    paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ListFilesAction:
    """Find files by name or list a folder with a dedicated tool."""

    path: str | None = None  # the folder, None when the trajectory has none


@dataclass(frozen=True, slots=True)
class WebSearchAction:
    """Search with a dedicated web tool."""

    queries: tuple[str, ...] = ()  # empty when the trajectory has none


@dataclass(frozen=True, slots=True)
class WebFetchAction:
    """Open pages with a dedicated web tool."""

    urls: tuple[str, ...] = ()  # empty when the trajectory has none


@dataclass(frozen=True, slots=True)
class WebFindAction:
    """Find text in a page with a dedicated web tool."""

    urls: tuple[str, ...] = ()  # empty when the trajectory has none


@dataclass(frozen=True, slots=True)
class StartSubagentAction:
    """Start a subagent, whose own calls may or may not be in the trajectory."""


@dataclass(frozen=True, slots=True)
class PollAction:
    """Read from, write to or stop a command, script or subagent started earlier."""

    handles: tuple[ExecutionHandle, ...] = ()
    input: str | None = None  # text sent to stdin, None if the poll only reads
    terminate: bool = False


@dataclass(frozen=True, slots=True)
class OtherAction:
    """Use a known tool that only handles the harness's own state, e.g. a plan, a to-do list, a wait or a question to the user.

    A tool that touches the task environment has a type of its own for what it does, e.g. `SearchFilesAction`.
    """


@dataclass(frozen=True, slots=True)
class UnknownAction:
    """Use an unknown tool, or make a call that could not be converted."""


@final
@dataclass(frozen=True, slots=True)
class MatchedFormat:
    """A declared harness result format matched the result."""

    name: str  # unique within one (harness, tool)

    def __str__(self) -> str:
        return self.name


class UnmatchedFormat(Enum):
    """No declared format produced the output."""

    UNKNOWN = "unknown_format"  # the tool has formats, but this result matched none
    SKIPPED = "skipped_format"  # the tool has no formats, so none were tried

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ToolCall:
    """One tool call in common types, as the trajectory records it."""

    harness_tool_call: HarnessToolCall
    action: ToolCallAction
    result: ToolCallResult | None  # None when the trajectory has no result


@dataclass(frozen=True, slots=True)
class HarnessToolCall:
    """One tool call from the trajectory, paired with its result."""

    key: ToolCallKey
    tool: HarnessTool
    # From the trajectory. It can be empty or repeated, so it is not a key.
    tool_call_id: str
    # The arguments in the trajectory.
    args: dict[str, Any]
    # The result object in the trajectory, or None when the call has none.
    result: dict[str, Any] | None
    is_subagent: bool = False


@dataclass(frozen=True, slots=True)
class ToolCallKey:
    """Unique position of a tool call in the trajectories."""

    trial_id: str  # Harbor Hub trial id
    trajectory_id: str  # "main", or "main/sub0" for the first subagent (0-based)
    step_id: int  # the step's step_id in the trajectory, 1-based
    call_index: int  # 0-based position in the step's tool_calls


@dataclass(frozen=True, slots=True)
class HarnessTool:
    """A tool as named by its harness."""

    harness: str
    name: str


@dataclass(frozen=True, slots=True)
class ToolCallResult:
    """Result of a tool call, in common types."""

    # The tool output as plain text, e.g. without line numbers.
    # "" when the tool showed no output, None when the trajectory holds no text of what it returned.
    # When no format matched, the raw text as is.
    tool_output_text: str | None = None
    execution_status: ExecutionStatus = ExecutionStatus.UNKNOWN
    # Real exit codes only.
    exit_code: int | None = None
    # The HTTP status a web fetch reports. A fetch has no exit code to hold it.
    http_status: int | None = None
    # For a PollAction, the target the result named. Otherwise the commands, scripts or subagents this call started.
    handles: tuple[ExecutionHandle, ...] = ()
    # The file holding the full output.
    output_path: str | None = None
    # None when the trajectory says nothing.
    is_truncated: bool | None = None
    # The harness result format that produced the fields above, see knowledge/harness_result_format_declaration.py.
    #   MatchedFormat(name)      the format that matched
    #   UnmatchedFormat.UNKNOWN  the tool has formats, but none matched
    #   UnmatchedFormat.SKIPPED  the tool has no formats, so none were tried
    # For audits, review and evidence only. Later steps must not branch on it.
    harness_result_format: FormatMatch = UnmatchedFormat.SKIPPED


@dataclass(frozen=True, slots=True)
class ExecutionHandle:
    """Id of a command, script or subagent that an earlier call started, used by a later call to read or stop it."""

    kind: ExecutionHandleKind
    id: str


class ExecutionHandleKind(StrEnum):
    """Kind of a handle's target."""

    COMMAND = "command"  # one shell command string
    SCRIPT = "script"  # a tool script, the code of a RunToolScriptAction
    SUBAGENT = "subagent"  # a subagent started earlier
    UNKNOWN = "unknown"  # cannot confirm from the trajectory


@dataclass(frozen=True, slots=True)
class UnreadableTrajectory:
    """Result of reading a trial whose trajectory file gives no tool calls, returned in place of the calls so that the trial is not taken for one without calls."""

    reason: UnreadableTrajectoryReason


class UnreadableTrajectoryReason(StrEnum):
    """Reason a trial's trajectory could not be read."""

    MISSING = "missing"  # the trial folder has no trajectory file
    INVALID_JSON = "invalid_json"  # the file holds broken JSON or broken UTF-8


@dataclass(frozen=True, slots=True)
class HarnessToolLabel:
    """Answer of the harness tool catalog about one harness tool and the arguments of one call of it, read by `convert_tool_calls` to build the `ToolCallAction` of that call."""

    # The name of a `ToolCallAction` member class, or `DEFERRED`.
    action_type: str
    # The action field each argument of the call fills, by argument name. An argument that fills none is absent.
    action_field_by_argument_name: Mapping[str, str]
    # Whether the tool stops a command, script or subagent started earlier.
    stops_execution: bool
    # The kind of target that the handles in the arguments of the call name, None when the catalog gives none or the call has no such argument.
    argument_handle_kind: ExecutionHandleKind | None


@dataclass(frozen=True, slots=True)
class UnknownHarnessToolLabel:
    """Answer of the harness tool catalog for a harness tool without a row, which `convert_tool_calls` turns into an `UnknownAction`."""


# The `action_type` of a tool whose converter decides the `ToolCallAction` class per call.
DEFERRED = "Deferred"
# The member classes of `ToolCallAction` by name, e.g. `RunCommandAction`.
TOOL_CALL_ACTION_CLASSES = {
    cls.__name__: cls for cls in get_args(ToolCallAction.__value__)
}
