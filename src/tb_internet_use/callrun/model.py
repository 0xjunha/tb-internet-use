"""Run types for tool calls in a trial, which expand each call into everything it actually ran and the calls that show its output.

A request can sit in a file that an earlier call wrote, e.g. `bash fetch.sh`, and its output can show up only in a later poll or log read, e.g. `tail fetch.log`.
"""

from dataclasses import dataclass
from enum import StrEnum

from tb_internet_use.shell.model import (
    CaptureDestination,
    DiscardDestination,
    FileDestination,
    ResultDestination,
    ShellCommand,
)
from tb_internet_use.toolcall.model import ExecutionStatus, ToolCall, ToolCallKey

# Source of a shell text that a call ran.
type ShellTextSource = (
    CallCommandText | ScriptStepText | PollInputText | FileText | StdinText
)
# Source of Python or JavaScript code that a call ran.
type CodeTextSource = FileText | StdinText | ArgumentText
# End of an output stream, after the commands that read it through a pipe.
# A route that ends in a capture stops there, since the command that receives a `$(...)` is not recorded.
type OutputRouteEnd = (
    ResultDestination | FileDestination | CaptureDestination | DiscardDestination
)


@dataclass(frozen=True, slots=True)
class CallRun:
    """Run result of one tool call, expanded over its whole trial into everything the call actually ran, including what its own text does not show."""

    call: ToolCall
    # Shell texts the call ran, i.e. its command string, script steps or typed input, and the shell files and heredocs their commands run.
    # e.g. the text of `bash fetch.sh > log` and the content of fetch.sh
    shell_texts: tuple[RanShellText, ...]
    # Python or JavaScript code the call's commands ran.
    # e.g. the content of get.py for `python get.py`, or the code of `python -c`
    code_texts: tuple[RanCodeText, ...]
    # Status and exit code of its command text. None when the call has no command text or no result.
    command_text_status: CommandTextStatus | None
    # Later calls that poll a handle this call started.
    # For a call that typed input, the later polls of the same handle.
    polls: tuple[ToolCallKey, ...]
    # Later readers of `call.output.output_path`, the file where the harness saved the call's whole result.
    # The readers of an output file that a poll result names are on the poll's own CallRun, found through `polls`.
    harness_output_file_readers: tuple[FileReader, ...]
    # Readers of each file that commands of the call send output to, e.g. `> fetch.log` or `tee fetch.log`.
    # A file that no call reads has no entry.
    redirected_output_reads: tuple[RedirectedOutputReads, ...]


@dataclass(frozen=True, slots=True)
class RanShellText:
    """Shell text run by a tool call, with its source and its commands."""

    source: ShellTextSource
    # None when the trial does not hold the text, e.g. a script file that no call wrote,
    # a file edited with content the trial does not show, or a step whose command the script builds at run time.
    commands: tuple[RanCommand, ...] | None


@dataclass(frozen=True, slots=True)
class CallCommandText:
    """Text source for the `command_str` of the call's `RunCommandAction`."""


@dataclass(frozen=True, slots=True)
class ScriptStepText:
    """Text source for the `command_str` of a `RunCommandAction` step of the call's `RunToolScriptAction`.

    The call's result shows the step's output only if the script prints it.
    """

    step_index: int  # 0-based in `RunToolScriptAction.steps`


@dataclass(frozen=True, slots=True)
class PollInputText:
    """Text source for the `input` of a `PollAction`, typed into a command or script started earlier."""

    # 0-based in `RunToolScriptAction.steps`, None when the poll is the call's action.
    step_index: int | None
    # The call that started the polled handle, None when no earlier call did.
    started_by: ToolCallKey | None


@dataclass(frozen=True, slots=True)
class FileText:
    """Text source for a file that a command runs, e.g. fetch.sh in `bash fetch.sh` or get.py in `python get.py`."""

    runner_command_id: int
    # The path as the runner's words name it.
    path: str
    # The last call that wrote the file before it ran, None when no call did, e.g. a file from the task image.
    # It can be the running call itself, e.g. `cat > f.sh <<EOF ... EOF; bash f.sh`.
    # It tells a file written with content the trial does not show apart from a file no call wrote.
    written_by: ToolCallKey | None


@dataclass(frozen=True, slots=True)
class StdinText:
    """Text source for a heredoc or herestring that a command runs, e.g. `bash <<EOF` or `python - <<EOF`."""

    runner_command_id: int


@dataclass(frozen=True, slots=True)
class RanCommand:
    """Simple command run by a tool call, with its variable values and output routes."""

    # The command as `parse_shell` gives it, with `$NAME` kept in its words.
    command: ShellCommand
    # One per variable in its words or redirect file paths that has literal values, e.g. U in `U=https://a.org; curl $U` or LOG in `curl u > $LOG`.
    variable_values: tuple[VariableValues, ...]
    # One route per end of the output. Several when a `tee` on the way, e.g. `| tee log` or `>(tee log)`, also writes it to a file.
    stdout_routes: tuple[OutputRoute, ...]
    stderr_routes: tuple[OutputRoute, ...]


@dataclass(frozen=True, slots=True)
class VariableValues:
    """Literal values that assignments before a command in its text give to a variable in its words or redirect file paths."""

    name: str
    # The values in text order, without repeats.
    values: tuple[str, ...]
    # True when the values are the items of the for loop closest before the command and the command is in a loop body, so it runs once per value.
    # False when it runs with one of them, e.g. after `A=1` in one if branch and `A=2` in the other.
    takes_each_value_in_turn: bool


@dataclass(frozen=True, slots=True)
class OutputRoute:
    """Route of a command's stdout or stderr through its pipe readers to its end."""

    # The first command of each pipeline stage it passes through, in order. The end is where the last stage sends its output.
    # e.g. (id of tail,) for curl's stdout in `curl u | tail -1`, or (id of grep a,) in `curl u | { grep a; grep b; }`
    pipe_reader_ids: tuple[int, ...]
    end: OutputRouteEnd


@dataclass(frozen=True, slots=True)
class RanCodeText:
    """Python or JavaScript code run by a command of a tool call."""

    source: CodeTextSource
    language: CodeLanguage
    # None when the trial does not hold it, e.g. a .py file that no call wrote.
    code: str | None


@dataclass(frozen=True, slots=True)
class ArgumentText:
    """Text source for code given as an argument, e.g. `python -c '...'` or `node -e '...'`."""

    runner_command_id: int


class CodeLanguage(StrEnum):
    """Language of a code text."""

    PYTHON = "python"
    JAVASCRIPT = "javascript"  # also TypeScript, e.g. a .ts file run by bun or tsx


@dataclass(frozen=True, slots=True)
class CommandTextStatus:
    """Execution status and exit code of a call's command text, from the first later poll that saw it end, or else from the call's own result.

    A poll result reports the polled command's state, so a command run in the background gets its exit code from a later poll.
    """

    execution_status: ExecutionStatus
    exit_code: int | None
    # The call itself, or the poll whose result gave this status and exit code.
    reported_by: ToolCallKey


@dataclass(frozen=True, slots=True)
class FileReader:
    """Call that reads a file, with a read tool or a command such as `tail fetch.log`, so its output can show the file's content."""

    call: ToolCallKey  # can be the call that wrote the file, e.g. `cmd > log; tail log`
    command_id: int | None  # the reading command in that call, None for a read tool


@dataclass(frozen=True, slots=True)
class RedirectedOutputReads:
    """Readers of one file that commands of a call send output to, by a redirect or as a `tee` argument."""

    # The path as the writing command names it, in a `FileDestination` or as a `tee` argument.
    path: str
    # Calls that read the file before a later call replaces its content, e.g. with `>` or a write tool.
    readers: tuple[FileReader, ...]
