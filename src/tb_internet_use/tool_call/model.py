"""Common types for the tool calls of ATIF trajectories, which `convert_tool_calls` gives so that later steps read the calls of every harness the same way.

Each harness names its tools and writes its results in its own way, e.g. a shell call is `Bash` in Claude Code and `exec_command` in Codex.

The command string of a `RunCommandAction` is also split into its simple commands, with when each runs and where its output goes, as shell grammar alone shows them. Text inside `bash -c '...'` is not split here, since that needs a fact about bash. It stays one word of the outer command, and `expand_tool_calls` splits it.
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
    | ChangeFilesAction
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

# Destination of a command's stdout or stderr.
type OutputDestination = (
    ResultDestination
    | FileDestination
    | PipeDestination
    | CaptureDestination
    | DiscardDestination
)


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
    """List the steps of a tool script with their 0-based index, or else the actions of the call with index None, i.e. the file changes of a `ChangeFilesAction` or the action alone.

    One call can run a script of several tool steps, e.g. a Codex `exec` that runs a command and then fetches a page, and later steps read each step, e.g. to record which step a request came from.
    The file changes of a `ChangeFilesAction` get no index, since they are parts of the call's own action and not steps of a script.
    """
    if isinstance(action, RunToolScriptAction):
        return tuple(enumerate(action.steps))
    if isinstance(action, ChangeFilesAction):
        return tuple((None, file_change) for file_change in action.file_changes)
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
    """Action of a tool call that runs a string in a shell in one go. The string can chain several commands."""

    # None when the trajectory has none.
    command_str: str | None = None
    # None when `command_str` is None.
    parsed_shell_text: ParsedShellText | UnreadableShellText | None = None


@dataclass(frozen=True, slots=True)
class UnreadableShellText:
    """Shell text that `parse_shell_text` could not split, standing where a `ParsedShellText` would. It has a syntax error and gave no command, e.g. a text of closing brackets only."""


@dataclass(frozen=True, slots=True)
class ParsedShellText:
    """Parse result of one shell text, returned by `parse_shell_text` and read by `expand_tool_calls`."""

    commands: tuple[ShellCommand, ...]
    variable_assignments: tuple[VariableAssignment, ...]  # in text order


@dataclass(frozen=True, slots=True)
class ResultDestination:
    """Output destination for the call's own result."""


@dataclass(frozen=True, slots=True)
class FileDestination:
    """Output destination for a file, e.g. `> fetch.log` or `>> fetch.log`."""

    path: str  # without quotes, e.g. fetch.log or $LOG/out
    appends: bool  # True for `>>`, which keeps what the file holds


@dataclass(frozen=True, slots=True)
class PipeDestination:
    """Output destination for another command's stdin, e.g. the next stage of a pipeline."""

    reader_id: int  # the first command that reads it


@dataclass(frozen=True, slots=True)
class CaptureDestination:
    """Output destination for a `$(...)` or `<(...)`, which hands it to the enclosing command."""


@dataclass(frozen=True, slots=True)
class DiscardDestination:
    """Output destination that throws output away, e.g. `> /dev/null`."""


@dataclass(frozen=True, slots=True)
class ShellCommand:
    """One simple command in a shell text, with when it runs and where its output goes, as shell grammar alone shows them."""

    # Unique within one call. 0-based.
    # The ids continue across the command strings of one call, e.g. the steps of a Codex `exec` script, and a command that `expand_tool_calls` adds from a file or an argument gets the id after the largest one of the call.
    id: int
    # The command name, then its arguments, without quotes, e.g. `("sudo", "bash", "-c", "curl u")` for `sudo bash -c 'curl u'`.
    words: tuple[str, ...]
    # 0-based indexes of the words that hold `$A`, `${A}`, `$(...)`, backticks, `<(...)`, `>(...)` or `$((...))` outside single quotes, kept as written in `words`. A glob such as `*.sh` and a brace list such as `{a,b}` are not among them.
    # The indexes are `(2,)` for `pip install "$PKG"`, for example.
    expansion_word_indexes: tuple[int, ...] = ()
    # Text that a heredoc or herestring gives to stdin.
    stdin_text: str | None = None
    # Whether the delimiter of the heredoc in `stdin_text` has a quote or a backslash, e.g. True for `<<'EOF'` and `<<\EOF`, False for `<<EOF` and `<<-EOF`, None when `stdin_text` is no heredoc.
    # It exists because an unquoted delimiter lets the shell expand `$A`, `$(...)` and backticks in the body before the command reads it, so the body as written is then not the text the command reads.
    is_heredoc_delimiter_quoted: bool | None = None
    # File that a `<` redirect gives to stdin, as written.
    stdin_file_path: str | None = None
    stdout: OutputDestination = ResultDestination()
    stderr: OutputDestination = ResultDestination()
    # All must hold for it to run.
    runs_if: tuple[RunCondition, ...] = ()
    # It may run any number of times, including none.
    in_loop_body: bool = False
    # It runs only if the function is called.
    in_function_body: bool = False
    # It runs only if its pattern matches.
    in_case_branch: bool = False
    # If the whole text exits 0, this command exited 0.
    # This holds for b in `a; b`, for a and b in `a && b` and for neither in `a || b`.
    succeeded_if_text_exits_zero: bool = False
    # The text has a syntax error, a brace list, lines that stayed joined after the line repairs or a statement that tree-sitter-bash misreads and the reading does not repair, so the fields above may be wrong.
    # Those statements are a `time` before a reserved word, `((`, an assignment or words beside a subshell, e.g. `time { a; }`, and a statement that is no simple command with words after its redirect target, e.g. `{ a; } > f b`.
    # A result that rests on them is then not given as confirmed. A text with a syntax error that gives no command at all is an `UnreadableShellText` instead.
    structure_may_be_wrong: bool = False


@dataclass(frozen=True, slots=True)
class RunCondition:
    """Run condition of a command, met when its deciding commands ended with the required outcome.

    In `a || b`, b has `RunCondition((id of a,), ExitOutcome.FAILURE)`.
    """

    deciding_command_ids: tuple[int, ...]  # empty when unknown, e.g. after `!`
    required_outcome_of_deciding_commands: ExitOutcome


class ExitOutcome(StrEnum):
    """Exit outcome of a command, by whether its exit code is 0."""

    SUCCESS = "success"  # exit code 0
    FAILURE = "failure"  # any other exit code


@dataclass(frozen=True, slots=True)
class VariableAssignment:
    """Value that `NAME=value` or a for loop gives to a variable."""

    name: str
    # None when the text computes the value as it runs, e.g. `A=$(date)`.
    value: str | None
    # The id the next command of the text gets, so commands from this id on come after it.
    next_command_id: int
    # For an item of a for loop, the id the first command after the loop gets. None for `NAME=value`.
    next_command_id_after_for_loop: int | None


@dataclass(frozen=True, slots=True)
class RunToolScriptAction:
    """Action of a tool call that runs code calling harness tools, e.g. Codex `exec`. The trajectory has one result for all of it."""

    # The code of the script, None when the trajectory has none.
    code: str | None = None
    # The ToolCallActions of the tool calls found in the code, in order. One call can have several steps, e.g. a patch that changes several files.
    # A step field is empty when the script builds the argument at run time, e.g. `tools.exec_command({cmd: "ls /app"})` gives `RunCommandAction("ls /app")`, but `tools.exec_command({cmd: "ls " + dir})` gives `RunCommandAction(None)`.
    steps: tuple[ToolCallAction, ...] = ()


@dataclass(frozen=True, slots=True)
class WriteFileAction:
    """Action of a tool call that writes a whole file with a dedicated tool."""

    path: str | None = None  # None when the trajectory has none
    content: str | None = None


@dataclass(frozen=True, slots=True)
class EditFileAction:
    """Action of a tool call that replaces text in a file with a dedicated tool."""

    path: str | None = None  # None when the trajectory has none
    old: str | None = None
    new: str | None = None


@dataclass(frozen=True, slots=True)
class DeleteFileAction:
    """Action of a tool call that deletes a file with a dedicated tool."""

    path: str | None = None  # None when the trajectory has none


@dataclass(frozen=True, slots=True)
class ChangeFilesAction:
    """Action of a tool call that adds, changes and deletes files in one go with a dedicated tool, e.g. a patch of Copilot CLI `apply_patch`.

    Later steps read each file change as they read a call of a write, edit or delete tool, through `indexed_action_steps_of`.
    A patch in a Codex `exec` script gives its file changes as steps of the `RunToolScriptAction` instead.
    """

    # In the order of the patch, e.g. a `WriteFileAction` for an added file, then an `EditFileAction` for each hunk of a changed one.
    file_changes: tuple[WriteFileAction | EditFileAction | DeleteFileAction, ...] = ()


@dataclass(frozen=True, slots=True)
class ReadFileAction:
    """Action of a tool call that reads a file with a dedicated tool."""

    path: str | None = None  # None when the trajectory has none
    offset: int | None = None  # 1-based line, and a negative one counts from the end
    limit: int | None = None  # number of lines


@dataclass(frozen=True, slots=True)
class SearchFilesAction:
    """Action of a tool call that searches the content of files with a dedicated tool."""

    # The files or folders searched, empty when the trajectory has none.
    paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ListFilesAction:
    """Action of a tool call that finds files by name or lists a folder with a dedicated tool."""

    path: str | None = None  # the folder, None when the trajectory has none


@dataclass(frozen=True, slots=True)
class WebSearchAction:
    """Action of a tool call that searches with a dedicated web tool."""

    queries: tuple[str, ...] = ()  # empty when the trajectory has none


@dataclass(frozen=True, slots=True)
class WebFetchAction:
    """Action of a tool call that opens pages with a dedicated web tool."""

    urls: tuple[str, ...] = ()  # empty when the trajectory has none


@dataclass(frozen=True, slots=True)
class WebFindAction:
    """Action of a tool call that finds text in a page with a dedicated web tool."""

    urls: tuple[str, ...] = ()  # empty when the trajectory has none


@dataclass(frozen=True, slots=True)
class StartSubagentAction:
    """Action of a tool call that starts a subagent, whose own calls may or may not be in the trajectory."""


@dataclass(frozen=True, slots=True)
class PollAction:
    """Action of a tool call that reads from, writes to or stops a command, script or subagent started earlier."""

    handles: tuple[ExecutionHandle, ...] = ()
    input: str | None = None  # text sent to stdin, None if the poll only reads
    terminate: bool = False


@dataclass(frozen=True, slots=True)
class OtherAction:
    """Action of a tool call that uses a known tool handling only the harness's own state, e.g. a plan, a to-do list, a wait or a question to the user.

    A tool that touches the task environment has a type of its own for what it does, e.g. `SearchFilesAction`.
    """


@dataclass(frozen=True, slots=True)
class UnknownAction:
    """Action of a tool call that uses an unknown tool, or of a call that could not be converted."""


@final
@dataclass(frozen=True, slots=True)
class MatchedFormat:
    """Format match of a tool result that one declared harness result format matched, held in `ToolCallResult.harness_result_format`."""

    name: str  # unique within one (harness, tool)

    def __str__(self) -> str:
        return self.name


class UnmatchedFormat(Enum):
    """Format match of a tool result that no declared harness result format matched, held in `ToolCallResult.harness_result_format`."""

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
    """One tool call from the trajectory, paired with its result, or one message that the harness wrote to the agent outside the results of calls, e.g. about the end of earlier work.

    Antigravity CLI writes the end of a background task as such a message, e.g. a `SYSTEM_MESSAGE` step that says the task exited with code 0 and shows its output. Its tool name is the name the harness gives the message, it has no `tool_call_id` and no arguments, and `is_harness_message` tells it apart from a call of the agent.
    """

    key: ToolCallKey
    tool: HarnessTool
    # From the trajectory, "" for a message that the harness wrote. It can be empty or repeated, so it is not a key.
    tool_call_id: str
    # The arguments in the trajectory, {} for a message that the harness wrote.
    args: dict[str, Any]
    # The result object in the trajectory, an object whose `content` is the message as the step holds it for a message that the harness wrote, or None when the call has none.
    result: dict[str, Any] | None
    # True for a call of a subagent trajectory, or of a step whose `extra.is_sidechain` is true or whose `extra.parentToolCallId` is set in the trajectory.
    is_subagent: bool = False
    # True for a message that the harness wrote to the agent outside the results of calls, which audits and judgment rule counts keep apart from the calls of the agent.
    is_harness_message: bool = False


@dataclass(frozen=True, slots=True)
class ToolCallKey:
    """Unique position of a tool call in the trajectories."""

    # The name of the trial folder, as in Trial.trial_id.
    trial_id: str
    # "main", or "main/sub0" for the first subagent (0-based).
    trajectory_id: str
    # The step's step_id in the trajectory, 1-based.
    step_id: int
    # The 0-based position in the step's tool_calls, or for a message that the harness wrote in the step, the number of tool_calls plus the 0-based position of the message among the messages of the step, so that the messages follow the calls and keys stay unique.
    call_index: int


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
    # The harness result format that produced the fields above, see knowledge/declarations/tool_call/harness_result_format_declaration.py.
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


@dataclass(frozen=True, slots=True)
class UnknownHarnessReturnCodeInterpretation:
    """Answer of `harness_return_code_interpretations.csv` for a text without a row, for which `convert_tool_calls` gives no exit code."""


# The `action_type` of a tool whose converter decides the `ToolCallAction` class per call.
DEFERRED = "Deferred"
# The member classes of `ToolCallAction` by name, e.g. `RunCommandAction`.
TOOL_CALL_ACTION_CLASSES = {
    cls.__name__: cls for cls in get_args(ToolCallAction.__value__)
}
