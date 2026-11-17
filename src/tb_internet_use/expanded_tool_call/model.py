"""Expansion types for the tool calls of one trial, tying each call to everything it actually ran and to the later calls that show its output or use the files it wrote.

A call can run text that sits in a file an earlier call wrote, e.g. `bash build.sh`, and its output can show up only in a later poll or file read, e.g. `tail build.log`.

The module also holds the answers of `ExpandedToolCallKnowledge` that `expand_tool_calls` tells apart when it runs, e.g. `UnknownProgramBehavior`, since a step never imports the door when it runs.
"""

from dataclasses import dataclass
from enum import StrEnum

from tb_internet_use.tool_call.model import (
    CaptureDestination,
    DiscardDestination,
    ExecutionStatus,
    FileDestination,
    ResultDestination,
    ShellCommand,
    ToolCall,
    ToolCallKey,
)

# Text that a call ran. An `UnknownRanText` sits where the text would sit when the trial does not hold it.
type RanText = RanShellText | RanCodeText | UnknownRanText
# Source of a text that a call ran.
type RanTextSource = (
    CallCommandText
    | ScriptStepText
    | PollInputText
    | FileText
    | FileTextWithoutKnownWriter
    | StdinText
    | ArgumentText
)
# Source of shell text that a call ran. A file that no single call is known to have written is not one, since the trial does not hold its text.
type ShellTextSource = (
    CallCommandText
    | ScriptStepText
    | PollInputText
    | FileText
    | StdinText
    | ArgumentText
)
# Source of code that a call ran.
type CodeTextSource = FileText | StdinText | ArgumentText | PollInputText
# End of an output stream, after the commands that read it through a pipe.
type OutputRouteEnd = (
    ResultDestination | FileDestination | CaptureDestination | DiscardDestination
)


@dataclass(frozen=True, slots=True)
class ExpandedToolCall:
    """Expansion of one tool call over its whole trial into everything the call actually ran, including what its own text does not show."""

    tool_call: ToolCall
    # The texts the call ran, i.e. its command string, script steps or typed input, and the files, heredocs and arguments that their commands run.
    # For `bash fetch.sh > log` they are the text of the call, then the content of fetch.sh.
    ran_texts: tuple[RanText, ...]
    # Status and exit code of its command text. For a call without a result, the status is `UNKNOWN` and the reporter is the call itself.
    # None in two cases, which `tool_call.action` tells apart. The call has no command text, e.g. a poll or a read tool. Or it is a tool script, whose one result covers the texts of several steps.
    command_text_status: CommandTextStatus | None
    # The results of calls that show output of the call's commands, apart from reads of the files in `written_files`.
    output_places: tuple[OutputPlace, ...]
    # The files that the words of the call's commands or its write or edit tool write, by a redirect, as a `tee` argument, by the program itself, e.g. `curl -o a.tgz`, or as a tool argument.
    # They are listed for a call that did not run too, with no file uses, so the field says what the text writes and not that the file was written.
    written_files: tuple[WrittenFile, ...]
    # The uses that the call's commands or tool make of files that no call of the trial wrote, e.g. `cat README.md` for a file of the task image.
    # A line in the result of such a call can be content of the file and not something a program printed as it ran.
    file_uses_without_known_writer: tuple[FileUseWithoutKnownWriter, ...]


@dataclass(frozen=True, slots=True)
class RanShellText:
    """Shell text run by a tool call, with its source and its commands."""

    source: ShellTextSource
    ran_commands: tuple[RanCommand, ...]


@dataclass(frozen=True, slots=True)
class RanCodeText:
    """Python or JavaScript code run by a command of a tool call.

    It is not split into commands, since all of its output comes out as the output of that one command.
    """

    source: CodeTextSource
    code_language: CodeLanguage
    code: str


@dataclass(frozen=True, slots=True)
class UnknownRanText:
    """Text that a tool call ran and that could not be followed, kept so that later steps know something ran there."""

    source: RanTextSource
    reason: UnknownRanTextReason

    def __post_init__(self) -> None:
        """Refuse a reason that the source contradicts, e.g. `READ_FROM_PIPE` for a file."""
        if not _is_reason_possible_for_source(self.reason, self.source):
            raise ValueError(f"{self.reason} does not fit {self.source}")


def _is_reason_possible_for_source(
    reason: UnknownRanTextReason, source: RanTextSource
) -> bool:
    """Tell whether the trial can lack a text of this source for this reason."""
    match reason:
        case UnknownRanTextReason.NOT_WRITTEN_IN_TRIAL:
            return isinstance(source, FileTextWithoutKnownWriter)
        case UnknownRanTextReason.FITS_SEVERAL_WRITTEN_FILES:
            return isinstance(source, FileTextWithoutKnownWriter)
        case UnknownRanTextReason.CHANGED_BY_UNREAD_COMMAND:
            return isinstance(source, FileText)
        case UnknownRanTextReason.READ_FROM_PIPE:
            return isinstance(source, StdinText)
        case UnknownRanTextReason.BUILT_AT_RUN_TIME:
            return isinstance(source, ArgumentText | FileTextWithoutKnownWriter)
        case UnknownRanTextReason.MISSING_FROM_TRAJECTORY:
            return isinstance(source, CallCommandText | ScriptStepText)
        case UnknownRanTextReason.UNREADABLE_SHELL_TEXT:
            return not isinstance(source, FileTextWithoutKnownWriter)
        case UnknownRanTextReason.LANGUAGE_NOT_KNOWN:
            return isinstance(
                source, FileText | StdinText | ArgumentText | PollInputText
            )
        case UnknownRanTextReason.FILE_ALREADY_RUNNING:
            return isinstance(source, FileText)


class UnknownRanTextReason(StrEnum):
    """Reason a text that a call ran could not be followed."""

    # No call of the trial wrote the file, e.g. setup.sh of the task image.
    NOT_WRITTEN_IN_TRIAL = "not_written_in_trial"
    # A command with a result the trial does not show changed the file before it ran, e.g. `sed -i` or `curl -o f.sh`.
    CHANGED_BY_UNREAD_COMMAND = "changed_by_unread_command"
    # The path fits several files that calls wrote, e.g. fetch.sh for /a/fetch.sh and /b/fetch.sh.
    FITS_SEVERAL_WRITTEN_FILES = "fits_several_written_files"
    # The text, or the path of the file that holds it, is built when it runs, e.g. `bash -c "$CMD"` or `bash $F` where F has no single literal value.
    BUILT_AT_RUN_TIME = "built_at_run_time"
    # The text comes through a pipe, e.g. `curl u | bash`.
    READ_FROM_PIPE = "read_from_pipe"
    # The trajectory lacks the text of the call itself, e.g. a script step without its command string.
    MISSING_FROM_TRAJECTORY = "missing_from_trajectory"
    # The trial holds the text, but no fact says which language the program that takes it runs, e.g. `./run` without a `#!` line or text typed into gdb.
    LANGUAGE_NOT_KNOWN = "language_not_known"
    # The trial holds the text, but it has a syntax error and no command could be read from it.
    UNREADABLE_SHELL_TEXT = "unreadable_shell_text"
    # The file is already running in the same call, e.g. `bash f.sh` inside f.sh, so its text is not followed again.
    FILE_ALREADY_RUNNING = "file_already_running"


@dataclass(frozen=True, slots=True)
class CallCommandText:
    """Text source for the `command_str` of the call's `RunCommandAction`."""


@dataclass(frozen=True, slots=True)
class ScriptStepText:
    """Text source for the `command_str` of a `RunCommandAction` step of the call's `RunToolScriptAction`."""

    step_index: int  # 0-based in `RunToolScriptAction.steps`


@dataclass(frozen=True, slots=True)
class PollInputText:
    """Text source for the `input` of a `PollAction`, typed into a command or script started earlier."""

    # 0-based in `RunToolScriptAction.steps`, None when the poll is the call's action.
    step_index: int | None
    # The call that started the polled handle, None when no earlier call did.
    starter_tool_call_key: ToolCallKey | None


@dataclass(frozen=True, slots=True)
class FileText:
    """Text source for a file that a command runs, e.g. fetch.sh in `bash fetch.sh` or get.py in `python get.py`."""

    runner_command_id: int
    # The path as the runner's words name it. None when they name none, e.g. the Makefile of `make`.
    path: str | None
    # The last call that wrote the file before it ran. It can be the running call itself.
    writer_tool_call_key: ToolCallKey


@dataclass(frozen=True, slots=True)
class FileTextWithoutKnownWriter:
    """Text source for a file that a command runs and that no single call is known to have written, e.g. setup.sh of the task image.

    Its text is always an `UnknownRanText`, whose reason says whether no call wrote it, several fit or its path is built at run time.
    """

    runner_command_id: int
    # The path as the runner's words name it. None when they name none, e.g. the Makefile of `make`.
    path: str | None


@dataclass(frozen=True, slots=True)
class StdinText:
    """Text source for a heredoc, herestring or pipe that a command runs, e.g. `bash <<EOF` or `curl u | bash`."""

    runner_command_id: int


@dataclass(frozen=True, slots=True)
class ArgumentText:
    """Text source for text given as an argument, e.g. `bash -c '...'` or `python -c '...'`."""

    runner_command_id: int


@dataclass(frozen=True, slots=True)
class RanCommand:
    """Simple command run by a tool call, read once into its programs and with the routes of its output."""

    # The command as `parse_shell_text` gives it, with `$NAME` kept in its words. Its id is unique within the call.
    shell_command: ShellCommand
    # The programs its words run, the outermost first, e.g. sudo, then `uv run`, then `pip install` for `sudo uv run pip install x`.
    # The last one is an `UnknownProgramInvocation` when no fact covers the program.
    program_invocations: tuple[ProgramInvocation | UnknownProgramInvocation, ...]
    # One per variable in its words or redirect file paths that has literal values, e.g. D in `D=/tmp/build; ls $D`.
    variable_values: tuple[VariableValues, ...]
    # One route per end of the output. Several when a `tee` on the way also writes it to a file.
    stdout_routes: tuple[OutputRoute, ...]
    stderr_routes: tuple[OutputRoute, ...]


@dataclass(frozen=True, slots=True)
class ProgramInvocation:
    """Reading of the words that one program of a command takes, made once so that later steps do not read the words again."""

    # The name of its row in the catalog, e.g. pip for `pip3` and python for `/usr/bin/python3.11`. The word as written stays in `shell_command.words`.
    program_name: str
    # The words that pick what the program does, e.g. ("install",) for `pip install x`. Empty when it has none.
    subcommand_words: tuple[str, ...]
    # The options that a fact covers, in order.
    options: tuple[ProgramOption, ...]
    # The words that are neither options nor option values, in order, e.g. ("notes.txt",) for `cat -n notes.txt`.
    arguments: tuple[str, ...]
    # It gets more arguments when it runs, e.g. curl in `cat urls.txt | xargs curl`, so `arguments` may not be all of them.
    gets_more_arguments_at_run_time: bool
    # The words from the first option that no fact covers to the end, e.g. ("--foo", "x", "u") for `curl --foo x u`.
    # After such an option nobody knows whether the next word is its value, so these words are not read.
    unread_words: tuple[str, ...]
    # It runs the next program and ends with that program's exit code, e.g. sudo. False when it runs none, e.g. cat.
    # An `UnknownExitsWithExitCodeOfNextProgram` when its row of `program_behaviors.csv` leaves the cell blank, so later steps never read a missing fact as true.
    exits_with_exit_code_of_next_program: bool | UnknownExitsWithExitCodeOfNextProgram


@dataclass(frozen=True, slots=True)
class ProgramOption:
    """Option of a program in a command, with the value it takes."""

    name: str  # as written, e.g. `-o` or `--connect-timeout`
    value: str | None  # None for an option that takes none, e.g. `-s`


@dataclass(frozen=True, slots=True)
class UnknownProgramInvocation:
    """Words of a command whose program no fact covers, e.g. `mytool run x`. Whether it runs or reads anything is unknown."""

    program_name: str  # the first word without its folder, as written
    words: tuple[str, ...]  # the words after the program, as written


@dataclass(frozen=True, slots=True)
class VariableValues:
    """Literal values that assignments before a command in its text give to a variable in its words or redirect file paths."""

    name: str
    # The values in text order, without repeats.
    values: tuple[str, ...]
    # True when the values are the items of the for loop closest before the command and the command is in a loop body, so it runs once per value.
    # False when it runs with one of them, e.g. after `A=1` in one if branch and `A=2` in the other.
    takes_each_value_in_turn: bool
    # An assignment before the command also gives the variable a value that the text computes as it runs, e.g. `U=$(cat url.txt)`, so `values` may not be all of them.
    has_value_set_at_run_time: bool


@dataclass(frozen=True, slots=True)
class OutputRoute:
    """Route of a command's stdout or stderr through its pipe readers to its end."""

    # The first command of each pipeline stage it passes through, in order, e.g. the id of tail for the stdout of curl in `curl u | tail -1`.
    pipe_reader_command_ids: tuple[int, ...]
    end: OutputRouteEnd
    # How much of the output is still there at the end, after the pipe readers.
    visibility_at_end: OutputVisibility

    def __post_init__(self) -> None:
        """Refuse a route without pipe readers whose output is not all there at its end, e.g. `NONE` for the stdout of `ls > f`."""
        if not self.pipe_reader_command_ids and (
            self.visibility_at_end != OutputVisibility.WHOLE
        ):
            raise ValueError(f"{self.visibility_at_end} without pipe readers")


class OutputVisibility(StrEnum):
    """Share of a command's output that is left at the end of its route."""

    WHOLE = "whole"  # no pipe reader, or each passes on all, e.g. `tee log`
    PARTIAL = "partial"  # a reader that passes on some of its input, e.g. `tail -1`
    NONE = "none"  # a reader that shows none of its input, e.g. `tar xz` or `bash`
    UNKNOWN = "unknown"  # a reader that no fact covers, e.g. `ls | mytool`


@dataclass(frozen=True, slots=True)
class CommandTextStatus:
    """End state of a call's command text, taken from the first later poll that saw it end or else from the call's own result, so that later steps know whether the text ran and how it exited."""

    execution_status: ExecutionStatus
    exit_code: int | None
    # The call itself, or the poll whose result gave this status and exit code.
    reporter_tool_call_key: ToolCallKey


@dataclass(frozen=True, slots=True)
class OutputPlace:
    """Result of a call that shows output of this call's commands. It is the call's own result, a later poll of a handle the call started, or a later read of the file where the harness saved a whole result."""

    # The call whose result shows the output. It can be this call itself.
    showing_tool_call_key: ToolCallKey
    # The commands of this call whose output reaches the place.
    command_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class WrittenFile:
    """File that commands or a write or edit tool of a call write, with the later calls that read or use it.

    The file can hold lines that a program prints, e.g. `make > build.log`, or what a program produces, e.g. `tar czf a.tgz src`. These types do not tell the two apart.
    """

    # The path as the first writing command or the tool names it.
    path: str
    # At least one, since a `WrittenFile` is made from the writes of the call.
    writers: tuple[WrittenFileWriter, ...]
    # The uses before a later call replaces the file's content, in call order.
    file_uses: tuple[FileUse, ...]

    def __post_init__(self) -> None:
        """Refuse a written file without a writer, which would hide who wrote it."""
        if not self.writers:
            raise ValueError(f"written file {self.path} without writers")


@dataclass(frozen=True, slots=True)
class WrittenFileWriter:
    """Writer of a file in a call, either a command with the stream or the output file of its own that goes there, or the call's write or edit tool."""

    command_id: int | None  # None for a write or edit tool
    channel: FileWriteChannel

    def __post_init__(self) -> None:
        """Refuse a tool writer with a command id and a command writer without one."""
        is_tool = self.channel == FileWriteChannel.TOOL_ARGUMENT
        if is_tool != (self.command_id is None):
            raise ValueError(f"{self.channel} with command id {self.command_id}")


class FileWriteChannel(StrEnum):
    """Way a command or a tool writes a file."""

    # By a redirect of stdout or as a `tee` argument, e.g. `cmd > f`.
    STDOUT = "stdout"
    # By a redirect of stderr, e.g. `cmd 2> f`.
    STDERR = "stderr"
    # The program writes or changes it itself, e.g. `curl -o f u`, `cp a f` or `sed -i s/a/b/ f`.
    OWN_OUTPUT_FILE = "own_output_file"
    # The content is an argument of a write or edit tool.
    TOOL_ARGUMENT = "tool_argument"


@dataclass(frozen=True, slots=True)
class FileUse:
    """Use of a written file by a call, with a tool or a command."""

    # The using call. It can be the call that wrote the file.
    using_tool_call_key: ToolCallKey
    # The using command in that call, None for a tool.
    command_id: int | None
    kind: FileUseKind
    # The path fits several written files, so the use is recorded on each and belongs to one of them.
    fits_several_written_files: bool


@dataclass(frozen=True, slots=True)
class FileUseWithoutKnownWriter:
    """Use, with a tool or a command of a call, of a file that no call of the trial wrote, e.g. README.md of the task image in `cat README.md`."""

    command_id: int | None  # the using command, None for a tool
    path: str  # as the using command or tool names it
    kind: FileUseKind


class FileUseKind(StrEnum):
    """Kind of use that a call makes of a file."""

    # Its result can show the content, e.g. `cat`, `tail`, `grep` or a read tool.
    SHOWS_CONTENT = "shows_content"
    # It works on the content without showing it, e.g. `tar xzf`, `pip install ./x.whl` or `bash f.sh`.
    USES_CONTENT = "uses_content"
    # It shows only the size or the type, e.g. `ls -l`, `wc -c` or `file`.
    SHOWS_SIZE_OR_TYPE = "shows_size_or_type"
    # A program that no fact covers takes the path as an argument.
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ProgramBehavior:
    """Answer of `ExpandedToolCallKnowledge` about how one program and subcommand uses its words and its stdin, as its row of `program_behaviors.csv` gives it."""

    program_name: str
    subcommand_words: tuple[str, ...]
    # The role of each word that is neither an option nor an option value.
    argument_role: ProgramWordRole | UnknownProgramWordRole
    # The role of the first such word, e.g. `RUN_FILE` for bash and `PATTERN` for grep.
    first_argument_role: ProgramWordRole | UnknownProgramWordRole | SameAsArgumentRole
    # The role of the last such word, e.g. `COPY_DESTINATION` for cp.
    last_argument_role: ProgramWordRole | UnknownProgramWordRole | SameAsArgumentRole
    # The role of stdin when no argument names a file or the argument is `-`. None when the row says `none`.
    stdin_role: ProgramWordRole | UnknownProgramWordRole | None
    # The share of piped input that it passes on to its own stdout. `UNKNOWN` when the cell is blank.
    visibility_of_piped_input: OutputVisibility
    # It gives the next program arguments that the text does not hold, e.g. xargs.
    gives_arguments_at_run_time: bool
    # It skips the `NAME=value` words before the next program, e.g. env.
    skips_assignment_words: bool
    # The words after its first argument are not its options, e.g. `python get.py -o x`.
    options_end_at_first_argument: bool
    # `-fsSL` is four options. False for find, java and go.
    takes_one_letter_options_joined: bool
    # The text it runs runs inside the calling shell and sees its assignments, e.g. eval, source and `.`. False for bash and sh.
    runs_text_in_calling_shell: bool
    # False when the cell is `no`. An `UnknownExitsWithExitCodeOfNextProgram` when it is blank.
    exits_with_exit_code_of_next_program: bool | UnknownExitsWithExitCodeOfNextProgram
    # The file it runs when its words name none, e.g. Makefile for make. None when the row says `none`.
    default_run_file: str | None


@dataclass(frozen=True, slots=True)
class UnknownExitsWithExitCodeOfNextProgram:
    """Answer of `ExpandedToolCallKnowledge`, standing where True or False would, to whether a program ends with the exit code of the program it runs, when its row of `program_behaviors.csv` leaves that cell blank."""

    def __bool__(self) -> bool:
        """Refuse to be read as True or False, so that `if` and `all` never take a blank cell for a yes."""
        raise TypeError(
            "whether the program ends with the exit code of the next program is not known"
        )


@dataclass(frozen=True, slots=True)
class UnknownProgramBehavior:
    """Answer of `ExpandedToolCallKnowledge` for a program without a row of `program_behaviors.csv`."""


@dataclass(frozen=True, slots=True)
class ProgramOptionBehavior:
    """Answer of `ExpandedToolCallKnowledge` about one option of a program, as its row of `program_option_behaviors.csv` gives it."""

    takes_value: bool
    # None when it takes no value.
    value_role: ProgramWordRole | UnknownProgramWordRole | None
    # The role that the arguments have when the command has this option, e.g. `CHANGED_FILE` for `-i` of sed. None when the row says `unchanged`.
    argument_role_with_option: ProgramWordRole | UnknownProgramWordRole | None
    # None when the row says `unchanged`.
    first_argument_role_with_option: (
        ProgramWordRole | UnknownProgramWordRole | SameAsArgumentRole | None
    )
    # None when the row says `unchanged`.
    last_argument_role_with_option: (
        ProgramWordRole | UnknownProgramWordRole | SameAsArgumentRole | None
    )
    # The other option whose value gets another role when the command has this option, e.g. `-f` for `-c` of tar. None when the row says `none`.
    changed_option_name: str | None
    # The role that the value of that other option gets. None when the row names no other option.
    changed_option_value_role: ProgramWordRole | UnknownProgramWordRole | None
    # It gives the next program arguments that the text does not hold, e.g. `-exec` of find.
    gives_arguments_at_run_time: bool
    # The words that end the words of the next program, e.g. `;` and `+` for `-exec` of find.
    next_program_end_words: tuple[str, ...]
    # None when the row says `unchanged`.
    exits_with_exit_code_of_next_program_with_option: bool | None

    def __post_init__(self) -> None:
        """Refuse a value role that disagrees with whether the option takes a value, e.g. one for `-s` of curl, and a changed option name without the role of its value or the other way round."""
        if (self.value_role is None) == self.takes_value:
            raise ValueError(
                f"value role {self.value_role} with takes_value {self.takes_value}"
            )
        if (self.changed_option_value_role is None) != (
            self.changed_option_name is None
        ):
            raise ValueError(
                f"changed option {self.changed_option_name} with role {self.changed_option_value_role}"
            )


@dataclass(frozen=True, slots=True)
class UnknownProgramOptionBehavior:
    """Answer of `ExpandedToolCallKnowledge` for an option without a row of `program_option_behaviors.csv`."""


@dataclass(frozen=True, slots=True)
class UnknownProgramWordRole:
    """Role of a word that `program_behaviors.csv` or `program_option_behaviors.csv` leaves blank, standing where a `ProgramWordRole` would, also when two options of one command give one place different roles."""


@dataclass(frozen=True, slots=True)
class SameAsArgumentRole:
    """Role of the first or last argument that is the role `argument_role` has after the options of the command, so the word is not treated apart from the other arguments."""


class ProgramWordRole(StrEnum):
    """Role that a word of a command has for its program, read by `expand_tool_calls` to follow run text and to record file writes and uses."""

    # The next program starts at this word, e.g. curl in `sudo curl u`.
    PROGRAM = "program"
    # The word is text that the program runs, e.g. the argument of `bash -c`.
    RUN_TEXT = "run_text"
    # The word names a file whose text the program runs, e.g. fetch.sh in `bash fetch.sh`.
    RUN_FILE = "run_file"
    # The program shows the content of the file, e.g. cat.
    READ_FILE = "read_file"
    # The program works on the content without showing it, e.g. `tar xzf a.tgz`.
    USED_FILE = "used_file"
    # The program shows only the size or the type of the file, e.g. `ls -l`.
    SIZE_OR_TYPE_FILE = "size_or_type_file"
    # The program writes the file itself, e.g. the value of `-o` of curl.
    WRITTEN_FILE = "written_file"
    # The program adds to the file, e.g. log in `tee -a log`.
    APPENDED_FILE = "appended_file"
    # The part of the word after its last `/` names the file that the program writes, e.g. the argument of `curl -O`.
    WRITTEN_FILE_SOURCE = "written_file_source"
    # The program changes the content and the text does not show the result, e.g. `sed -i`.
    CHANGED_FILE = "changed_file"
    COPY_SOURCE = "copy_source"
    COPY_DESTINATION = "copy_destination"
    DELETED_FILE = "deleted_file"
    # A pattern or a script of the program, e.g. the first argument of grep.
    PATTERN = "pattern"
    # One-letter options written without a dash, e.g. `xzf` in `tar xzf a.tgz`.
    OPTION_CLUSTER = "option_cluster"
    # The name of a variable that gets its value when the text runs, e.g. A in `read A`.
    VARIABLE_NAME_SET_AT_RUN_TIME = "variable_name_set_at_run_time"
    # Neither a file nor text, e.g. the `30` of `timeout 30`.
    OTHER = "other"


# Language of the text that a program runs or that a file extension names, as `code_runners.csv` gives it.
type RanTextLanguage = ShellLanguage | CodeLanguage


class CodeLanguage(StrEnum):
    """Language of a code text."""

    PYTHON = "python"
    JAVASCRIPT = "javascript"  # also TypeScript, e.g. a .ts file run by bun or tsx


@dataclass(frozen=True, slots=True)
class ShellLanguage:
    """Language of a text that a shell runs, e.g. the argument of `bash -c` or a `.sh` file, standing beside the members of `CodeLanguage` in `RanTextLanguage`."""


@dataclass(frozen=True, slots=True)
class UnknownRanTextLanguage:
    """Answer of `ExpandedToolCallKnowledge` for a program or a file extension without a row of `code_runners.csv`."""
