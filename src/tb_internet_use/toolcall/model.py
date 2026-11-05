"""Harness-agnostic common types for tool calls in ATIF trajectories"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ExecutionHandleKind(StrEnum):
    """What a handle points at."""

    COMMAND = "command"  # one shell command string
    SCRIPT = "script"  # code that can run several commands
    SUBAGENT = "subagent"  # a subagent started earlier
    UNKNOWN = "unknown"  # cannot confirm from the log


class ExecutionStatus(StrEnum):
    """How the requested work stood when the tool call returned.

    For a poll, this is the polled target's state, except NOT_RUN, which means
    the poll itself did nothing.
    """

    FINISHED = "finished"  # ended on its own, whether it succeeded or not
    RUNNING = "running"  # still going; the result comes in a later call
    KILLED = "killed"  # stopped from outside
    NOT_RUN = "not_run"  # the tool did no work
    UNKNOWN = "unknown"  # the log does not say


@dataclass(frozen=True, slots=True)
class ExecutionHandle:
    """Id that a later call uses to read or stop what an earlier call started."""

    kind: ExecutionHandleKind
    id: str


@dataclass(frozen=True, slots=True)
class RunCommandAction:
    """Run a string in a shell in one go; it can chain several commands."""

    command_str: str | None = None  # None when the log has none or JS builds it later


@dataclass(frozen=True, slots=True)
class RunScriptAction:
    """Run code that can call several tools; the log has one result for all of it."""

    code: str | None = None  # None when the log has none
    steps: tuple[Action, ...] = ()  # tool calls found in the code, in order


@dataclass(frozen=True, slots=True)
class WriteFileAction:
    """Write a whole file with a dedicated tool."""

    path: str | None = None  # None when the log has none
    content: str | None = None


@dataclass(frozen=True, slots=True)
class EditFileAction:
    """Replace text in a file with a dedicated tool."""

    path: str | None = None  # None when the log has none
    old: str | None = None
    new: str | None = None


@dataclass(frozen=True, slots=True)
class ReadFileAction:
    """Read a file with a dedicated tool."""

    path: str | None = None  # None when the log has none
    offset: int | None = None  # 1-based line; negative counts from the end
    limit: int | None = None  # number of lines


@dataclass(frozen=True, slots=True)
class WebSearchAction:
    """Search with a dedicated web tool."""

    queries: tuple[str, ...] = ()  # empty when the log has none


@dataclass(frozen=True, slots=True)
class WebFetchAction:
    """Open pages with a dedicated web tool."""

    urls: tuple[str, ...] = ()  # empty when the log has none


@dataclass(frozen=True, slots=True)
class WebFindAction:
    """Find text in a page with a dedicated web tool."""

    urls: tuple[str, ...] = ()  # empty when the log has none


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
    | RunScriptAction
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


@dataclass(frozen=True, slots=True)
class ToolCallOutput:
    """What a tool call returned, in common types."""

    text: str | None = None  # body without what the harness wrapped around it
    execution_status: ExecutionStatus = ExecutionStatus.UNKNOWN
    exit_code: int | None = None  # real exit codes only
    handles: tuple[ExecutionHandle, ...] = ()
    output_path: str | None = None  # file holding the full output
    is_truncated: bool | None = None  # None when the log says nothing


@dataclass(frozen=True, slots=True)
class ToolCallKey:
    """Unique position of a tool call in the logs."""

    trial_id: str  # Harbor Hub trial id
    trajectory_id: str  # "main", or "main/sub0" for the first subagent (0-based)
    step_id: int  # as logged; 1-based in each trajectory
    call_index: int  # 0-based position in the step's tool_calls


@dataclass(frozen=True, slots=True)
class HarnessTool:
    """A tool as named by its harness."""

    harness: str
    name: str


@dataclass(frozen=True, slots=True)
class RawToolCall:
    """One tool call as logged, paired with its result."""

    key: ToolCallKey
    tool: HarnessTool
    tool_call_id: str  # as logged; can be empty or repeated, so not a key
    args: dict[str, Any]  # arguments as logged
    result: dict[str, Any] | None  # result object as logged; None when there is none
    is_subagent: bool = False


@dataclass(frozen=True, slots=True)
class ToolCall:
    """One tool call in common types."""

    raw: RawToolCall
    action: Action
    output: ToolCallOutput | None  # None when the log has no result
