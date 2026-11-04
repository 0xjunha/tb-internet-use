"""Harness-agnostic common types for tool calls in ATIF trajectories"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ExecutionHandleKind(StrEnum):
    """What a handle points at."""

    COMMAND = "command"  # one shell command string
    SCRIPT = "script"  # code that can run several commands
    SUBAGENT = "subagent"  # a subagent started earlier


class ExecutionStatus(StrEnum):
    """How a command or script stood when its tool call returned."""

    EXITED = "exited"
    RUNNING = "running"
    KILLED = "killed"
    NOT_RUN = "not_run"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ExecutionHandle:
    """Id that a later call uses to read or stop what an earlier call started."""

    kind: ExecutionHandleKind
    id: str


@dataclass(frozen=True, slots=True)
class RunCommandAction:
    """Run a string in a shell in one go; it can chain several commands."""

    command_str: str | None = None  # None when Codex `exec` JS builds it at run time


@dataclass(frozen=True, slots=True)
class WriteFileAction:
    """Write a whole file with a dedicated tool."""

    path: str
    content: str | None = None


@dataclass(frozen=True, slots=True)
class EditFileAction:
    """Replace text in a file with a dedicated tool."""

    path: str
    old: str | None = None
    new: str | None = None


@dataclass(frozen=True, slots=True)
class ReadFileAction:
    """Read a file with a dedicated tool."""

    path: str
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
    """What a tool call returned."""

    raw_result: dict[str, Any]  # result object as logged
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
class ToolCall:
    """One logged tool call, converted to common types."""

    key: ToolCallKey
    tool: HarnessTool
    tool_call_id: str  # as logged; can be empty or repeated, so not a key
    raw_args: dict[str, Any]  # arguments as logged
    is_subagent: bool = False
    actions: tuple[Action, ...] = ()
    output: ToolCallOutput | None = None  # None when the log has no result
