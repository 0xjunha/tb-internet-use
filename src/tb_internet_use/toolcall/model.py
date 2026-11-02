"""Harness-agnostic common types for tool calls in ATIF trajectories"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ExecutionHandleKind(StrEnum):
    """What a handle points at."""

    COMMAND = "command"  # one shell command string
    SCRIPT = "script"  # code that can run several commands


class ExecutionStatus(StrEnum):
    """How a command or script stood when its tool call returned."""

    EXITED = "exited"
    RUNNING = "running"
    KILLED = "killed"
    NOT_RUN = "not_run"
    UNKNOWN = "unknown"


class WebToolKind(StrEnum):
    """What a web tool does."""

    SEARCH = "search"
    FETCH = "fetch"


@dataclass(frozen=True, slots=True)
class ExecutionHandle:
    """Id that a later call uses to read or stop a command or script."""

    kind: ExecutionHandleKind
    id: str


@dataclass(frozen=True, slots=True)
class RunCommandAction:
    """Run a string in a shell in one go; it can chain several commands."""

    command_str: str | None = None  # None when Codex `exec` JS builds it at run time
    workdir: str | None = None


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
class WebToolAction:
    """Search or fetch with a dedicated web tool."""

    kind: WebToolKind
    target: str | None = None


@dataclass(frozen=True, slots=True)
class PollAction:
    """Read from, write to or stop a command or script started earlier."""

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
    | WebToolAction
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

    trial_id: str
    trajectory_id: str
    step_id: int
    call_index: int


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
