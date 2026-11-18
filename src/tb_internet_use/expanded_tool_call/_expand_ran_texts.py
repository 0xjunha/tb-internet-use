"""Follow every text that the tool calls of one trial ran, from their command strings, script steps and typed input to the files, heredocs and arguments that their commands run, and record each file that a call writes or uses on the way.

A text can sit in a file that an earlier call wrote, e.g. `bash fetch.sh` after a write tool wrote fetch.sh, so the calls are read in order with the content each file has at that moment.
A text that the trial does not hold stays where it would be as an `UnknownRanText`, e.g. setup.sh of the task image, `bash -c "$CMD"` or fetch.sh after `sed -i` changed it.
"""

import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from tb_internet_use.expanded_tool_call._expand_output_routes import PipeReader
from tb_internet_use.expanded_tool_call._expand_poll_links import (
    PollLinks,
    Trajectory,
    trajectory_of,
)
from tb_internet_use.expanded_tool_call._expand_ran_commands import (
    RanCommandsOfShellText,
    expand_ran_commands,
)
from tb_internet_use.expanded_tool_call.judgment_rules import (
    treat_calls_of_other_trajectory_as_not_linked,
    treat_command_under_run_condition_as_run,
    treat_copy_with_two_arguments_as_same_content,
    treat_deleted_file_as_never_written,
    treat_edit_of_text_not_found_once_as_unknown_content,
    treat_extension_of_file_without_interpreter_line_as_its_language,
    treat_file_not_named_by_command_words_as_untouched,
    treat_input_of_key_presses_only_as_no_text,
    treat_last_command_of_starter_as_reader_of_typed_text,
    treat_outer_assignment_as_not_visible_in_new_shell,
    treat_path_that_ends_another_as_same_file,
    treat_path_that_fits_several_written_files_as_unknown_text,
    treat_tool_call_not_marked_not_run_as_maybe_run,
    treat_use_after_later_overwrite_as_use_of_later_write,
    treat_use_of_path_that_fits_several_written_files_as_use_of_each,
)
from tb_internet_use.expanded_tool_call.model import (
    ArgumentText,
    CallCommandText,
    CodeLanguage,
    CodeTextSource,
    FileText,
    FileTextWithoutKnownWriter,
    FileUseKind,
    FileWriteChannel,
    InterpreterLine,
    OutputVisibility,
    PollInputText,
    ProgramBehavior,
    ProgramInvocation,
    ProgramWordRole,
    RanCodeText,
    RanCommand,
    RanShellText,
    RanText,
    RanTextLanguage,
    ScriptStepText,
    ShellLanguage,
    ShellTextSource,
    StdinText,
    UnknownDefaultRunFile,
    UnknownProgramBehavior,
    UnknownProgramInvocation,
    UnknownProgramWordRole,
    UnknownRanText,
    UnknownRanTextLanguage,
    UnknownRanTextReason,
    UnreadableInterpreterLine,
    VariableValues,
)
from tb_internet_use.expanded_tool_call.parse_interpreter_line import (
    parse_interpreter_line,
)
from tb_internet_use.tool_call.model import (
    DeleteFileAction,
    EditFileAction,
    ExecutionStatus,
    FileDestination,
    ParsedShellText,
    PipeDestination,
    PollAction,
    ReadFileAction,
    RunCommandAction,
    SearchFilesAction,
    ShellCommand,
    ToolCall,
    ToolCallAction,
    ToolCallKey,
    UnreadableShellText,
    VariableAssignment,
    WriteFileAction,
    indexed_action_steps_of,
)
from tb_internet_use.tool_call.parse_shell_text import (
    command_substitution_texts_of,
    parse_shell_text,
)

if TYPE_CHECKING:
    # The door is passed in and named in annotations only, so that this module never loads `knowledge/` itself.
    from tb_internet_use.knowledge.expanded_tool_call_knowledge import (
        ExpandedToolCallKnowledge,
    )

# The trajectory of every call when the calls of a trial are read as one trajectory.
_ONE_TRAJECTORY: Trajectory = ("", False)
# Characters that typed input holds when it only presses keys, i.e. space, Enter, Ctrl-C and Ctrl-D.
_KEY_PRESS_CHARACTERS = " \n\x03\x04"
# Characters that make a word a glob or a brace list, which names files that the text does not show.
_GLOB_CHARACTERS = frozenset("*?[{")
# A parameter in braces, e.g. `${D}` or `${D:-x}`, whose `{` starts no brace list.
_PARAMETER_IN_BRACES = re.compile(r"\$\{[^}]*\}")
# The word that stands for stdin or stdout instead of a file, e.g. in `cat - log` or `python -`.
_STDIN_WORD = "-"
# A variable as `$NAME` or `${NAME}`, the forms whose value `VariableValues` can fill.
_PLAIN_VARIABLE = re.compile(r"\$(?:\{(\w+)\}|(\w+))")
# A `$` that starts a variable or a parameter, e.g. `$U`, `${U:-x}`, `$1` or `$@`, as left after the plain variables with one value are filled.
_VARIABLE_OR_PARAMETER_REFERENCE = re.compile(r"\$[A-Za-z_{0-9@*#?!$-]")
# The start of an expansion that bash performs, i.e. a variable or a parameter, `$(...)`, `$((...))` or a backtick.
# A `$` before anything else is a plain character, e.g. in `cost is 5$`.
_EXPANSION_START = r"(?:\$[A-Za-z_{(0-9@*#?!$-]|`)"
# An expansion in the body of a heredoc with an unquoted delimiter, after an even number of backslashes, since a backslash keeps the next `$`, backtick or backslash as is, e.g. in `\$HOME`.
_EXPANSION_IN_UNQUOTED_HEREDOC = re.compile(r"(?<!\\)(?:\\\\)*" + _EXPANSION_START)
# An expansion anywhere in the text of a herestring.
# The text of a herestring has its quotes and escapes removed already, so it no longer shows whether a `$` was single-quoted or escaped, e.g. `$X` for both `'$X'` and `"$X"`.
_EXPANSION_IN_HERESTRING = re.compile(_EXPANSION_START)
# A backslash that bash removes from the body of a heredoc with an unquoted delimiter, before `$`, a backtick or a backslash, or with the line break after it.
_ESCAPE_IN_UNQUOTED_HEREDOC = re.compile(r"\\([$`\\])|\\\n")
# The extension that ends the last part of a path, e.g. `.py` of `./get.py`.
_FILE_EXTENSION_AT_END = re.compile(r"\.\w+$")
# A leading part of a path whose folder the text does not show, i.e. a variable, `~` or `..`.
_UNKNOWN_FOLDER_PART = re.compile(r"^(?:\$|~|\.\.$)")
# The roles of a word that names a file a program writes itself, with whether it adds to the file.
_APPENDS_OF_WRITTEN_FILE_ROLE = {
    ProgramWordRole.WRITTEN_FILE: False,
    ProgramWordRole.APPENDED_FILE: True,
}
# The roles of a word that names a file or a text, after which a program does not read its stdin as that file or text, e.g. `python get.py < input.txt`.
_ROLES_IN_PLACE_OF_STDIN = frozenset(
    {
        ProgramWordRole.RUN_TEXT,
        ProgramWordRole.RUN_FILE,
        ProgramWordRole.READ_FILE,
        ProgramWordRole.USED_FILE,
        ProgramWordRole.SIZE_OR_TYPE_FILE,
    }
)
# The roles of a word that names a file, read for the files that a program gets at run time, e.g. sed in `ls | xargs sed -i s/a/b/`.
_FILE_ROLES = frozenset(
    {
        *_ROLES_IN_PLACE_OF_STDIN - {ProgramWordRole.RUN_TEXT},
        *_APPENDS_OF_WRITTEN_FILE_ROLE,
        ProgramWordRole.WRITTEN_FILE_SOURCE,
        ProgramWordRole.CHANGED_FILE,
        ProgramWordRole.COPY_SOURCE,
        ProgramWordRole.COPY_DESTINATION,
        ProgramWordRole.DELETED_FILE,
    }
)


@dataclass(frozen=True, slots=True)
class RanTextsOfToolCall:
    """Texts and file touches of one tool call, built in call order by `expand_ran_texts` and read by the later pieces of `expand_tool_calls`."""

    tool_call_key: ToolCallKey
    ran_texts: tuple[RanText, ...]
    # In the order the texts, their commands and the words of each command give them.
    file_touches: tuple[FileTouch, ...]


@dataclass(frozen=True, slots=True)
class FileTouch:
    """Touch of one file by one command or by the tool of a call, with the written files it meets as `TrialFileContents` held them at that moment."""

    # The touching command, None for a tool.
    command_id: int | None
    # As written, with each variable of exactly one value filled.
    path: str
    kind: FileTouchKind
    # The way it writes the file, set for `WRITES` and None for the other kinds.
    channel: FileWriteChannel | None
    # For a use or a removal, the written files it meets, empty when no call of the trajectory wrote the file. For a write, the one written file it belongs to.
    written_file_keys: tuple[WrittenFileKey, ...]
    # The path of a use fits several written files and the use belongs to one of them.
    fits_several_written_files: bool
    # For a use, the earlier calls of the trajectory whose result has the path as its `output_path`, in call order, so `expand_output_places` knows whose output the read shows. Empty for the other kinds and when the path is no such `output_path`.
    harness_output_file_tool_call_keys: tuple[ToolCallKey, ...]

    @property
    def reads_harness_output_file(self) -> bool:
        """Tell whether the path is the `output_path` of the result of an earlier call of the trajectory."""
        return bool(self.harness_output_file_tool_call_keys)


class FileTouchKind(StrEnum):
    """Kind of touch that a command or a tool makes of a file."""

    SHOWS_CONTENT = "shows_content"
    USES_CONTENT = "uses_content"
    SHOWS_SIZE_OR_TYPE = "shows_size_or_type"
    # A program that no fact covers, or an unread word, names a written file, so its content becomes unknown.
    UNKNOWN_USE = "unknown_use"
    WRITES = "writes"
    DELETES = "deletes"


# The kind of use of each role of a word that names a file a program reads.
_FILE_TOUCH_KIND_OF_USE_ROLE = {
    ProgramWordRole.READ_FILE: FileTouchKind.SHOWS_CONTENT,
    ProgramWordRole.USED_FILE: FileTouchKind.USES_CONTENT,
    ProgramWordRole.SIZE_OR_TYPE_FILE: FileTouchKind.SHOWS_SIZE_OR_TYPE,
}
# The kind of use of each kind of touch that uses a file without writing or removing it, read by the pieces that list uses.
FILE_USE_KIND_OF_FILE_TOUCH_KIND = {
    FileTouchKind.SHOWS_CONTENT: FileUseKind.SHOWS_CONTENT,
    FileTouchKind.USES_CONTENT: FileUseKind.USES_CONTENT,
    FileTouchKind.SHOWS_SIZE_OR_TYPE: FileUseKind.SHOWS_SIZE_OR_TYPE,
    FileTouchKind.UNKNOWN_USE: FileUseKind.UNKNOWN,
}


@dataclass(frozen=True, slots=True)
class WrittenFileKey:
    """Key of one `WrittenFile`, i.e. the call that holds it and its path."""

    tool_call_key: ToolCallKey
    # As the first write of the call names it.
    path: str


@dataclass(frozen=True, slots=True)
class LatestFileText:
    """Answer of `TrialFileContents` about the text of a file that a command runs."""

    # The last write of each file the path fits. Empty when no call wrote it, several when the path fits several files.
    written_file_keys: tuple[WrittenFileKey, ...]
    # None unless exactly one write fits and its content is known.
    content: str | None


def expand_ran_texts(
    tool_calls: Sequence[ToolCall],
    poll_links: PollLinks,
    *,
    knowledge: ExpandedToolCallKnowledge,
    judgment_rule_use_counts: Counter[str],
) -> tuple[RanTextsOfToolCall, ...]:
    """Follow the texts that each tool call of a trial ran and record the file touches of each, one result per call in the order of `tool_calls`.

    The calls of one trajectory share the files they write, e.g. main or one subagent, so each trajectory keeps its own `TrialFileContents`.
    A run or use of a path that only a write of another trajectory fits asks `treat_calls_of_other_trajectory_as_not_linked` once all calls are read, since the trajectories do not say how their calls interleave.
    When the rule says to link one, the calls are read again as one trajectory.
    The counts of the door and of the rules then keep only the second reading, so each command counts once.
    A poll's typed text goes to the call that started the polled handle, as `poll_links` gives it.
    Every use of a rule of `judgment_rules.py` adds one to `judgment_rule_use_counts`.
    """
    row_use_counts_before_reading = Counter(knowledge.uses.row_use_counts)
    unknown_input_counts_before_reading = Counter(knowledge.uses.unknown_input_counts)
    reading_use_counts: Counter[str] = Counter()
    ran_texts_of_tool_calls, trial_file_contents_of_trajectory = (
        _expand_ran_texts_in_call_order(
            tool_calls,
            poll_links,
            trajectory_of,
            knowledge=knowledge,
            judgment_rule_use_counts=reading_use_counts,
        )
    )
    if not _is_each_link_to_other_trajectory_left_unmade(
        tool_calls,
        ran_texts_of_tool_calls,
        trial_file_contents_of_trajectory,
        judgment_rule_use_counts=judgment_rule_use_counts,
    ):
        reading_use_counts = Counter()
        knowledge.uses.row_use_counts.clear()
        knowledge.uses.row_use_counts.update(row_use_counts_before_reading)
        knowledge.uses.unknown_input_counts.clear()
        knowledge.uses.unknown_input_counts.update(unknown_input_counts_before_reading)
        ran_texts_of_tool_calls, _ = _expand_ran_texts_in_call_order(
            tool_calls,
            poll_links,
            lambda _: _ONE_TRAJECTORY,
            knowledge=knowledge,
            judgment_rule_use_counts=reading_use_counts,
        )
    judgment_rule_use_counts.update(reading_use_counts)
    return ran_texts_of_tool_calls


def _expand_ran_texts_in_call_order(
    tool_calls: Sequence[ToolCall],
    poll_links: PollLinks,
    trajectory_for: Callable[[ToolCall], Trajectory],
    *,
    knowledge: ExpandedToolCallKnowledge,
    judgment_rule_use_counts: Counter[str],
) -> tuple[tuple[RanTextsOfToolCall, ...], dict[Trajectory, TrialFileContents]]:
    """Follow the texts of the calls in order with one `TrialFileContents` per trajectory that `trajectory_for` gives, and give those contents with the results."""
    trial_file_contents_of_trajectory: dict[Trajectory, TrialFileContents] = {}
    typed_text_readers_by_tool_call_key: dict[ToolCallKey, _TypedTextReader | None] = {}
    ran_texts_of_tool_calls: list[RanTextsOfToolCall] = []
    for tool_call in tool_calls:
        trial_file_contents = trial_file_contents_of_trajectory.setdefault(
            trajectory_for(tool_call),
            TrialFileContents(judgment_rule_use_counts=judgment_rule_use_counts),
        )
        ran_texts_of_tool_call, typed_text_reader = _expand_ran_texts_of_tool_call(
            tool_call,
            poll_links.starter_tool_call_keys_of_poll,
            typed_text_readers_by_tool_call_key,
            trial_file_contents,
            knowledge=knowledge,
            judgment_rule_use_counts=judgment_rule_use_counts,
        )
        typed_text_readers_by_tool_call_key[tool_call.harness_tool_call.key] = (
            typed_text_reader
        )
        if tool_call.result is not None and tool_call.result.output_path is not None:
            trial_file_contents.record_harness_output_file(
                tool_call.result.output_path, tool_call.harness_tool_call.key
            )
        ran_texts_of_tool_calls.append(ran_texts_of_tool_call)
    return tuple(ran_texts_of_tool_calls), trial_file_contents_of_trajectory


def _is_each_link_to_other_trajectory_left_unmade(
    tool_calls: Sequence[ToolCall],
    ran_texts_of_tool_calls: Sequence[RanTextsOfToolCall],
    trial_file_contents_of_trajectory: Mapping[Trajectory, TrialFileContents],
    *,
    judgment_rule_use_counts: Counter[str],
) -> bool:
    """Ask `treat_calls_of_other_trajectory_as_not_linked` for each run or use of a path that no write of its own trajectory fits and a write of another trajectory does, wherever that write sits in the trial, and tell whether every answer leaves the link unmade.

    Such a run is an `UnknownRanText` with the reason `NOT_WRITTEN_IN_TRIAL`, e.g. `bash f.sh` in main after a subagent wrote f.sh, and such a use is a `FileTouch` without written files that reads no harness output file.
    A run records a use of its file too, so the rule is asked once for each command and path.
    """
    is_each_left_unmade = True
    for tool_call, ran_texts_of_tool_call in zip(
        tool_calls, ran_texts_of_tool_calls, strict=True
    ):
        trajectory = trajectory_of(tool_call)
        command_ids_and_paths = [
            (ran_text.source.runner_command_id, ran_text.source.path)
            for ran_text in ran_texts_of_tool_call.ran_texts
            if isinstance(ran_text, UnknownRanText)
            and ran_text.reason == UnknownRanTextReason.NOT_WRITTEN_IN_TRIAL
            and isinstance(ran_text.source, FileTextWithoutKnownWriter)
            and ran_text.source.path is not None
        ] + [
            (file_touch.command_id, file_touch.path)
            for file_touch in ran_texts_of_tool_call.file_touches
            if file_touch.kind in FILE_USE_KIND_OF_FILE_TOUCH_KIND
            and not file_touch.written_file_keys
            and not file_touch.reads_harness_output_file
        ]
        own_trial_file_contents = trial_file_contents_of_trajectory[trajectory]
        for _, path in dict.fromkeys(command_ids_and_paths):
            if (
                not own_trial_file_contents.has_written_file_fitting(path)
                and any(
                    other_trajectory != trajectory
                    and other_trial_file_contents.has_written_file_fitting(path)
                    for other_trajectory, other_trial_file_contents in trial_file_contents_of_trajectory.items()
                )
                and not treat_calls_of_other_trajectory_as_not_linked(
                    use_counts=judgment_rule_use_counts
                )
            ):
                is_each_left_unmade = False
    return is_each_left_unmade


@dataclass(frozen=True, slots=True)
class _TypedTextReader:
    """Program of a call that reads what a later poll types, i.e. the innermost program of the last command of the last text the call holds itself, kept by `expand_ran_texts` for the polls of later calls."""

    program_invocation: ProgramInvocation | UnknownProgramInvocation
    program_behavior: ProgramBehavior | UnknownProgramBehavior
    # A word of the command names a file or a text that the program reads instead of its stdin, e.g. install.sh of `bash install.sh`, so typed text may be an answer and not a text that runs.
    has_word_in_place_of_stdin: bool


@dataclass(slots=True)
class _ToolCallState:
    """State kept while `_expand_ran_texts_of_tool_call` reads one call, shared by the pieces that follow its texts."""

    tool_call_key: ToolCallKey
    trial_file_contents: TrialFileContents
    # False for a call whose result is `NOT_RUN`, whose writes do not change the files and whose uses are not recorded.
    may_have_run: bool
    knowledge: ExpandedToolCallKnowledge
    judgment_rule_use_counts: Counter[str]
    # The id that the first command of the next text added from a file, an argument, stdin or a poll gets, so ids stay unique within the call.
    next_command_id: int
    ran_texts: list[RanText] = field(default_factory=list)
    file_touches: list[FileTouch] = field(default_factory=list)


def _expand_ran_texts_of_tool_call(
    tool_call: ToolCall,
    starter_tool_call_keys_of_poll: Mapping[
        tuple[ToolCallKey, int | None], tuple[ToolCallKey, ...]
    ],
    typed_text_readers_by_tool_call_key: Mapping[ToolCallKey, _TypedTextReader | None],
    trial_file_contents: TrialFileContents,
    *,
    knowledge: ExpandedToolCallKnowledge,
    judgment_rule_use_counts: Counter[str],
) -> tuple[RanTextsOfToolCall, _TypedTextReader | None]:
    """Follow all texts of one call, starting from its command string, its script steps and the input its polls type, and record the files its tools write, remove and read.

    It also gives the program that reads what a later poll types into a handle this call started, None when the call's last text has no command or could not be read.
    """
    tool_call_key = tool_call.harness_tool_call.key
    tool_call_state = _ToolCallState(
        tool_call_key,
        trial_file_contents,
        _may_have_run(tool_call, judgment_rule_use_counts=judgment_rule_use_counts),
        knowledge,
        judgment_rule_use_counts,
        _first_added_command_id_of(tool_call.action),
    )
    last_ran_commands_of_shell_text: RanCommandsOfShellText | None = None
    for step_index, step in indexed_action_steps_of(tool_call.action):
        if isinstance(step, RunCommandAction):
            last_ran_commands_of_shell_text = _expand_ran_texts_of_own_shell_text(
                tool_call_state,
                CallCommandText() if step_index is None else ScriptStepText(step_index),
                step.parsed_shell_text,
            )
        elif isinstance(step, PollAction):
            _expand_ran_text_of_typed_text(
                tool_call_state,
                step,
                step_index,
                starter_tool_call_keys_of_poll[(tool_call_key, step_index)],
                typed_text_readers_by_tool_call_key,
            )
        else:
            _record_file_touches_of_tool(tool_call_state, step)
    return (
        RanTextsOfToolCall(
            tool_call_key,
            tuple(tool_call_state.ran_texts),
            tuple(tool_call_state.file_touches),
        ),
        None
        if last_ran_commands_of_shell_text is None
        else _typed_text_reader_from(last_ran_commands_of_shell_text),
    )


def _may_have_run(
    tool_call: ToolCall, *, judgment_rule_use_counts: Counter[str]
) -> bool:
    """Tell whether the tool may have run a call, i.e. whether its result is anything but `NOT_RUN`, asking a rule when there is no result or its status is `UNKNOWN`."""
    if tool_call.result is None or (
        tool_call.result.execution_status == ExecutionStatus.UNKNOWN
    ):
        return treat_tool_call_not_marked_not_run_as_maybe_run(
            use_counts=judgment_rule_use_counts
        )
    return tool_call.result.execution_status != ExecutionStatus.NOT_RUN


def _first_added_command_id_of(action: ToolCallAction) -> int:
    """Give the id after the largest command id of the call's own texts, i.e. its command string or all of its script steps, 0 when they have no command."""
    command_ids = [
        shell_command.id
        for _, step in indexed_action_steps_of(action)
        if isinstance(step, RunCommandAction)
        and isinstance(step.parsed_shell_text, ParsedShellText)
        for shell_command in step.parsed_shell_text.commands
    ]
    return max(command_ids, default=-1) + 1


def _expand_ran_texts_of_own_shell_text(
    tool_call_state: _ToolCallState,
    source: CallCommandText | ScriptStepText,
    parsed_shell_text: ParsedShellText | UnreadableShellText | None,
) -> RanCommandsOfShellText | None:
    """Follow a command string of the call as `convert_tool_calls` split it, and give what `expand_ran_commands` read from it, None when the trajectory lacks the text or it could not be read."""
    if parsed_shell_text is None:
        tool_call_state.ran_texts.append(
            UnknownRanText(source, UnknownRanTextReason.MISSING_FROM_TRAJECTORY)
        )
        return None
    return _expand_ran_shell_text(
        tool_call_state,
        source,
        parsed_shell_text,
        outer_variable_assignments=(),
        runner_command_reading=None,
        running_written_file_keys=(),
        command_substitution_texts=frozenset(),
    )


def _typed_text_reader_from(
    ran_commands_of_shell_text: RanCommandsOfShellText,
) -> _TypedTextReader | None:
    """Give the innermost program of the last command of a text as the reader of what a later poll types, None when the text has no command."""
    if (
        not ran_commands_of_shell_text.ran_commands
        or not ran_commands_of_shell_text.ran_commands[-1].program_invocations
    ):
        return None
    last_ran_command = ran_commands_of_shell_text.ran_commands[-1]
    return _TypedTextReader(
        last_ran_command.program_invocations[-1],
        ran_commands_of_shell_text.program_behaviors_of_commands[-1][-1],
        _has_word_in_place_of_stdin(
            last_ran_command.shell_command.words,
            ran_commands_of_shell_text.word_roles_of_commands[-1],
        ),
    )


def _expand_ran_text_of_typed_text(
    tool_call_state: _ToolCallState,
    poll_action: PollAction,
    step_index: int | None,
    starter_tool_call_keys: Sequence[ToolCallKey],
    typed_text_readers_by_tool_call_key: Mapping[ToolCallKey, _TypedTextReader | None],
) -> None:
    """Follow the text that a poll types into a command or script started earlier, as the program that reads it runs it.

    The poll has one starting call when every polled handle that an earlier call started was started by the same call.
    Text typed into a program whose row gives its stdin a role other than `RUN_TEXT`, e.g. `cat > notes.txt`, ran nothing and adds no text.
    A program that runs a file or a text that its words name does not run its stdin, e.g. `bash install.sh`, so text typed into it may only answer a prompt of that file and its language is not known.
    """
    typed_text = poll_action.input
    if typed_text is None:
        return
    judgment_rule_use_counts = tool_call_state.judgment_rule_use_counts
    if not typed_text.strip(_KEY_PRESS_CHARACTERS) and (
        treat_input_of_key_presses_only_as_no_text(
            typed_text, use_counts=judgment_rule_use_counts
        )
    ):
        return
    distinct_starter_tool_call_keys = tuple(dict.fromkeys(starter_tool_call_keys))
    starter_tool_call_key = (
        distinct_starter_tool_call_keys[0]
        if len(distinct_starter_tool_call_keys) == 1
        else None
    )
    source = PollInputText(step_index, starter_tool_call_key)
    typed_text_reader = None
    if starter_tool_call_key is not None and (
        treat_last_command_of_starter_as_reader_of_typed_text(
            use_counts=judgment_rule_use_counts
        )
    ):
        typed_text_reader = typed_text_readers_by_tool_call_key[starter_tool_call_key]
    if (
        typed_text_reader is None
        or not isinstance(typed_text_reader.program_behavior, ProgramBehavior)
        or typed_text_reader.has_word_in_place_of_stdin
    ):
        tool_call_state.ran_texts.append(
            UnknownRanText(source, UnknownRanTextReason.LANGUAGE_NOT_KNOWN)
        )
        return
    stdin_role = typed_text_reader.program_behavior.stdin_role
    if isinstance(stdin_role, UnknownProgramWordRole):
        tool_call_state.ran_texts.append(
            UnknownRanText(source, UnknownRanTextReason.LANGUAGE_NOT_KNOWN)
        )
    elif stdin_role == ProgramWordRole.RUN_TEXT:
        _expand_ran_text_of_language(
            tool_call_state,
            source,
            typed_text,
            tool_call_state.knowledge.ran_text_language_of_program(
                typed_text_reader.program_invocation.program_name
            ),
            lambda: _NO_SHELL_TEXT_START_STATE,
            runner_command_reading=None,
            running_written_file_keys=(),
            command_substitution_texts=frozenset(),
        )


def _record_file_touches_of_tool(
    tool_call_state: _ToolCallState, tool_call_action: ToolCallAction
) -> None:
    """Record the file that a write, edit, delete, read or content search tool writes, removes or reads, as a touch without a command."""
    trial_file_contents = tool_call_state.trial_file_contents
    file_touches: list[FileTouch | None] = []
    if isinstance(tool_call_action, WriteFileAction) and tool_call_action.path:
        file_touches.append(
            trial_file_contents.record_write(
                tool_call_state.tool_call_key,
                None,
                tool_call_action.path,
                FileWriteChannel.TOOL_ARGUMENT,
                tool_call_action.content,
                appends=False,
                may_have_run=tool_call_state.may_have_run,
                may_be_glob=False,
            )
        )
    elif isinstance(tool_call_action, EditFileAction) and tool_call_action.path:
        file_touches.append(
            trial_file_contents.record_write(
                tool_call_state.tool_call_key,
                None,
                tool_call_action.path,
                FileWriteChannel.TOOL_ARGUMENT,
                _content_after_edit_of(
                    tool_call_action,
                    trial_file_contents.file_text(tool_call_action.path),
                    judgment_rule_use_counts=tool_call_state.judgment_rule_use_counts,
                ),
                appends=False,
                may_have_run=tool_call_state.may_have_run,
                may_be_glob=False,
            )
        )
    elif not tool_call_state.may_have_run:
        return
    elif isinstance(tool_call_action, DeleteFileAction) and tool_call_action.path:
        file_touches.append(
            trial_file_contents.record_deletion(
                None, tool_call_action.path, may_be_glob=False
            )
        )
    elif isinstance(tool_call_action, ReadFileAction) and tool_call_action.path:
        file_touches.append(
            trial_file_contents.record_use(
                None,
                tool_call_action.path,
                FileTouchKind.SHOWS_CONTENT,
                may_be_glob=False,
            )
        )
    elif isinstance(tool_call_action, SearchFilesAction):
        file_touches += [
            trial_file_contents.record_use(
                None, path, FileTouchKind.SHOWS_CONTENT, may_be_glob=False
            )
            for path in tool_call_action.paths
        ]
    tool_call_state.file_touches += [
        file_touch for file_touch in file_touches if file_touch is not None
    ]


def _content_after_edit_of(
    edit_file_action: EditFileAction,
    latest_file_text: LatestFileText,
    *,
    judgment_rule_use_counts: Counter[str],
) -> str | None:
    """Apply an edit to the known content of its file, None when the trial does not hold the content, the text the edit replaces or its new text, or when a rule reads the edit as unknown."""
    old_text = edit_file_action.old
    new_text = edit_file_action.new
    content = latest_file_text.content
    if content is None or old_text is None or new_text is None:
        return None
    if content.count(old_text) != 1 and (
        treat_edit_of_text_not_found_once_as_unknown_content(
            edit_file_action.path or "", use_counts=judgment_rule_use_counts
        )
    ):
        return None
    return content.replace(old_text, new_text, 1)


def _expand_ran_shell_text(
    tool_call_state: _ToolCallState,
    source: ShellTextSource,
    parsed_shell_text: ParsedShellText | UnreadableShellText,
    *,
    outer_variable_assignments: Sequence[VariableAssignment],
    runner_command_reading: _CommandReading | None,
    running_written_file_keys: tuple[WrittenFileKey, ...],
    command_substitution_texts: frozenset[str],
) -> RanCommandsOfShellText | None:
    """Add one shell text with its commands to the call's texts, then record the file touches of each command and follow the texts it runs, in the order of the commands.

    `outer_variable_assignments` are the assignments of the text that runs this one in the calling shell, e.g. by `eval`.
    `runner_command_reading` is the command that runs the text, None for a text of the call itself or typed into a running program. The output of the text's commands can lead to the pipe readers of the runner's text, e.g. tail in `bash fetch.sh | tail -1`.
    `running_written_file_keys` are the written files that the call is following around this text, so that a file that runs itself is not followed again.
    `command_substitution_texts` are the `$(...)` texts that an outer shell ran before this text, passed again to the texts that its commands run.
    It gives what `expand_ran_commands` read, None for a text that could not be read, which is an `UnknownRanText` with the reason `UNREADABLE_SHELL_TEXT`.
    """
    if isinstance(parsed_shell_text, UnreadableShellText):
        tool_call_state.ran_texts.append(
            UnknownRanText(source, UnknownRanTextReason.UNREADABLE_SHELL_TEXT)
        )
        return None
    ran_commands_of_shell_text = expand_ran_commands(
        parsed_shell_text,
        outer_variable_assignments=outer_variable_assignments,
        outer_pipe_readers_by_command_id={}
        if runner_command_reading is None
        else runner_command_reading.pipe_readers_by_command_id,
        knowledge=tool_call_state.knowledge,
        judgment_rule_use_counts=tool_call_state.judgment_rule_use_counts,
    )
    tool_call_state.ran_texts.append(
        RanShellText(source, ran_commands_of_shell_text.ran_commands)
    )
    pipe_reader_command_ids = frozenset(
        output_destination.reader_id
        for shell_command in parsed_shell_text.commands
        for output_destination in (shell_command.stdout, shell_command.stderr)
        if isinstance(output_destination, PipeDestination)
    )
    for ran_command, word_roles, program_behaviors, program_word_indexes in zip(
        ran_commands_of_shell_text.ran_commands,
        ran_commands_of_shell_text.word_roles_of_commands,
        ran_commands_of_shell_text.program_behaviors_of_commands,
        ran_commands_of_shell_text.program_word_indexes_of_commands,
        strict=True,
    ):
        command_reading = _CommandReading(
            ran_command,
            word_roles,
            program_behaviors,
            program_word_indexes,
            ran_commands_of_shell_text.pipe_readers_by_command_id,
            reads_pipe=ran_command.shell_command.id in pipe_reader_command_ids,
        )
        _record_file_touches_of_command(tool_call_state, command_reading)
        _expand_ran_texts_of_command(
            tool_call_state,
            command_reading,
            ran_commands_of_shell_text.variable_assignments,
            running_written_file_keys=running_written_file_keys,
            command_substitution_texts=command_substitution_texts,
        )
    return ran_commands_of_shell_text


@dataclass(frozen=True, slots=True)
class _CommandReading:
    """Command of a shell text with the roles of its words and the rows of its programs, as `expand_ran_commands` read them, passed to the pieces that record its file touches and follow its texts."""

    ran_command: RanCommand
    word_roles: tuple[ProgramWordRole | UnknownProgramWordRole | None, ...]
    program_behaviors: tuple[ProgramBehavior | UnknownProgramBehavior, ...]
    # The 0-based index in `ShellCommand.words` of the word of each program, at the index of the program.
    program_word_indexes: tuple[int, ...]
    # The pipe readers of its text and of the texts around it, which the output of a text it runs can lead to.
    pipe_readers_by_command_id: Mapping[int, PipeReader]
    # A command of the same text sends its stdout or stderr to this command through a pipe.
    reads_pipe: bool

    @property
    def shell_command(self) -> ShellCommand:
        return self.ran_command.shell_command

    def word_indexes_for_role(self, role: ProgramWordRole) -> list[int]:
        """List the 0-based indexes of the words with a role, in word order."""
        return [
            word_index
            for word_index, word_role in enumerate(self.word_roles)
            if word_role == role
        ]

    def filled_word_for(self, word_index: int) -> str:
        """Give the word at a 0-based index with each variable of exactly one value filled, e.g. fetch.sh for `$F` after `F=fetch.sh`, only for a word that holds an expansion."""
        word = self.shell_command.words[word_index]
        if word_index not in self.shell_command.expansion_word_indexes:
            return word
        return _text_with_variable_values_of(word, self.ran_command.variable_values)

    def program_index_for_word(self, word: str) -> int:
        """Give the 0-based index of the innermost program whose arguments or option values hold a word, e.g. bash for `curl u` in `sudo bash -c 'curl u'`, else that of the innermost program."""
        program_invocations = self.ran_command.program_invocations
        for program_index in reversed(range(len(program_invocations))):
            program_invocation = program_invocations[program_index]
            if isinstance(program_invocation, ProgramInvocation) and (
                word in program_invocation.arguments
                or any(
                    program_option.value == word
                    for program_option in program_invocation.options
                )
            ):
                return program_index
        return len(program_invocations) - 1


def _record_file_touches_of_command(
    tool_call_state: _ToolCallState, command_reading: _CommandReading
) -> None:
    """Record the files that the words of a command read, write, change, copy or remove, and the files its output routes end in, in word order and then route order.

    A file that the command runs is recorded where its text is followed, and its stdin where that is read.
    A word with the role `METADATA_CHANGED_FILE` records no touch, since its program leaves the content as it was, e.g. f.sh of `chmod +x f.sh`.
    A command of a call that did not run records only its writes, since they say what the text writes.
    """
    shell_command = command_reading.shell_command
    may_have_run = tool_call_state.may_have_run
    trial_file_contents = tool_call_state.trial_file_contents
    copy_paths: list[tuple[ProgramWordRole, str]] = []
    for word_index, word_role in enumerate(command_reading.word_roles):
        if word_role is None or shell_command.words[word_index] == _STDIN_WORD:
            continue
        path = command_reading.filled_word_for(word_index)
        if isinstance(word_role, UnknownProgramWordRole):
            if may_have_run:
                _add_unknown_use(tool_call_state, shell_command, path)
        elif word_role in _FILE_TOUCH_KIND_OF_USE_ROLE:
            if may_have_run and _may_touch_files(tool_call_state, shell_command):
                _add_file_touch(
                    tool_call_state,
                    trial_file_contents.record_use(
                        shell_command.id,
                        path,
                        _FILE_TOUCH_KIND_OF_USE_ROLE[word_role],
                        may_be_glob=True,
                    ),
                )
        elif word_role in _APPENDS_OF_WRITTEN_FILE_ROLE:
            _record_write_of_written_file_word(
                tool_call_state, command_reading, path, word_role
            )
        elif word_role == ProgramWordRole.WRITTEN_FILE_SOURCE:
            file_name = path.rsplit("/", 1)[-1]
            if file_name:
                _record_write_of_own_output_file(
                    tool_call_state, shell_command, file_name
                )
        elif word_role == ProgramWordRole.CHANGED_FILE:
            _record_write_of_own_output_file(tool_call_state, shell_command, path)
        elif word_role in (
            ProgramWordRole.COPY_SOURCE,
            ProgramWordRole.COPY_DESTINATION,
        ):
            copy_paths.append((word_role, path))
        elif (
            word_role == ProgramWordRole.DELETED_FILE
            and may_have_run
            and _may_touch_files(tool_call_state, shell_command)
        ):
            _add_file_touch(
                tool_call_state,
                trial_file_contents.record_deletion(
                    shell_command.id, path, may_be_glob=True
                ),
            )
    if [word_role for word_role, _ in copy_paths] == [
        ProgramWordRole.COPY_SOURCE,
        ProgramWordRole.COPY_DESTINATION,
    ] and _may_touch_files(tool_call_state, shell_command):
        (_, source_path), (_, destination_path) = copy_paths
        _add_file_touch(
            tool_call_state,
            trial_file_contents.record_copy(
                tool_call_state.tool_call_key,
                shell_command.id,
                source_path,
                destination_path,
                may_have_run=may_have_run,
            ),
        )
    _count_programs_that_touch_files_given_at_run_time(
        command_reading,
        judgment_rule_use_counts=tool_call_state.judgment_rule_use_counts,
    )
    _record_writes_of_output_routes(tool_call_state, command_reading)


def _may_touch_files(
    tool_call_state: _ToolCallState, shell_command: ShellCommand
) -> bool:
    """Tell whether the file touches of a command are recorded, asking a rule when the command runs only under a condition, e.g. after `test -f x &&`."""
    if not (
        shell_command.runs_if
        or shell_command.in_function_body
        or shell_command.in_case_branch
    ):
        return True
    return treat_command_under_run_condition_as_run(
        use_counts=tool_call_state.judgment_rule_use_counts
    )


def _add_file_touch(
    tool_call_state: _ToolCallState, file_touch: FileTouch | None
) -> None:
    """Add a file touch to those of the call, unless a rule left it out."""
    if file_touch is not None:
        tool_call_state.file_touches.append(file_touch)


def _add_unknown_use(
    tool_call_state: _ToolCallState, shell_command: ShellCommand, path: str
) -> None:
    """Record a word whose role is unknown as a use of unknown kind when it names a written file, e.g. f.sh of `mytool f.sh`, which leaves the content of that file unknown.

    Such a word is mostly no file at all, e.g. a URL, so a word that names no written file adds no touch, and the rule about run conditions is asked only for a word that does.
    """
    file_touch = tool_call_state.trial_file_contents.record_use(
        shell_command.id, path, FileTouchKind.UNKNOWN_USE, may_be_glob=True
    )
    if (
        file_touch is not None
        and file_touch.written_file_keys
        and _may_touch_files(tool_call_state, shell_command)
    ):
        tool_call_state.file_touches.append(file_touch)


def _record_write_of_own_output_file(
    tool_call_state: _ToolCallState, shell_command: ShellCommand, path: str
) -> None:
    """Record a file that a program writes or changes itself with content that the text does not show, e.g. f.sh of `sed -i s/a/b/ f.sh`."""
    if _may_touch_files(tool_call_state, shell_command):
        _add_file_touch(
            tool_call_state,
            tool_call_state.trial_file_contents.record_write(
                tool_call_state.tool_call_key,
                shell_command.id,
                path,
                FileWriteChannel.OWN_OUTPUT_FILE,
                None,
                appends=False,
                may_have_run=tool_call_state.may_have_run,
                may_be_glob=True,
            ),
        )


def _record_write_of_written_file_word(
    tool_call_state: _ToolCallState,
    command_reading: _CommandReading,
    path: str,
    word_role: ProgramWordRole,
) -> None:
    """Record the file that a word with the role `WRITTEN_FILE` or `APPENDED_FILE` names, e.g. a.tgz of `curl -o a.tgz u` or log of `tee log`.

    A program whose row says that it passes on all piped input writes that input, so its channel is `STDOUT`, e.g. tee, and its content is the heredoc it gets when nothing else changes it.
    When such a program reads a pipe, the output routes of the commands before it end in the file and record the write instead, e.g. curl writes log in `curl u | tee log`.
    """
    shell_command = command_reading.shell_command
    is_passing_on_all_piped_input = _is_passing_on_all_piped_input(command_reading)
    if (
        is_passing_on_all_piped_input and command_reading.reads_pipe
    ) or not _may_touch_files(tool_call_state, shell_command):
        return
    appends = _APPENDS_OF_WRITTEN_FILE_ROLE[word_role]
    _add_file_touch(
        tool_call_state,
        tool_call_state.trial_file_contents.record_write(
            tool_call_state.tool_call_key,
            shell_command.id,
            path,
            FileWriteChannel.STDOUT
            if is_passing_on_all_piped_input
            else FileWriteChannel.OWN_OUTPUT_FILE,
            None
            if appends or not is_passing_on_all_piped_input
            else _stdin_text_passed_on_whole_of(command_reading),
            appends=appends,
            may_have_run=tool_call_state.may_have_run,
            may_be_glob=True,
        ),
    )


def _is_passing_on_all_piped_input(command_reading: _CommandReading) -> bool:
    """Tell whether the row of a command's innermost program says that it passes on all piped input, e.g. cat or tee."""
    if not command_reading.program_behaviors:
        return False
    innermost_program_behavior = command_reading.program_behaviors[-1]
    return (
        isinstance(innermost_program_behavior, ProgramBehavior)
        and innermost_program_behavior.visibility_of_piped_input
        == OutputVisibility.WHOLE
    )


def _stdin_text_passed_on_whole_of(command_reading: _CommandReading) -> str | None:
    """Give the heredoc or herestring that a command's only program passes on unchanged, e.g. the heredoc of `cat > f <<EOF` or `tee f <<EOF`, else None.

    That holds when the row of the program says that it passes on all piped input, it has no options, and each of its words is `-` or a file it writes, so it reads only its stdin.
    """
    shell_command = command_reading.shell_command
    program_invocations = command_reading.ran_command.program_invocations
    if (
        shell_command.stdin_text is None
        or len(program_invocations) != 1
        or not _is_passing_on_all_piped_input(command_reading)
    ):
        return None
    (program_invocation,) = program_invocations
    if not isinstance(program_invocation, ProgramInvocation) or (
        program_invocation.options or program_invocation.unread_words
    ):
        return None
    if all(
        word_role is None
        or word == _STDIN_WORD
        or word_role in _APPENDS_OF_WRITTEN_FILE_ROLE
        for word, word_role in zip(
            shell_command.words, command_reading.word_roles, strict=True
        )
    ):
        return _stdin_text_read_by_program_of(shell_command)
    return None


def _stdin_text_read_by_program_of(shell_command: ShellCommand) -> str | None:
    """Give the heredoc or herestring of a command as its program reads it, or None when bash builds it at run time.

    Bash expands the body of a heredoc whose delimiter is unquoted before the program reads it.
    So a body with an expansion is built at run time, e.g. `$(curl u)` or `$HOME` under `<<EOF`, and a body without one loses the backslashes that escape, e.g. `\\$HOME` is read as `$HOME`.
    A body under a quoted delimiter, e.g. `<<'EOF'`, is read as written.
    Bash expands the word of a herestring too unless it is single-quoted, e.g. `<<< "curl $(cat u.txt)"`.
    Its text no longer shows the quotes, so the text of a herestring with an expansion in it is not known, e.g. `$X` comes from both `'$X'` and `"$X"`.
    """
    stdin_text = shell_command.stdin_text
    if stdin_text is None or shell_command.is_heredoc_delimiter_quoted is True:
        return stdin_text
    if shell_command.is_heredoc_delimiter_quoted is None:
        return None if _EXPANSION_IN_HERESTRING.search(stdin_text) else stdin_text
    if _EXPANSION_IN_UNQUOTED_HEREDOC.search(stdin_text):
        return None
    return _ESCAPE_IN_UNQUOTED_HEREDOC.sub(
        lambda match: match.group(1) or "", stdin_text
    )


def _count_programs_that_touch_files_given_at_run_time(
    command_reading: _CommandReading, *, judgment_rule_use_counts: Counter[str]
) -> None:
    """Ask a rule for each program of a command that gets arguments at run time and whose row gives its arguments a file role, e.g. sed in `ls | xargs sed -i s/a/b/`, whose files the text does not name."""
    for program_invocation, program_behavior in zip(
        command_reading.ran_command.program_invocations,
        command_reading.program_behaviors,
        strict=True,
    ):
        if (
            isinstance(program_invocation, ProgramInvocation)
            and isinstance(program_behavior, ProgramBehavior)
            and program_invocation.gets_more_arguments_at_run_time
            and program_behavior.argument_role in _FILE_ROLES
        ):
            treat_file_not_named_by_command_words_as_untouched(
                program_invocation.program_name, use_counts=judgment_rule_use_counts
            )


def _record_writes_of_output_routes(
    tool_call_state: _ToolCallState, command_reading: _CommandReading
) -> None:
    """Record the file that each stdout or stderr route of a command ends in, e.g. log for `curl u > log` or for curl in `curl u | tee log`, as written by that command."""
    ran_command = command_reading.ran_command
    shell_command = ran_command.shell_command
    for output_routes, channel in (
        (ran_command.stdout_routes, FileWriteChannel.STDOUT),
        (ran_command.stderr_routes, FileWriteChannel.STDERR),
    ):
        for output_route in output_routes:
            file_destination = output_route.end
            if not isinstance(file_destination, FileDestination) or not (
                _may_touch_files(tool_call_state, shell_command)
            ):
                continue
            passes_on_stdin_text = (
                channel == FileWriteChannel.STDOUT
                and not output_route.pipe_reader_command_ids
            )
            _add_file_touch(
                tool_call_state,
                tool_call_state.trial_file_contents.record_write(
                    tool_call_state.tool_call_key,
                    shell_command.id,
                    _text_with_variable_values_of(
                        file_destination.path, ran_command.variable_values
                    ),
                    channel,
                    _stdin_text_passed_on_whole_of(command_reading)
                    if passes_on_stdin_text
                    else None,
                    appends=file_destination.appends,
                    may_have_run=tool_call_state.may_have_run,
                    may_be_glob=True,
                ),
            )


def _expand_ran_texts_of_command(
    tool_call_state: _ToolCallState,
    command_reading: _CommandReading,
    text_variable_assignments: Sequence[VariableAssignment],
    *,
    running_written_file_keys: tuple[WrittenFileKey, ...],
    command_substitution_texts: frozenset[str],
) -> None:
    """Follow the texts that one command runs, i.e. its words with the role `RUN_TEXT`, the files its words name with the role `RUN_FILE`, the files it runs by their paths or by default, and its stdin.

    A program whose row runs texts or files and leaves its default run file blank gets an `UnknownRanText` when its words name no file to run, since it may run a file that no fact names.

    `text_variable_assignments` are the assignments of the command's text, which a text run in the calling shell sees, e.g. that of `eval`.
    """
    _expand_ran_texts_of_run_text_words(
        tool_call_state,
        command_reading,
        text_variable_assignments,
        running_written_file_keys=running_written_file_keys,
        command_substitution_texts=command_substitution_texts,
    )
    _expand_ran_texts_of_words_of_unknown_role(tool_call_state, command_reading)
    shell_command = command_reading.shell_command
    program_invocations = command_reading.ran_command.program_invocations
    run_file_word_indexes = command_reading.word_indexes_for_role(
        ProgramWordRole.RUN_FILE
    )
    for word_index in run_file_word_indexes:
        word = shell_command.words[word_index]
        if word != _STDIN_WORD:
            _expand_ran_text_of_file_of_program(
                tool_call_state,
                command_reading,
                command_reading.filled_word_for(word_index),
                command_reading.program_index_for_word(word),
                text_variable_assignments,
                running_written_file_keys=running_written_file_keys,
            )
    for program_invocation, program_word_index in zip(
        program_invocations, command_reading.program_word_indexes, strict=True
    ):
        if isinstance(program_invocation, UnknownProgramInvocation):
            _expand_ran_text_of_file_run_by_path(
                tool_call_state,
                command_reading,
                program_word_index,
                running_written_file_keys=running_written_file_keys,
            )
    if not run_file_word_indexes:
        for program_index, program_behavior in enumerate(
            command_reading.program_behaviors
        ):
            if not isinstance(program_behavior, ProgramBehavior):
                continue
            default_run_file = program_behavior.default_run_file
            if isinstance(default_run_file, str):
                _expand_ran_text_of_file_of_program(
                    tool_call_state,
                    command_reading,
                    default_run_file,
                    program_index,
                    text_variable_assignments,
                    running_written_file_keys=running_written_file_keys,
                    is_default_run_file=True,
                )
            elif isinstance(
                default_run_file, UnknownDefaultRunFile
            ) and _is_running_text_or_file(program_behavior):
                tool_call_state.ran_texts.append(
                    UnknownRanText(
                        FileTextWithoutKnownWriter(shell_command.id, None),
                        UnknownRanTextReason.DEFAULT_RUN_FILE_NOT_KNOWN,
                    )
                )
    _expand_ran_text_of_stdin(
        tool_call_state,
        command_reading,
        text_variable_assignments,
        running_written_file_keys=running_written_file_keys,
    )


def _expand_ran_texts_of_words_of_unknown_role(
    tool_call_state: _ToolCallState, command_reading: _CommandReading
) -> None:
    """Add an `UnknownRanText` with the reason `WORD_ROLE_NOT_KNOWN` for each argument whose role is unknown of a program whose row runs a text or a file, e.g. f.sh of `bash -n f.sh` when the row of `-n` leaves the role of the first argument blank.

    Such a word may be a text or a file that the program runs, so the run is kept as an unknown instead of nothing.
    """
    shell_command = command_reading.shell_command
    for word_index, word_role in enumerate(command_reading.word_roles):
        if not isinstance(word_role, UnknownProgramWordRole):
            continue
        word = shell_command.words[word_index]
        program_index = command_reading.program_index_for_word(word)
        program_invocation = command_reading.ran_command.program_invocations[
            program_index
        ]
        program_behavior = command_reading.program_behaviors[program_index]
        if (
            isinstance(program_invocation, ProgramInvocation)
            and word in program_invocation.arguments
            and isinstance(program_behavior, ProgramBehavior)
            and _is_running_text_or_file(program_behavior)
        ):
            tool_call_state.ran_texts.append(
                UnknownRanText(
                    ArgumentText(shell_command.id),
                    UnknownRanTextReason.WORD_ROLE_NOT_KNOWN,
                )
            )


def _is_running_text_or_file(program_behavior: ProgramBehavior) -> bool:
    """Tell whether the row of a program gives a word or its stdin the role `RUN_TEXT` or `RUN_FILE`, e.g. bash or python."""
    return any(
        role in (ProgramWordRole.RUN_TEXT, ProgramWordRole.RUN_FILE)
        for role in (
            program_behavior.argument_role,
            program_behavior.first_argument_role,
            program_behavior.last_argument_role,
            program_behavior.stdin_role,
        )
    )


def _expand_ran_texts_of_run_text_words(
    tool_call_state: _ToolCallState,
    command_reading: _CommandReading,
    text_variable_assignments: Sequence[VariableAssignment],
    *,
    running_written_file_keys: tuple[WrittenFileKey, ...],
    command_substitution_texts: frozenset[str],
) -> None:
    """Follow the text of each word with the role `RUN_TEXT`, e.g. `curl u` of `bash -c 'curl u'`, or of all such words of a program joined by spaces when its row gives every argument that role, e.g. `eval curl u`."""
    shell_command = command_reading.shell_command
    word_indexes_of_program_index: dict[int, list[int]] = {}
    for word_index in command_reading.word_indexes_for_role(ProgramWordRole.RUN_TEXT):
        program_index = command_reading.program_index_for_word(
            shell_command.words[word_index]
        )
        word_indexes_of_program_index.setdefault(program_index, []).append(word_index)
    for program_index, word_indexes in word_indexes_of_program_index.items():
        program_behavior = command_reading.program_behaviors[program_index]
        joins_arguments = (
            isinstance(program_behavior, ProgramBehavior)
            and program_behavior.argument_role == ProgramWordRole.RUN_TEXT
        )
        for word_indexes_of_text in (
            [word_indexes] if joins_arguments else [[index] for index in word_indexes]
        ):
            _expand_ran_text_of_argument_words(
                tool_call_state,
                command_reading,
                word_indexes_of_text,
                program_index,
                text_variable_assignments,
                running_written_file_keys=running_written_file_keys,
                command_substitution_texts=command_substitution_texts,
            )


def _expand_ran_text_of_argument_words(
    tool_call_state: _ToolCallState,
    command_reading: _CommandReading,
    word_indexes: Sequence[int],
    program_index: int,
    text_variable_assignments: Sequence[VariableAssignment],
    *,
    running_written_file_keys: tuple[WrittenFileKey, ...],
    command_substitution_texts: frozenset[str],
) -> None:
    """Follow one text that a program runs from its words, joined by spaces, in the language of the program.

    A word that holds an expansion is filled with the variables of exactly one value. The text is built at run time when a variable is left, or when only the output of a `$(...)` is left, e.g. `bash -c "$CMD"` or `bash -c "$(curl u)"`.
    A `$(...)` in such a word ran in the outer shell, so the reading of the text does not count its commands again.
    """
    shell_command = command_reading.shell_command
    source = ArgumentText(shell_command.id)
    expansion_word_indexes = frozenset(shell_command.expansion_word_indexes)
    texts_run_by_outer_shell = frozenset(
        command_substitution_text
        for word_index in word_indexes
        if word_index in expansion_word_indexes
        for command_substitution_text in command_substitution_texts_of(
            shell_command.words[word_index]
        )
    )
    text = " ".join(
        command_reading.filled_word_for(word_index) for word_index in word_indexes
    )
    if any(word_index in expansion_word_indexes for word_index in word_indexes) and (
        _is_built_at_run_time(text, texts_run_by_outer_shell)
    ):
        tool_call_state.ran_texts.append(
            UnknownRanText(source, UnknownRanTextReason.BUILT_AT_RUN_TIME)
        )
        return
    program_invocation = command_reading.ran_command.program_invocations[program_index]
    _expand_ran_text_of_language(
        tool_call_state,
        source,
        text,
        tool_call_state.knowledge.ran_text_language_of_program(
            program_invocation.program_name
        ),
        lambda: _shell_text_start_state_of_program(
            tool_call_state, command_reading, program_index, text_variable_assignments
        ),
        runner_command_reading=command_reading,
        running_written_file_keys=running_written_file_keys,
        command_substitution_texts=command_substitution_texts
        | texts_run_by_outer_shell,
    )


def _is_built_at_run_time(text: str, texts_run_by_outer_shell: frozenset[str]) -> bool:
    """Tell whether a text that a word gives still holds a variable after the filling, or holds nothing besides what an outer `$(...)` printed."""
    text_without_outer_output = text
    for command_substitution_text in texts_run_by_outer_shell:
        text_without_outer_output = text_without_outer_output.replace(
            command_substitution_text, ""
        )
    return (
        _VARIABLE_OR_PARAMETER_REFERENCE.search(text_without_outer_output) is not None
        or not text_without_outer_output.strip()
    )


@dataclass(frozen=True, slots=True)
class _ShellTextStartState:
    """Assignments and shell options that a shell text run by a command starts with, given by `_shell_text_start_state_of_program` when the text is shell text."""

    # The assignments of the outer text that the text sees, for a text run in the calling shell.
    outer_variable_assignments: tuple[VariableAssignment, ...]
    # The options of a new shell as `set` takes them, e.g. `("-e",)` for `bash -e f.sh`.
    set_arguments_at_start: tuple[str, ...]


# The start state of a shell text that sees no outer assignment and starts with no option, e.g. text typed into a running shell.
_NO_SHELL_TEXT_START_STATE = _ShellTextStartState((), ())


def _shell_text_start_state_of_program(
    tool_call_state: _ToolCallState,
    command_reading: _CommandReading,
    program_index: int,
    text_variable_assignments: Sequence[VariableAssignment],
) -> _ShellTextStartState:
    """Give the outer assignments and the shell options that a shell text run by a program of a command starts with.

    A text run in the calling shell, e.g. by `eval` or `source`, sees the assignments of the outer text up to the running command.
    A new shell, e.g. `bash -c`, sees none of them by a rule, and starts with the one-letter options and the `-o` or `+o` names of the program, e.g. `-e` of `bash -e f.sh`.
    """
    program_behavior = command_reading.program_behaviors[program_index]
    runner_command_id = command_reading.shell_command.id
    outer_variable_assignments = tuple(
        variable_assignment
        for variable_assignment in text_variable_assignments
        if variable_assignment.next_command_id <= runner_command_id
    )
    if isinstance(program_behavior, ProgramBehavior) and (
        program_behavior.runs_text_in_calling_shell
    ):
        return _ShellTextStartState(outer_variable_assignments, ())
    if outer_variable_assignments and not (
        treat_outer_assignment_as_not_visible_in_new_shell(
            use_counts=tool_call_state.judgment_rule_use_counts
        )
    ):
        return _ShellTextStartState(outer_variable_assignments, ())
    return _ShellTextStartState(
        (),
        _set_arguments_at_start_of(
            command_reading.ran_command.program_invocations[program_index]
        ),
    )


def _set_arguments_at_start_of(
    program_invocation: ProgramInvocation | UnknownProgramInvocation,
) -> tuple[str, ...]:
    """Give the one-letter options without a value and the `-o` or `+o` options with their names of a program that runs shell text, e.g. `("-e", "-o", "pipefail")` for `bash -eo pipefail f.sh`, as `set` takes them."""
    if isinstance(program_invocation, UnknownProgramInvocation):
        return ()
    set_arguments: list[str] = []
    for program_option in program_invocation.options:
        name = program_option.name
        if name in ("-o", "+o") and program_option.value is not None:
            set_arguments += [name, program_option.value]
        elif len(name) == 2 and name[0] in "-+" and program_option.value is None:
            set_arguments.append(name)
    return tuple(set_arguments)


def _expand_ran_text_of_file_of_program(
    tool_call_state: _ToolCallState,
    command_reading: _CommandReading,
    path: str,
    program_index: int,
    text_variable_assignments: Sequence[VariableAssignment],
    *,
    running_written_file_keys: tuple[WrittenFileKey, ...],
    is_default_run_file: bool = False,
) -> None:
    """Follow the text of a file that a program runs, e.g. fetch.sh of `bash fetch.sh` or the Makefile of `make`, in the language of the program."""
    program_invocation = command_reading.ran_command.program_invocations[program_index]
    knowledge = tool_call_state.knowledge
    _expand_ran_text_of_file(
        tool_call_state,
        command_reading,
        path,
        lambda _: knowledge.ran_text_language_of_program(
            program_invocation.program_name
        ),
        lambda _: _shell_text_start_state_of_program(
            tool_call_state, command_reading, program_index, text_variable_assignments
        ),
        running_written_file_keys=running_written_file_keys,
        is_default_run_file=is_default_run_file,
    )


def _expand_ran_text_of_file_run_by_path(
    tool_call_state: _ToolCallState,
    command_reading: _CommandReading,
    program_word_index: int,
    *,
    running_written_file_keys: tuple[WrittenFileKey, ...],
) -> None:
    """Follow the text of a file that a command runs by its path, e.g. `./run` or `/app/run.sh`, when no row covers the program word at the 0-based `program_word_index`, in the language that its `#!` line names.

    A program word without `/` names a program and not a file, e.g. `run.sh`.
    Without a `#!` line a rule reads the language of the extension. The text runs in a new shell when it is shell text, with the options of the `#!` line, e.g. `-e` of `#!/bin/bash -e`.
    """
    shell_command = command_reading.shell_command
    if "/" not in shell_command.words[program_word_index]:
        return
    path = command_reading.filled_word_for(program_word_index)
    knowledge = tool_call_state.knowledge
    judgment_rule_use_counts = tool_call_state.judgment_rule_use_counts

    def language_of_content(content: str) -> RanTextLanguage | UnknownRanTextLanguage:
        interpreter_line = _interpreter_line_of(content)
        if isinstance(interpreter_line, UnreadableInterpreterLine):
            return UnknownRanTextLanguage()
        if interpreter_line is not None:
            return knowledge.ran_text_language_of_program(
                interpreter_line.interpreter_name
            )
        file_extension = _file_extension_of(path)
        if not treat_extension_of_file_without_interpreter_line_as_its_language(
            path, use_counts=judgment_rule_use_counts
        ):
            return UnknownRanTextLanguage()
        if file_extension is None:
            return UnknownRanTextLanguage()
        return knowledge.ran_text_language_of_file_extension(file_extension)

    _expand_ran_text_of_file(
        tool_call_state,
        command_reading,
        path,
        language_of_content,
        _shell_text_start_state_of_interpreter_line,
        running_written_file_keys=running_written_file_keys,
        is_default_run_file=False,
    )


def _interpreter_line_of(
    content: str,
) -> InterpreterLine | UnreadableInterpreterLine | None:
    """Read the `#!` line that starts the content of a file, None when it starts with none."""
    return parse_interpreter_line(content.split("\n", 1)[0])


def _shell_text_start_state_of_interpreter_line(content: str) -> _ShellTextStartState:
    """Give the shell options that the `#!` line of a shell file starts its text with, e.g. `("-e",)` for `#!/bin/bash -e`, as `_set_arguments_at_start_of` picks them for `bash -e f.sh`.

    The text runs in a new shell, so it sees no outer assignment.
    """
    interpreter_line = _interpreter_line_of(content)
    if not isinstance(interpreter_line, InterpreterLine):
        return _NO_SHELL_TEXT_START_STATE
    return _ShellTextStartState(
        (), _set_arguments_at_start_of_words(interpreter_line.argument_words)
    )


def _set_arguments_at_start_of_words(words: Sequence[str]) -> tuple[str, ...]:
    """Give the one-letter options and the `-o` or `+o` options with their names among the words after the interpreter of a `#!` line, e.g. `("-e",)` for `-e`, as written and as `set` takes them."""
    set_arguments: list[str] = []
    word_iterator = iter(words)
    for word in word_iterator:
        if word in ("-o", "+o"):
            option_name = next(word_iterator, None)
            if option_name is not None:
                set_arguments += [word, option_name]
        elif len(word) >= 2 and word[0] in "-+" and word[1] not in "-+":
            set_arguments.append(word)
    return tuple(set_arguments)


def _expand_ran_text_of_file(
    tool_call_state: _ToolCallState,
    command_reading: _CommandReading,
    path: str,
    language_of_content: Callable[[str], RanTextLanguage | UnknownRanTextLanguage],
    shell_text_start_state_of_content: Callable[[str], _ShellTextStartState],
    *,
    running_written_file_keys: tuple[WrittenFileKey, ...],
    is_default_run_file: bool,
) -> None:
    """Record a use of a file that a command runs and follow its text as the trial last wrote it, or add an `UnknownRanText` with the reason the text cannot be followed.

    `language_of_content` and `shell_text_start_state_of_content` give the language of the text and, for shell text, the state it starts with, from the content of the file.

    The path of a default run file is not in the words, so the source holds no path, e.g. the Makefile of `make`.
    A path that fits no written file and still holds a variable is built at run time, e.g. `bash $F` when F has no single value.
    """
    shell_command = command_reading.shell_command
    trial_file_contents = tool_call_state.trial_file_contents
    if tool_call_state.may_have_run and _may_touch_files(
        tool_call_state, shell_command
    ):
        _add_file_touch(
            tool_call_state,
            trial_file_contents.record_use(
                shell_command.id, path, FileTouchKind.USES_CONTENT, may_be_glob=True
            ),
        )
    source_path = None if is_default_run_file else path
    latest_file_text = trial_file_contents.file_text(path)
    written_file_keys = latest_file_text.written_file_keys
    if len(written_file_keys) != 1:
        if written_file_keys:
            reason = UnknownRanTextReason.FITS_SEVERAL_WRITTEN_FILES
        elif _VARIABLE_OR_PARAMETER_REFERENCE.search(path):
            reason = UnknownRanTextReason.BUILT_AT_RUN_TIME
        else:
            reason = UnknownRanTextReason.NOT_WRITTEN_IN_TRIAL
        tool_call_state.ran_texts.append(
            UnknownRanText(
                FileTextWithoutKnownWriter(shell_command.id, source_path), reason
            )
        )
        return
    written_file_key = written_file_keys[0]
    source = FileText(shell_command.id, source_path, written_file_key.tool_call_key)
    content = latest_file_text.content
    if written_file_key in running_written_file_keys:
        tool_call_state.ran_texts.append(
            UnknownRanText(source, UnknownRanTextReason.FILE_ALREADY_RUNNING)
        )
    elif content is None:
        tool_call_state.ran_texts.append(
            UnknownRanText(source, UnknownRanTextReason.CHANGED_BY_UNREAD_COMMAND)
        )
    else:
        _expand_ran_text_of_language(
            tool_call_state,
            source,
            content,
            language_of_content(content),
            lambda: shell_text_start_state_of_content(content),
            runner_command_reading=command_reading,
            running_written_file_keys=(*running_written_file_keys, written_file_key),
            command_substitution_texts=frozenset(),
        )


def _expand_ran_text_of_stdin(
    tool_call_state: _ToolCallState,
    command_reading: _CommandReading,
    text_variable_assignments: Sequence[VariableAssignment],
    *,
    running_written_file_keys: tuple[WrittenFileKey, ...],
) -> None:
    """Follow the heredoc, herestring, file or pipe that a command's innermost program reads as its stdin, as the role of its stdin in its row says, e.g. code for `python - <<EOF` or a shown file for `grep error < build.log`.

    The program reads its stdin only when none of the command's words names a file or a text, apart from `-`.
    A heredoc that a program without a row or with an unknown stdin role takes is text in an unknown language, and a written file it takes is a use of unknown kind.
    """
    shell_command = command_reading.shell_command
    program_invocations = command_reading.ran_command.program_invocations
    if not program_invocations or _has_word_in_place_of_stdin(
        shell_command.words, command_reading.word_roles
    ):
        return
    source = StdinText(shell_command.id)
    program_index = len(program_invocations) - 1
    program_behavior = command_reading.program_behaviors[program_index]
    stdin_role = (
        program_behavior.stdin_role
        if isinstance(program_behavior, ProgramBehavior)
        else UnknownProgramWordRole()
    )
    stdin_file_path = (
        None
        if shell_command.stdin_file_path is None
        else _text_with_variable_values_of(
            shell_command.stdin_file_path, command_reading.ran_command.variable_values
        )
    )
    may_record_use = tool_call_state.may_have_run and stdin_file_path is not None
    stdin_text = _stdin_text_read_by_program_of(shell_command)
    if stdin_role == ProgramWordRole.RUN_TEXT:
        if shell_command.stdin_text is not None and stdin_text is None:
            tool_call_state.ran_texts.append(
                UnknownRanText(source, UnknownRanTextReason.BUILT_AT_RUN_TIME)
            )
        elif stdin_text is not None:
            _expand_ran_text_of_language(
                tool_call_state,
                source,
                stdin_text,
                tool_call_state.knowledge.ran_text_language_of_program(
                    program_invocations[program_index].program_name
                ),
                lambda: _shell_text_start_state_of_program(
                    tool_call_state,
                    command_reading,
                    program_index,
                    text_variable_assignments,
                ),
                runner_command_reading=command_reading,
                running_written_file_keys=running_written_file_keys,
                command_substitution_texts=frozenset(),
            )
        elif stdin_file_path is not None:
            _expand_ran_text_of_file_of_program(
                tool_call_state,
                command_reading,
                stdin_file_path,
                program_index,
                text_variable_assignments,
                running_written_file_keys=running_written_file_keys,
            )
        elif command_reading.reads_pipe:
            tool_call_state.ran_texts.append(
                UnknownRanText(source, UnknownRanTextReason.READ_FROM_PIPE)
            )
    elif isinstance(stdin_role, UnknownProgramWordRole):
        if shell_command.stdin_text is not None:
            tool_call_state.ran_texts.append(
                UnknownRanText(source, UnknownRanTextReason.LANGUAGE_NOT_KNOWN)
            )
        elif may_record_use and stdin_file_path is not None:
            _add_unknown_use(tool_call_state, shell_command, stdin_file_path)
    elif (
        isinstance(stdin_role, ProgramWordRole)
        and stdin_role in _FILE_TOUCH_KIND_OF_USE_ROLE
        and may_record_use
        and stdin_file_path is not None
        and _may_touch_files(tool_call_state, shell_command)
    ):
        _add_file_touch(
            tool_call_state,
            tool_call_state.trial_file_contents.record_use(
                shell_command.id,
                stdin_file_path,
                _FILE_TOUCH_KIND_OF_USE_ROLE[stdin_role],
                may_be_glob=True,
            ),
        )


def _has_word_in_place_of_stdin(
    words: Sequence[str],
    word_roles: Sequence[ProgramWordRole | UnknownProgramWordRole | None],
) -> bool:
    """Tell whether a word of a command other than `-` names a file or a text that its program reads instead of its stdin, e.g. get.py of `python get.py < in.txt`."""
    return any(
        word_role in _ROLES_IN_PLACE_OF_STDIN and word != _STDIN_WORD
        for word, word_role in zip(words, word_roles, strict=True)
    )


def _expand_ran_text_of_language(
    tool_call_state: _ToolCallState,
    source: CodeTextSource,
    text: str,
    ran_text_language: RanTextLanguage | UnknownRanTextLanguage,
    shell_text_start_state_for: Callable[[], _ShellTextStartState],
    *,
    runner_command_reading: _CommandReading | None,
    running_written_file_keys: tuple[WrittenFileKey, ...],
    command_substitution_texts: frozenset[str],
) -> None:
    """Add a text that the trial holds, as shell text whose commands are followed further, as code, or as an `UnknownRanText` when its language is unknown.

    `runner_command_reading` is the command that runs the text, None for text typed into a running program.
    `shell_text_start_state_for` is asked only for shell text, so that the rule about outer assignments counts only texts that a shell runs.
    """
    if isinstance(ran_text_language, ShellLanguage):
        shell_text_start_state = shell_text_start_state_for()
        _expand_ran_shell_text(
            tool_call_state,
            source,
            _split_added_shell_text(
                tool_call_state,
                text,
                runner=None
                if runner_command_reading is None
                else runner_command_reading.shell_command,
                set_arguments_at_start=shell_text_start_state.set_arguments_at_start,
                command_substitution_texts=command_substitution_texts,
            ),
            outer_variable_assignments=shell_text_start_state.outer_variable_assignments,
            runner_command_reading=runner_command_reading,
            running_written_file_keys=running_written_file_keys,
            command_substitution_texts=command_substitution_texts,
        )
    elif isinstance(ran_text_language, CodeLanguage):
        tool_call_state.ran_texts.append(RanCodeText(source, ran_text_language, text))
    else:
        tool_call_state.ran_texts.append(
            UnknownRanText(source, UnknownRanTextReason.LANGUAGE_NOT_KNOWN)
        )


def _split_added_shell_text(
    tool_call_state: _ToolCallState,
    text: str,
    *,
    runner: ShellCommand | None,
    set_arguments_at_start: tuple[str, ...],
    command_substitution_texts: frozenset[str],
) -> ParsedShellText | UnreadableShellText:
    """Split a shell text that the call runs beyond its own texts into commands whose ids come after all ids of the call so far."""
    parsed_shell_text = parse_shell_text(
        text,
        judgment_rule_use_counts=tool_call_state.judgment_rule_use_counts,
        first_command_id=tool_call_state.next_command_id,
        runner=runner,
        set_arguments_at_start=set_arguments_at_start,
        command_substitution_texts_run_by_outer_shell=command_substitution_texts,
    )
    if isinstance(parsed_shell_text, ParsedShellText) and parsed_shell_text.commands:
        tool_call_state.next_command_id = parsed_shell_text.commands[-1].id + 1
    return parsed_shell_text


def _text_with_variable_values_of(
    text: str, variable_values: Sequence[VariableValues]
) -> str:
    """Fill each `$NAME` or `${NAME}` of a text whose variable has exactly one value and no value set at run time, e.g. fetch.sh for `$F` after `F=fetch.sh`."""
    sure_value_of_name = {
        variable_value.name: variable_value.values[0]
        for variable_value in variable_values
        if len(variable_value.values) == 1
        and not variable_value.has_value_set_at_run_time
    }

    def value_or_variable(match: re.Match[str]) -> str:
        return sure_value_of_name.get(match.group(1) or match.group(2), match.group(0))

    return _PLAIN_VARIABLE.sub(value_or_variable, text)


def _file_extension_of(path: str) -> str | None:
    """Give the extension of the last part of a path, e.g. `.py` for `./get.py`, None when it has none."""
    match = _FILE_EXTENSION_AT_END.search(path.rsplit("/", 1)[-1])
    return match.group(0) if match else None


class TrialFileContents:
    """State of the files that the calls of one trajectory wrote so far, kept while `expand_ran_texts` reads the calls in order. Every method that records returns the `FileTouch` it records.

    Each write, removal and use asks rules about how two paths name one file and how earlier writes count, so that the choices are in one place.
    A method returns None when a rule leaves the touch out, e.g. for a glob such as `*.sh`.
    """

    def __init__(self, *, judgment_rule_use_counts: Counter[str]) -> None:
        self._judgment_rule_use_counts = judgment_rule_use_counts
        self._written_file_histories: list[_WrittenFileHistory] = []
        self._written_file_history_of_key: dict[
            WrittenFileKey, _WrittenFileHistory
        ] = {}
        # The keys of the files that each call wrote, so that the writes of one call to one file share a key.
        self._written_file_keys_of_tool_call: dict[
            ToolCallKey, list[WrittenFileKey]
        ] = {}
        # The `output_path` of each result of the calls read so far, with the call of that result.
        self._harness_output_paths_and_tool_call_keys: list[
            tuple[str, ToolCallKey]
        ] = []

    def record_write(
        self,
        tool_call_key: ToolCallKey,
        command_id: int | None,
        path: str,
        channel: FileWriteChannel,
        content: str | None,
        *,
        appends: bool,
        may_have_run: bool,
        may_be_glob: bool,
    ) -> FileTouch | None:
        """Record a write of a file and give its touch, whose key is that of the call's earlier write to the same file or a new one.

        A write that appends keeps the earlier writes and leaves the content unknown. A write of a call that did not run changes nothing.
        A write that replaces the content of the file where the harness saved a result ends the reads of that result, e.g. `echo x > /tmp/tasks/b1.output`.
        `may_be_glob` is False for the path argument of a tool, which names one file as written, e.g. `app/[id]/page.tsx`, and True for a word or redirect of a command, which the shell may expand.
        """
        if may_be_glob and self._is_glob(path):
            return None
        written_file_key = self._written_file_key_for(tool_call_key, path)
        if may_have_run:
            self._record_written_content(
                written_file_key, path, content, appends=appends
            )
            if not appends:
                self._forget_harness_output_files_named_by(path)
        return FileTouch(
            command_id,
            path,
            FileTouchKind.WRITES,
            channel,
            (written_file_key,),
            False,
            (),
        )

    def record_copy(
        self,
        tool_call_key: ToolCallKey,
        command_id: int | None,
        source_path: str,
        destination_path: str,
        *,
        may_have_run: bool,
    ) -> FileTouch | None:
        """Record the copy that a command with exactly two arguments makes, e.g. g.sh of `cp f.sh g.sh`, with the content of the source by a rule, and record no use of the source."""
        if self._is_glob(source_path):
            return None
        content = (
            self._sure_content_of(source_path)
            if treat_copy_with_two_arguments_as_same_content(
                use_counts=self._judgment_rule_use_counts
            )
            else None
        )
        return self.record_write(
            tool_call_key,
            command_id,
            destination_path,
            FileWriteChannel.OWN_OUTPUT_FILE,
            content,
            appends=False,
            may_have_run=may_have_run,
            may_be_glob=True,
        )

    def record_deletion(
        self, command_id: int | None, path: str, *, may_be_glob: bool
    ) -> FileTouch | None:
        """Record the removal of the written files a path fits, after which a rule reads them as never written, e.g. f.sh of `rm f.sh`.

        A path that names a folder of a written file, e.g. scripts of `rm -rf scripts`, touches none of its files by a rule.
        A removal of the file where the harness saved a result ends the reads of that result, e.g. `rm /tmp/tasks/b1.output`.
        `may_be_glob` says whether the path may be a glob, as for `record_write`.
        """
        if (may_be_glob and self._is_glob(path)) or (
            self._is_folder_of_written_file(path)
            and treat_file_not_named_by_command_words_as_untouched(
                path, use_counts=self._judgment_rule_use_counts
            )
        ):
            return None
        written_file_histories = self._written_file_histories_fitting(path)
        for written_file_history in written_file_histories:
            written_file_history.is_deleted = True
        self._forget_harness_output_files_named_by(path)
        return FileTouch(
            command_id,
            path,
            FileTouchKind.DELETES,
            None,
            tuple(
                written_file_key
                for written_file_history in written_file_histories
                for written_file_key in written_file_history.written_file_keys
            ),
            False,
            (),
        )

    def record_use(
        self,
        command_id: int | None,
        path: str,
        kind: FileTouchKind,
        *,
        may_be_glob: bool,
    ) -> FileTouch | None:
        """Record a use of a file and give the written files it is a use of, i.e. the writes since the last write that replaced the content.

        A use of unknown kind leaves the content of the written file unknown, since the program may have changed it.
        Its word has no known file role, e.g. `{print $1}` of an awk without a row, so a glob there asks no rule.
        `may_be_glob` says whether the path may be a glob, as for `record_write`.
        """
        if may_be_glob and kind != FileTouchKind.UNKNOWN_USE and self._is_glob(path):
            return None
        harness_output_file_tool_call_keys = tuple(
            dict.fromkeys(
                tool_call_key
                for harness_output_path, tool_call_key in self._harness_output_paths_and_tool_call_keys
                if self._may_name_same_file(path, harness_output_path)
            )
        )
        written_file_histories = self._live_written_file_histories_fitting(path)
        if kind == FileTouchKind.UNKNOWN_USE:
            for written_file_history in written_file_histories:
                written_file_history.content = None
        fits_several_written_files = len(written_file_histories) > 1 and (
            treat_use_of_path_that_fits_several_written_files_as_use_of_each(
                path, use_counts=self._judgment_rule_use_counts
            )
        )
        if len(written_file_histories) > 1 and not fits_several_written_files:
            written_file_histories = []
        written_file_keys: list[WrittenFileKey] = []
        for written_file_history in written_file_histories:
            if written_file_history.replaced_written_file_keys and not (
                treat_use_after_later_overwrite_as_use_of_later_write(
                    path, use_counts=self._judgment_rule_use_counts
                )
            ):
                written_file_keys += written_file_history.replaced_written_file_keys
            written_file_keys += written_file_history.written_file_keys
        return FileTouch(
            command_id,
            path,
            kind,
            None,
            tuple(written_file_keys),
            fits_several_written_files,
            harness_output_file_tool_call_keys,
        )

    def file_text(self, path: str) -> LatestFileText:
        """Give the last write of each written file a path fits and the content when exactly one fits, unknown by a rule when several fit."""
        written_file_histories = self._live_written_file_histories_fitting(path)
        if not written_file_histories:
            return LatestFileText((), None)
        if len(written_file_histories) == 1:
            (written_file_history,) = written_file_histories
            return LatestFileText(
                (written_file_history.written_file_keys[-1],),
                written_file_history.content,
            )
        if treat_path_that_fits_several_written_files_as_unknown_text(
            path, use_counts=self._judgment_rule_use_counts
        ):
            return LatestFileText(
                tuple(
                    written_file_history.written_file_keys[-1]
                    for written_file_history in written_file_histories
                ),
                None,
            )
        latest_written_file_history = written_file_histories[-1]
        return LatestFileText(
            (latest_written_file_history.written_file_keys[-1],),
            latest_written_file_history.content,
        )

    def has_written_file_fitting(self, path: str) -> bool:
        """Tell whether a path can name a file that a call of the trajectory wrote, removed or not, without asking the rule on two paths.

        It only tells whether to ask the rule on other trajectories, so it does not count a use of the rule on two paths.
        """
        path_parts = _path_parts_of(path)
        return any(
            path == written_path
            or _may_path_parts_name_same_file(path_parts, _path_parts_of(written_path))
            for written_file_history in self._written_file_histories
            for written_path in written_file_history.paths
        )

    def record_harness_output_file(self, path: str, tool_call_key: ToolCallKey) -> None:
        """Record the file where the harness saved the whole result of a call, so that a later read of it is marked as one of that call's result."""
        self._harness_output_paths_and_tool_call_keys.append((path, tool_call_key))

    def _forget_harness_output_files_named_by(self, path: str) -> None:
        """Forget each file where the harness saved a result that a path can name, since a write that replaces it or a removal leaves none of that result to read."""
        self._harness_output_paths_and_tool_call_keys = [
            (harness_output_path, tool_call_key)
            for harness_output_path, tool_call_key in self._harness_output_paths_and_tool_call_keys
            if not self._may_name_same_file(path, harness_output_path)
        ]

    def _written_file_key_for(
        self, tool_call_key: ToolCallKey, path: str
    ) -> WrittenFileKey:
        """Give the key of the call's earlier write to the file a path names, or a new key with this path."""
        written_file_keys = self._written_file_keys_of_tool_call.setdefault(
            tool_call_key, []
        )
        for written_file_key in written_file_keys:
            if self._may_name_same_file(path, written_file_key.path):
                return written_file_key
        written_file_key = WrittenFileKey(tool_call_key, path)
        written_file_keys.append(written_file_key)
        return written_file_key

    def _record_written_content(
        self,
        written_file_key: WrittenFileKey,
        path: str,
        content: str | None,
        *,
        appends: bool,
    ) -> None:
        """Change the state of the file that a write of a call that may have run writes.

        A later write of the same call to the same file keeps the writes as they are.
        A path that fits several written files starts a file of its own, since the text does not say which of them it writes, and leaves the content of each of them unknown, since it may have changed any of them.
        """
        written_content = None if appends else content
        written_file_history = self._written_file_history_of_key.get(written_file_key)
        if written_file_history is None:
            written_file_histories = self._written_file_histories_fitting(path)
            if len(written_file_histories) == 1:
                (written_file_history,) = written_file_histories
                if not appends or written_file_history.is_deleted:
                    written_file_history.replaced_written_file_keys += (
                        written_file_history.written_file_keys
                    )
                    written_file_history.written_file_keys = []
                written_file_history.written_file_keys.append(written_file_key)
                written_file_history.paths.append(path)
            else:
                for fitting_written_file_history in written_file_histories:
                    fitting_written_file_history.content = None
                written_file_history = _WrittenFileHistory(
                    [path], [written_file_key], [], written_content
                )
                self._written_file_histories.append(written_file_history)
            self._written_file_history_of_key[written_file_key] = written_file_history
        written_file_history.content = written_content
        written_file_history.is_deleted = False

    def _sure_content_of(self, path: str) -> str | None:
        """Give the content of the one written file a path fits, None when none or several fit, it was removed or its content is unknown."""
        written_file_histories = self._written_file_histories_fitting(path)
        if len(written_file_histories) != 1 or written_file_histories[0].is_deleted:
            return None
        return written_file_histories[0].content

    def _live_written_file_histories_fitting(
        self, path: str
    ) -> list[_WrittenFileHistory]:
        """List the written files a path fits, leaving out by a rule those removed since their last write."""
        return [
            written_file_history
            for written_file_history in self._written_file_histories_fitting(path)
            if not (
                written_file_history.is_deleted
                and treat_deleted_file_as_never_written(
                    path, use_counts=self._judgment_rule_use_counts
                )
            )
        ]

    def _written_file_histories_fitting(self, path: str) -> list[_WrittenFileHistory]:
        """List the written files that a path can name, in the order of their first writes."""
        return [
            written_file_history
            for written_file_history in self._written_file_histories
            if any(
                self._may_name_same_file(path, written_path)
                for written_path in written_file_history.paths
            )
        ]

    def _may_name_same_file(self, path: str, other_path: str) -> bool:
        """Tell whether two paths can name one file, asking a rule when they differ as written and the relative one ends the other by whole folders."""
        if path == other_path:
            return True
        if not _may_path_parts_name_same_file(
            _path_parts_of(path), _path_parts_of(other_path)
        ):
            return False
        return treat_path_that_ends_another_as_same_file(
            path, other_path, use_counts=self._judgment_rule_use_counts
        )

    def _is_folder_of_written_file(self, path: str) -> bool:
        """Tell whether a path names a folder that holds a written file, e.g. scripts for scripts/fetch.sh."""
        is_absolute, parts = _path_parts_of(path)
        for written_file_history in self._written_file_histories:
            for written_path in written_file_history.paths:
                written_path_is_absolute, written_path_parts = _path_parts_of(
                    written_path
                )
                if any(
                    _may_path_parts_name_same_file(
                        (is_absolute, parts),
                        (written_path_is_absolute, written_path_parts[:part_count]),
                    )
                    for part_count in range(1, len(written_path_parts))
                ):
                    return True
        return False

    def _is_glob(self, path: str) -> bool:
        """Tell whether a path is a glob or a brace list, whose files a rule leaves untouched, e.g. `*.sh`.

        The braces of a parameter, e.g. `${D}` of `${D}/f.sh`, make no brace list.
        """
        return not _GLOB_CHARACTERS.isdisjoint(_PARAMETER_IN_BRACES.sub("", path)) and (
            treat_file_not_named_by_command_words_as_untouched(
                path, use_counts=self._judgment_rule_use_counts
            )
        )


@dataclass(slots=True)
class _WrittenFileHistory:
    """State of one file that the calls of a trajectory wrote, kept by `TrialFileContents` from its first write on."""

    # Every path that a write named it by, so that a later path can fit any of them.
    paths: list[str]
    # The writes since the last write that replaced the content, in call order. Several when a later call appended.
    written_file_keys: list[WrittenFileKey]
    # The writes of earlier calls that a later write replaced, read only to ask a rule.
    replaced_written_file_keys: list[WrittenFileKey]
    # None when the trial does not show the content.
    content: str | None
    # A command or a tool removed it after the last write.
    is_deleted: bool = False


def _path_parts_of(path: str) -> tuple[bool, tuple[str, ...]]:
    """Split a path into whether it is absolute and its parts, without `.`, empty parts and `x/..`, and without the leading parts of a relative path whose folder the text does not show, e.g. `(False, ("out",))` for `$LOG/out`.

    A `..` right after the root stays at the root, as in `/../f`, which names `/f`.
    """
    is_absolute = path.startswith("/")
    parts: list[str] = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == ".." and parts and parts[-1] != "..":
            parts.pop()
        elif not (part == ".." and is_absolute and not parts):
            parts.append(part)
    while not is_absolute and parts and _UNKNOWN_FOLDER_PART.match(parts[0]):
        parts.pop(0)
    return is_absolute, tuple(parts)


def _may_path_parts_name_same_file(
    path_parts: tuple[bool, tuple[str, ...]],
    other_path_parts: tuple[bool, tuple[str, ...]],
) -> bool:
    """Tell whether two split paths can name one file, i.e. two absolute ones are equal, and otherwise a relative one ends the other by whole parts."""
    is_absolute, parts = path_parts
    other_is_absolute, other_parts = other_path_parts
    if not parts or not other_parts:
        return False
    if is_absolute and other_is_absolute:
        return parts == other_parts
    if is_absolute:
        return _has_ending_parts(parts, other_parts)
    if other_is_absolute:
        return _has_ending_parts(other_parts, parts)
    shorter_parts, longer_parts = sorted((parts, other_parts), key=len)
    return _has_ending_parts(longer_parts, shorter_parts)


def _has_ending_parts(parts: tuple[str, ...], ending_parts: tuple[str, ...]) -> bool:
    """Tell whether the parts of a path end with other parts."""
    return (
        len(ending_parts) <= len(parts) and parts[-len(ending_parts) :] == ending_parts
    )
