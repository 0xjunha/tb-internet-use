"""Tests for expanded_tool_call/_expand_written_files.py, on made-up calls of one trial whose file touches come from the real `expand_ran_texts` with a made-up program catalog, so that a case does not change when the real catalog gains rows."""

from collections import Counter
from pathlib import Path

import pytest

from tb_internet_use.expanded_tool_call import _expand_ran_texts
from tb_internet_use.expanded_tool_call._expand_poll_links import expand_poll_links
from tb_internet_use.expanded_tool_call._expand_ran_texts import (
    FileTouch,
    FileTouchKind,
    RanTextsOfToolCall,
    WrittenFileKey,
    expand_ran_texts,
)
from tb_internet_use.expanded_tool_call._expand_written_files import (
    expand_written_files,
)
from tb_internet_use.expanded_tool_call.judgment_rules import (
    treat_use_of_path_that_fits_several_written_files_as_use_of_none,
)
from tb_internet_use.expanded_tool_call.model import (
    FileUse,
    FileUseKind,
    FileWriteChannel,
    WrittenFile,
    WrittenFileWriter,
)
from tb_internet_use.knowledge.expanded_tool_call_knowledge import (
    ExpandedToolCallKnowledge,
)
from tb_internet_use.tool_call.model import (
    ChangeFilesAction,
    DeleteFileAction,
    EditFileAction,
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    ReadFileAction,
    RunCommandAction,
    RunToolScriptAction,
    ToolCall,
    ToolCallAction,
    ToolCallKey,
    ToolCallResult,
    WriteFileAction,
)
from tb_internet_use.tool_call.parse_shell_text import parse_shell_text

Channel = FileWriteChannel
Kind = FileUseKind
FINISHED = ToolCallResult(execution_status=ExecutionStatus.FINISHED)
NOT_RUN = ToolCallResult(execution_status=ExecutionStatus.NOT_RUN)
TOOL_WRITER = WrittenFileWriter(None, Channel.TOOL_ARGUMENT)

# Made-up rows, each named by the program and the cells that differ from the defaults of `conftest.py`. mytool has no row.
PROGRAM_BEHAVIOR_ROWS: list[dict[str, str]] = [
    {
        "program_name": "bash",
        "first_argument_role": "run_file",
        "stdin_role": "run_text",
        "options_end_at_first_argument": "yes",
    },
    {
        "program_name": "cat",
        "argument_role": "read_file",
        "stdin_role": "read_file",
        "visibility_of_piped_input": "whole",
    },
    {
        "program_name": "grep",
        "argument_role": "read_file",
        "first_argument_role": "pattern",
        "stdin_role": "read_file",
        "visibility_of_piped_input": "partial",
    },
    {
        "program_name": "tail",
        "argument_role": "read_file",
        "visibility_of_piped_input": "partial",
    },
    {
        "program_name": "tee",
        "argument_role": "written_file",
        "visibility_of_piped_input": "whole",
    },
    {"program_name": "tar", "first_argument_role": "option_cluster"},
    {"program_name": "ls", "argument_role": "size_or_type_file"},
    {
        "program_name": "sed",
        "argument_role": "read_file",
        "first_argument_role": "pattern",
    },
    {
        "program_name": "cp",
        "argument_role": "copy_source",
        "last_argument_role": "copy_destination",
    },
    {"program_name": "rm", "argument_role": "deleted_file"},
    {
        "program_name": "curl",
        "argument_role": "",
        "first_argument_role": "",
        "last_argument_role": "",
    },
    {"program_name": "echo"},
]
# Made-up rows, each named by the program, the option and the cells that differ from the defaults of `conftest.py`.
PROGRAM_OPTION_BEHAVIOR_ROWS: list[dict[str, str]] = [
    {"program_name": "tar", "option_name": "-x"},
    {"program_name": "tar", "option_name": "-z"},
    {
        "program_name": "tar",
        "option_name": "-f",
        "takes_value": "yes",
        "value_role": "used_file",
    },
    {"program_name": "ls", "option_name": "-l"},
    {
        "program_name": "sed",
        "option_name": "-i",
        "argument_role_with_option": "changed_file",
    },
    {"program_name": "curl", "option_name": "-s"},
    {
        "program_name": "curl",
        "option_name": "-o",
        "takes_value": "yes",
        "value_role": "written_file",
    },
]
# Made-up code runner rows, with the cells that differ from the defaults of `conftest.py`.
CODE_RUNNER_ROWS: list[dict[str, str]] = [
    {"runner_kind": "program_name", "runner": "bash"},
]


def _key(step_id: int) -> ToolCallKey:
    return ToolCallKey("trial", "main", step_id, 0)


K1, K2, K3, K4 = (_key(step_id) for step_id in (1, 2, 3, 4))


def _command(text: str) -> RunCommandAction:
    return RunCommandAction(
        text, parse_shell_text(text, judgment_rule_use_counts=Counter())
    )


def _call(
    step_id: int,
    action: ToolCallAction | str,
    result: ToolCallResult = FINISHED,
    *,
    is_subagent: bool = False,
) -> ToolCall:
    """Make a call at a step of the main trajectory, or of a subagent, taking a string as the command of a `RunCommandAction`."""
    return ToolCall(
        HarnessToolCall(
            _key(step_id),
            HarnessTool("harness", "tool"),
            "",
            {},
            None,
            is_subagent=is_subagent,
        ),
        _command(action) if isinstance(action, str) else action,
        result,
    )


def _calls(*actions: ToolCallAction | str) -> list[ToolCall]:
    """Make finished calls at steps 1, 2 and so on of the main trajectory."""
    return [_call(step_id, action) for step_id, action in enumerate(actions, 1)]


@pytest.fixture(scope="module")
def knowledge(catalogs_dir: Path) -> ExpandedToolCallKnowledge:
    return ExpandedToolCallKnowledge(catalogs_dir=catalogs_dir)


def _written_files(
    knowledge: ExpandedToolCallKnowledge, calls: list[ToolCall]
) -> tuple[tuple[WrittenFile, ...], ...]:
    """Expand the written files of calls from the file touches that the real `expand_ran_texts` records for them."""
    return expand_written_files(
        expand_ran_texts(
            calls,
            expand_poll_links(calls, judgment_rule_use_counts=Counter()),
            knowledge=knowledge,
            judgment_rule_use_counts=Counter(),
        )
    )


def test_a_downloaded_file_gets_every_later_use_with_its_kind(
    knowledge: ExpandedToolCallKnowledge,
):
    written_files = _written_files(
        knowledge,
        _calls(
            "curl -s -o a.tgz u",
            "tar xzf a.tgz",
            "ls -l a.tgz",
            "mytool a.tgz",
        ),
    )

    assert written_files == (
        (
            WrittenFile(
                "a.tgz",
                (WrittenFileWriter(0, Channel.OWN_OUTPUT_FILE),),
                (
                    FileUse(K2, 0, Kind.USES_CONTENT, False),
                    FileUse(K3, 0, Kind.SHOWS_SIZE_OR_TYPE, False),
                    FileUse(K4, 0, Kind.UNKNOWN, False),
                ),
            ),
        ),
        (),
        (),
        (),
    )


@pytest.mark.parametrize(
    ("writing_text", "using_text", "channel"),
    [
        ("curl u > log", "cat log", Channel.STDOUT),
        ("curl u 2> log", "grep error < log", Channel.STDERR),
        ("echo a | tee log", "tail log", Channel.STDOUT),
    ],
)
def test_a_redirected_or_teed_file_is_shown_by_a_later_call(
    knowledge: ExpandedToolCallKnowledge,
    writing_text: str,
    using_text: str,
    channel: FileWriteChannel,
):
    (written_files_of_writer, _) = _written_files(
        knowledge, _calls(writing_text, using_text)
    )

    assert written_files_of_writer == (
        WrittenFile(
            "log",
            (WrittenFileWriter(0, channel),),
            (FileUse(K2, 0, Kind.SHOWS_CONTENT, False),),
        ),
    )


def test_a_tool_written_file_that_a_later_command_runs_and_the_file_its_output_goes_to(
    knowledge: ExpandedToolCallKnowledge,
):
    written_files = _written_files(
        knowledge,
        _calls(WriteFileAction("fetch.sh", "curl a"), "bash fetch.sh > log"),
    )

    assert written_files == (
        (
            WrittenFile(
                "fetch.sh",
                (TOOL_WRITER,),
                (FileUse(K2, 0, Kind.USES_CONTENT, False),),
            ),
        ),
        (
            WrittenFile(
                "log",
                (
                    WrittenFileWriter(0, Channel.STDOUT),
                    WrittenFileWriter(1, Channel.STDOUT),
                ),
                (),
            ),
        ),
    )


def test_a_tool_written_file_read_by_a_command_and_by_a_read_tool(
    knowledge: ExpandedToolCallKnowledge,
):
    (written_files_of_writer, *_) = _written_files(
        knowledge,
        _calls(
            WriteFileAction("notes.md", "a"),
            "cat notes.md",
            ReadFileAction("notes.md"),
        ),
    )

    assert written_files_of_writer == (
        WrittenFile(
            "notes.md",
            (TOOL_WRITER,),
            (
                FileUse(K2, 0, Kind.SHOWS_CONTENT, False),
                FileUse(K3, None, Kind.SHOWS_CONTENT, False),
            ),
        ),
    )


def test_a_later_command_of_the_writing_call_uses_the_file(
    knowledge: ExpandedToolCallKnowledge,
):
    assert _written_files(knowledge, _calls("curl u > log; tail log")) == (
        (
            WrittenFile(
                "log",
                (WrittenFileWriter(0, Channel.STDOUT),),
                (FileUse(K1, 1, Kind.SHOWS_CONTENT, False),),
            ),
        ),
    )


@pytest.mark.parametrize(
    "texts",
    [
        ("curl -o a.tgz u",),
        ("cat log; echo a > log",),
        ("cat log", "echo a > log"),
    ],
    ids=["never used", "used before the write in its call", "used by an earlier call"],
)
def test_a_file_without_a_use_after_its_write_has_no_file_uses(
    knowledge: ExpandedToolCallKnowledge, texts: tuple[str, ...]
):
    written_files = _written_files(knowledge, _calls(*texts))

    assert [
        written_file.file_uses
        for written_files_of_call in written_files
        for written_file in written_files_of_call
    ] == [()]


def test_a_command_that_names_a_written_file_twice_is_one_use(
    knowledge: ExpandedToolCallKnowledge,
):
    (written_files_of_writer, _) = _written_files(
        knowledge, _calls("curl u > log", "cat log log")
    )

    assert written_files_of_writer == (
        WrittenFile(
            "log",
            (WrittenFileWriter(0, Channel.STDOUT),),
            (FileUse(K2, 0, Kind.SHOWS_CONTENT, False),),
        ),
    )


def test_a_download_to_dev_null_is_a_written_file_with_its_path_as_written(
    knowledge: ExpandedToolCallKnowledge,
):
    """Only `parse_shell_text` reads `/dev/null` as a discard, and only for a redirect, so the file a program writes keeps its path."""
    assert _written_files(knowledge, _calls("curl -o /dev/null u")) == (
        (
            WrittenFile(
                "/dev/null", (WrittenFileWriter(0, Channel.OWN_OUTPUT_FILE),), ()
            ),
        ),
    )


def test_a_use_belongs_to_the_write_before_it_and_not_to_one_that_a_later_write_replaced(
    knowledge: ExpandedToolCallKnowledge,
):
    written_files = _written_files(
        knowledge, _calls("echo a > log", "cat log", "echo b > log", "cat log")
    )

    assert [
        written_file.file_uses
        for written_files_of_call in written_files
        for written_file in written_files_of_call
    ] == [
        (FileUse(K2, 0, Kind.SHOWS_CONTENT, False),),
        (FileUse(K4, 0, Kind.SHOWS_CONTENT, False),),
    ]


def test_a_use_after_an_append_belongs_to_both_writes(
    knowledge: ExpandedToolCallKnowledge,
):
    (written_files_of_first, written_files_of_second, _) = _written_files(
        knowledge, _calls("echo a > log", "echo b >> log", "cat log")
    )

    assert written_files_of_first == (
        WrittenFile(
            "log",
            (WrittenFileWriter(0, Channel.STDOUT),),
            (FileUse(K3, 0, Kind.SHOWS_CONTENT, False),),
        ),
    )
    assert written_files_of_second == (
        WrittenFile(
            "log",
            (WrittenFileWriter(0, Channel.STDOUT),),
            (FileUse(K3, 0, Kind.SHOWS_CONTENT, False),),
        ),
    )


@pytest.mark.parametrize("is_use_of_each", [False, True])
def test_a_use_whose_path_fits_several_written_files_is_on_none_or_on_each_and_marked(
    knowledge: ExpandedToolCallKnowledge,
    monkeypatch: pytest.MonkeyPatch,
    is_use_of_each: bool,
):
    monkeypatch.setattr(
        _expand_ran_texts,
        treat_use_of_path_that_fits_several_written_files_as_use_of_none.__name__,
        lambda path, *, use_counts: not is_use_of_each,
    )
    written_files = _written_files(
        knowledge,
        _calls("echo a > /a/fetch.log", "echo b > /b/fetch.log", "cat fetch.log"),
    )

    file_uses = (FileUse(K3, 0, Kind.SHOWS_CONTENT, True),) if is_use_of_each else ()
    assert written_files == (
        (
            WrittenFile(
                "/a/fetch.log", (WrittenFileWriter(0, Channel.STDOUT),), file_uses
            ),
        ),
        (
            WrittenFile(
                "/b/fetch.log", (WrittenFileWriter(0, Channel.STDOUT),), file_uses
            ),
        ),
        (),
    )


@pytest.mark.parametrize(
    ("changing_action", "running_text", "written_files_of_changer"),
    [
        (
            "sed -i s/a/b/ f.sh",
            "bash f.sh",
            (
                WrittenFile(
                    "f.sh",
                    (WrittenFileWriter(0, Channel.OWN_OUTPUT_FILE),),
                    (FileUse(K3, 0, Kind.USES_CONTENT, False),),
                ),
            ),
        ),
        (
            EditFileAction("f.sh", "a", "b"),
            "bash f.sh",
            (
                WrittenFile(
                    "f.sh",
                    (TOOL_WRITER,),
                    (FileUse(K3, 0, Kind.USES_CONTENT, False),),
                ),
            ),
        ),
        (
            "cp f.sh g.sh",
            "bash g.sh",
            (
                WrittenFile(
                    "g.sh",
                    (WrittenFileWriter(0, Channel.OWN_OUTPUT_FILE),),
                    (FileUse(K3, 0, Kind.USES_CONTENT, False),),
                ),
            ),
        ),
    ],
    ids=["sed -i", "edit tool", "cp"],
)
def test_a_file_that_a_later_call_changes_or_copies_gives_the_run_to_that_call(
    knowledge: ExpandedToolCallKnowledge,
    changing_action: ToolCallAction | str,
    running_text: str,
    written_files_of_changer: tuple[WrittenFile, ...],
):
    written_files = _written_files(
        knowledge,
        _calls(WriteFileAction("f.sh", "curl a"), changing_action, running_text),
    )

    assert written_files == (
        (WrittenFile("f.sh", (TOOL_WRITER,), ()),),
        written_files_of_changer,
        (),
    )


def test_a_program_without_a_row_uses_the_file_without_replacing_its_write(
    knowledge: ExpandedToolCallKnowledge,
):
    (written_files_of_writer, *_) = _written_files(
        knowledge,
        _calls(WriteFileAction("f.sh", "curl a"), "mytool f.sh", "bash f.sh"),
    )

    assert written_files_of_writer == (
        WrittenFile(
            "f.sh",
            (TOOL_WRITER,),
            (
                FileUse(K2, 0, Kind.UNKNOWN, False),
                FileUse(K3, 0, Kind.USES_CONTENT, False),
            ),
        ),
    )


@pytest.mark.parametrize(
    "removing_action",
    [
        "rm f.sh",
        DeleteFileAction("f.sh"),
        ChangeFilesAction((DeleteFileAction("f.sh"),)),
    ],
    ids=["rm", "delete tool", "patch"],
)
def test_a_removal_is_no_use_and_ends_the_link_to_the_write(
    knowledge: ExpandedToolCallKnowledge, removing_action: ToolCallAction | str
):
    written_files = _written_files(
        knowledge, _calls(WriteFileAction("f.sh", "a"), removing_action, "cat f.sh")
    )

    assert written_files == ((WrittenFile("f.sh", (TOOL_WRITER,), ()),), (), ())


def test_a_call_that_did_not_run_lists_its_writes_without_uses_and_links_no_use(
    knowledge: ExpandedToolCallKnowledge,
):
    calls = [
        _call(1, "curl u > log; curl -o a.tgz u", NOT_RUN),
        _call(2, "cat log"),
        _call(3, "echo a > b.txt"),
        _call(4, "cat b.txt", NOT_RUN),
    ]

    assert _written_files(knowledge, calls) == (
        (
            WrittenFile("log", (WrittenFileWriter(0, Channel.STDOUT),), ()),
            WrittenFile("a.tgz", (WrittenFileWriter(1, Channel.OWN_OUTPUT_FILE),), ()),
        ),
        (),
        (WrittenFile("b.txt", (WrittenFileWriter(0, Channel.STDOUT),), ()),),
        (),
    )


WRITES_OF_ONE_CALL = (
    WriteFileAction("b.py", "x = 1"),
    WriteFileAction("a.py", "y = 2"),
    EditFileAction("b.py", "1", "3"),
)


@pytest.mark.parametrize(
    "action",
    [
        RunToolScriptAction(steps=WRITES_OF_ONE_CALL),
        ChangeFilesAction(WRITES_OF_ONE_CALL),
    ],
    ids=["tool script", "patch"],
)
def test_writes_of_one_call_make_one_written_file_per_path_in_first_write_order(
    knowledge: ExpandedToolCallKnowledge, action: ToolCallAction
):
    assert _written_files(knowledge, [_call(1, action)]) == (
        (
            WrittenFile("b.py", (TOOL_WRITER, TOOL_WRITER), ()),
            WrittenFile("a.py", (TOOL_WRITER,), ()),
        ),
    )


def test_a_file_written_by_a_subagent_is_used_only_by_calls_of_that_subagent(
    knowledge: ExpandedToolCallKnowledge,
):
    calls = [
        _call(1, WriteFileAction("f.sh", "a"), is_subagent=True),
        _call(2, "bash f.sh"),
        _call(3, "cat f.sh", is_subagent=True),
    ]

    (written_files_of_subagent_call, *_) = _written_files(knowledge, calls)

    assert written_files_of_subagent_call == (
        WrittenFile(
            "f.sh",
            (TOOL_WRITER,),
            (FileUse(K3, 0, Kind.SHOWS_CONTENT, False),),
        ),
    )


def _touch(
    kind: FileTouchKind,
    channel: FileWriteChannel | None,
    written_file_key: WrittenFileKey,
) -> FileTouch:
    """Make a touch of log by command 0 that meets one written file, for inputs that `expand_ran_texts` never gives."""
    return FileTouch(0, "log", kind, channel, (written_file_key,), False, ())


@pytest.mark.parametrize(
    "ran_texts_of_tool_calls",
    [
        (
            RanTextsOfToolCall(
                K1, (), (_touch(FileTouchKind.WRITES, None, WrittenFileKey(K1, "log")),)
            ),
        ),
        (
            RanTextsOfToolCall(
                K1,
                (),
                (
                    _touch(
                        FileTouchKind.WRITES, Channel.STDOUT, WrittenFileKey(K2, "log")
                    ),
                ),
            ),
            RanTextsOfToolCall(K2, (), ()),
        ),
        (
            RanTextsOfToolCall(
                K1,
                (),
                (_touch(FileTouchKind.SHOWS_CONTENT, None, WrittenFileKey(K2, "log")),),
            ),
        ),
    ],
    ids=[
        "write without a channel",
        "write that belongs to another call",
        "use of a file that no earlier write made",
    ],
)
def test_a_file_touch_that_breaks_what_expand_ran_texts_gives_fails(
    ran_texts_of_tool_calls: tuple[RanTextsOfToolCall, ...],
):
    with pytest.raises(ValueError):
        expand_written_files(ran_texts_of_tool_calls)
