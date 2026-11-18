"""Tests for the checks that the types of expanded_tool_call/model.py make when they are built."""

import pytest

from tb_internet_use.expanded_tool_call.model import (
    ArgumentText,
    CallCommandText,
    FileText,
    FileTextWithoutKnownWriter,
    FileWriteChannel,
    OutputRoute,
    OutputVisibility,
    PollInputText,
    ProgramOptionBehavior,
    ProgramWordRole,
    RanTextSource,
    ScriptStepText,
    StdinText,
    UnknownExitsWithExitCodeOfNextProgram,
    UnknownOptionsEndAtFirstArgument,
    UnknownProgramWordRole,
    UnknownRanText,
    UnknownRanTextReason,
    UnknownTakesOneLetterOptionsJoined,
    WrittenFile,
    WrittenFileWriter,
)
from tb_internet_use.tool_call.model import ResultDestination, ToolCallKey

WRITER_TOOL_CALL_KEY = ToolCallKey("trial", "main", 1, 0)
# One source of each type, by the name of the type.
RAN_TEXT_SOURCE_BY_TYPE_NAME: dict[str, RanTextSource] = {
    "CallCommandText": CallCommandText(),
    "ScriptStepText": ScriptStepText(0),
    "PollInputText": PollInputText(None, None),
    "FileText": FileText(0, "f.sh", WRITER_TOOL_CALL_KEY),
    "FileTextWithoutKnownWriter": FileTextWithoutKnownWriter(0, "f.sh"),
    "StdinText": StdinText(0),
    "ArgumentText": ArgumentText(0),
}
# The names of the source types that each reason fits, written out by hand, e.g. only stdin gets text through a pipe, and only a file can already be running.
SOURCE_TYPE_NAMES_OF_REASON = {
    UnknownRanTextReason.NOT_WRITTEN_IN_TRIAL: {"FileTextWithoutKnownWriter"},
    UnknownRanTextReason.FITS_SEVERAL_WRITTEN_FILES: {"FileTextWithoutKnownWriter"},
    UnknownRanTextReason.CHANGED_BY_UNREAD_COMMAND: {"FileText"},
    UnknownRanTextReason.READ_FROM_PIPE: {"StdinText"},
    UnknownRanTextReason.WORD_ROLE_NOT_KNOWN: {"ArgumentText"},
    UnknownRanTextReason.BUILT_AT_RUN_TIME: {
        "ArgumentText",
        "FileTextWithoutKnownWriter",
        "StdinText",
    },
    UnknownRanTextReason.MISSING_FROM_TRAJECTORY: {
        "CallCommandText",
        "ScriptStepText",
    },
    UnknownRanTextReason.LANGUAGE_NOT_KNOWN: {
        "FileText",
        "StdinText",
        "ArgumentText",
        "PollInputText",
    },
    UnknownRanTextReason.UNREADABLE_SHELL_TEXT: {
        "CallCommandText",
        "ScriptStepText",
        "PollInputText",
        "FileText",
        "StdinText",
        "ArgumentText",
    },
    UnknownRanTextReason.FILE_ALREADY_RUNNING: {"FileText"},
}


def build_program_option_behavior(
    *,
    takes_value: bool,
    value_role: ProgramWordRole | UnknownProgramWordRole | None,
    changed_option_name: str | None = None,
    changed_option_value_role: ProgramWordRole | UnknownProgramWordRole | None = None,
) -> ProgramOptionBehavior:
    return ProgramOptionBehavior(
        takes_value=takes_value,
        value_role=value_role,
        argument_role_with_option=None,
        first_argument_role_with_option=None,
        last_argument_role_with_option=None,
        changed_option_name=changed_option_name,
        changed_option_value_role=changed_option_value_role,
        gives_arguments_at_run_time=False,
        next_program_end_words=(),
        exits_with_exit_code_of_next_program_with_option=None,
    )


@pytest.mark.parametrize(
    ("reason", "source_type_name"),
    [
        (reason, name)
        for reason in UnknownRanTextReason
        for name in RAN_TEXT_SOURCE_BY_TYPE_NAME
    ],
)
def test_unknown_ran_text_accepts_a_reason_only_with_the_sources_it_fits(
    reason: UnknownRanTextReason, source_type_name: str
):
    source = RAN_TEXT_SOURCE_BY_TYPE_NAME[source_type_name]
    if source_type_name in SOURCE_TYPE_NAMES_OF_REASON[reason]:
        assert UnknownRanText(source, reason).source == source
    else:
        with pytest.raises(ValueError):
            UnknownRanText(source, reason)


@pytest.mark.parametrize(
    ("command_id", "channel", "is_accepted"),
    [
        (None, FileWriteChannel.TOOL_ARGUMENT, True),
        (0, FileWriteChannel.TOOL_ARGUMENT, False),
        (0, FileWriteChannel.STDOUT, True),
        (None, FileWriteChannel.STDOUT, False),
        (0, FileWriteChannel.STDERR, True),
        (None, FileWriteChannel.STDERR, False),
        (0, FileWriteChannel.OWN_OUTPUT_FILE, True),
        (None, FileWriteChannel.OWN_OUTPUT_FILE, False),
    ],
)
def test_written_file_writer_has_a_command_id_exactly_when_a_command_writes(
    command_id: int | None, channel: FileWriteChannel, is_accepted: bool
):
    if is_accepted:
        assert WrittenFileWriter(command_id, channel).channel == channel
    else:
        with pytest.raises(ValueError):
            WrittenFileWriter(command_id, channel)


def test_written_file_has_at_least_one_writer():
    writer = WrittenFileWriter(0, FileWriteChannel.STDOUT)
    assert WrittenFile("log", (writer,), ()).writers == (writer,)
    with pytest.raises(ValueError):
        WrittenFile("log", (), ())


@pytest.mark.parametrize(
    ("pipe_reader_command_ids", "visibility_at_end", "is_accepted"),
    [
        ((), OutputVisibility.WHOLE, True),
        ((), OutputVisibility.PARTIAL, False),
        ((), OutputVisibility.NONE, False),
        ((), OutputVisibility.UNKNOWN, False),
        ((1,), OutputVisibility.WHOLE, True),
        ((1,), OutputVisibility.NONE, True),
    ],
)
def test_output_route_without_pipe_readers_keeps_the_whole_output(
    pipe_reader_command_ids: tuple[int, ...],
    visibility_at_end: OutputVisibility,
    is_accepted: bool,
):
    if is_accepted:
        route = OutputRoute(
            pipe_reader_command_ids, ResultDestination(), visibility_at_end
        )
        assert route.visibility_at_end == visibility_at_end
    else:
        with pytest.raises(ValueError):
            OutputRoute(pipe_reader_command_ids, ResultDestination(), visibility_at_end)


@pytest.mark.parametrize(
    "unknown",
    [
        UnknownExitsWithExitCodeOfNextProgram(),
        UnknownOptionsEndAtFirstArgument(),
        UnknownTakesOneLetterOptionsJoined(),
    ],
)
def test_unknown_answer_to_a_yes_or_no_cell_is_not_read_as_true_or_false(unknown):
    with pytest.raises(TypeError):
        all([True, unknown])


@pytest.mark.parametrize(
    ("takes_value", "value_role", "is_accepted"),
    [
        (True, ProgramWordRole.WRITTEN_FILE, True),
        (True, UnknownProgramWordRole(), True),
        (False, None, True),
        (True, None, False),
        (False, ProgramWordRole.OTHER, False),
    ],
)
def test_program_option_behavior_has_a_value_role_exactly_when_the_option_takes_a_value(
    takes_value: bool,
    value_role: ProgramWordRole | UnknownProgramWordRole | None,
    is_accepted: bool,
):
    if is_accepted:
        behavior = build_program_option_behavior(
            takes_value=takes_value, value_role=value_role
        )
        assert behavior.value_role == value_role
    else:
        with pytest.raises(ValueError):
            build_program_option_behavior(
                takes_value=takes_value, value_role=value_role
            )


@pytest.mark.parametrize(
    ("changed_option_name", "changed_option_value_role", "is_accepted"),
    [
        ("-f", ProgramWordRole.WRITTEN_FILE, True),
        ("-f", UnknownProgramWordRole(), True),
        (None, None, True),
        ("-f", None, False),
        (None, ProgramWordRole.WRITTEN_FILE, False),
    ],
)
def test_program_option_behavior_names_a_changed_option_exactly_when_it_gives_its_value_a_role(
    changed_option_name: str | None,
    changed_option_value_role: ProgramWordRole | UnknownProgramWordRole | None,
    is_accepted: bool,
):
    def build_option_behavior_with_changed_option() -> ProgramOptionBehavior:
        return build_program_option_behavior(
            takes_value=False,
            value_role=None,
            changed_option_name=changed_option_name,
            changed_option_value_role=changed_option_value_role,
        )

    if is_accepted:
        behavior = build_option_behavior_with_changed_option()
        assert behavior.changed_option_name == changed_option_name
    else:
        with pytest.raises(ValueError):
            build_option_behavior_with_changed_option()
