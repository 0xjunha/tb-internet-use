"""Harness-agnostic common types for tool calls in ATIF trajectories"""

from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import Any, final


class ExecutionHandleKind(StrEnum):
    """What a handle points at."""

    COMMAND = "command"  # one shell command string
    SCRIPT = "script"  # a tool script, the code of a RunToolScriptAction
    SUBAGENT = "subagent"  # a subagent started earlier
    UNKNOWN = "unknown"  # cannot confirm from the trajectory


class ExecutionStatus(StrEnum):
    """How the requested work stood when the tool call returned.

    For a poll, this is the polled target's state, except NOT_RUN, which means
    the poll itself did nothing.

    A FINISHED result can still have handles. A Codex script can end while a command
    it started keeps running, and its exec or wait result names that command's session.
    """

    FINISHED = "finished"  # ended on its own, whether it succeeded or not
    RUNNING = "running"  # still going; the result comes in a later call
    TIMED_OUT = "timed_out"  # stopped by the harness's time limit
    KILLED = "killed"  # stopped by a signal or a stop request
    NOT_RUN = "not_run"  # the tool did no work
    UNKNOWN = "unknown"  # the trajectory does not say


@dataclass(frozen=True, slots=True)
class ExecutionHandle:
    """Id that a later call uses to read or stop what an earlier call started."""

    kind: ExecutionHandleKind
    id: str


def handles_from_ids(
    kind: ExecutionHandleKind, ids: Any
) -> tuple[ExecutionHandle, ...]:
    """Handles of one kind for a list of ids or one id, in order and without missing,
    empty or repeated ones."""
    return tuple(ExecutionHandle(kind, i) for i in string_tuple(ids))


def string_tuple(values: Any) -> tuple[str, ...]:
    """A list of values or one value as the strings of an Action field, in order and
    without missing, empty or repeated ones."""
    listed = values if isinstance(values, list) else [values]
    return tuple(dict.fromkeys(str(v) for v in listed if v not in (None, "")))


@dataclass(frozen=True, slots=True)
class RunCommandAction:
    """Run a string in a shell in one go; it can chain several commands."""

    command_str: str | None = None  # None when the trajectory has none


@dataclass(frozen=True, slots=True)
class RunToolScriptAction:
    """Run code that calls harness tools, e.g. Codex `exec`. The trajectory has one result for all of it."""

    code: str | None = None  # None when the trajectory has none
    # The Actions of the tool calls found in the code, in order.
    # One call can have several steps, e.g. a patch that changes several files.
    #
    # A step field is empty when the script builds the argument at run time,
    # e.g.
    # tools.exec_command({cmd: "ls /app"}) gives RunCommandAction("ls /app"), but
    # tools.exec_command({cmd: "ls " + dir}) gives RunCommandAction(None).
    steps: tuple[Action, ...] = ()


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
class ReadFileAction:
    """Read a file with a dedicated tool."""

    path: str | None = None  # None when the trajectory has none
    offset: int | None = None  # 1-based line; negative counts from the end
    limit: int | None = None  # number of lines


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
class PollAction:
    """Read from, write to or stop a command, script or subagent started earlier."""

    handles: tuple[ExecutionHandle, ...] = ()
    input: str | None = None  # text sent to stdin; None if the poll only reads
    terminate: bool = False


@dataclass(frozen=True, slots=True)
class OtherAction:
    """Use a known tool that needs no common type."""


@dataclass(frozen=True, slots=True)
class UnknownAction:
    """Use an unknown tool, or make a call that could not be converted."""


type Action = (
    RunCommandAction
    | RunToolScriptAction
    | WriteFileAction
    | EditFileAction
    | ReadFileAction
    | WebSearchAction
    | WebFetchAction
    | WebFindAction
    | PollAction
    | OtherAction
    | UnknownAction
)


@final
@dataclass(frozen=True, slots=True)
class MatchedFormat:
    """A declared harness result format matched the result."""

    name: str  # unique within one (harness, tool)

    def __str__(self) -> str:
        return self.name


class UnmatchedFormat(Enum):
    """No declared format produced the output."""

    UNKNOWN = "unknown_format"  # the tool has formats; this result matched none
    SKIPPED = "skipped_format"  # the tool has no formats, so none were tried

    def __str__(self) -> str:
        return self.value


# Which format produced a ToolCallOutput; str() gives the name the catalog and audit CSVs use.
type FormatMatch = MatchedFormat | UnmatchedFormat


@dataclass(frozen=True, slots=True)
class ToolCallOutput:
    """What a tool call returned, in common types."""

    # The tool output as plain text, e.g. without line numbers. "" when the tool
    # showed no output, None when the trajectory holds no text of what it returned.
    # When no format matched, the raw text as is.
    tool_output_text: str | None = None
    execution_status: ExecutionStatus = ExecutionStatus.UNKNOWN
    exit_code: int | None = None  # real exit codes only
    # The HTTP status a web fetch reports. A fetch has no exit code to hold it.
    http_status: int | None = None
    handles: tuple[ExecutionHandle, ...] = ()
    output_path: str | None = None  # file holding the full output
    is_truncated: bool | None = None  # None when the trajectory says nothing
    # The harness result format that produced the fields above, see result_formats.py.
    #   MatchedFormat(name)      the format that matched
    #   UnmatchedFormat.UNKNOWN  the tool has formats, but none matched
    #   UnmatchedFormat.SKIPPED  the tool has no formats, so none were tried
    # For audits, review and evidence only. Later stages must not branch on it.
    harness_result_format: FormatMatch = UnmatchedFormat.SKIPPED


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
class RawToolCall:
    """One tool call from the trajectory, paired with its result."""

    key: ToolCallKey
    tool: HarnessTool
    # From the trajectory. It can be empty or repeated, so it is not a key.
    tool_call_id: str
    args: dict[str, Any]  # the arguments in the trajectory
    # The result object in the trajectory, or None when the call has none.
    result: dict[str, Any] | None
    is_subagent: bool = False


@dataclass(frozen=True, slots=True)
class ToolCall:
    """One tool call in common types."""

    raw: RawToolCall
    action: Action
    output: ToolCallOutput | None  # None when the trajectory has no result
