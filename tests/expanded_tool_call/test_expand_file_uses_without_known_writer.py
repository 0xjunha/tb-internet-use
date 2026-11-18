"""Tests for expanded_tool_call/_expand_file_uses_without_known_writer.py, on made-up calls of one trial read by the real `expand_poll_links` and `expand_ran_texts` with a made-up program catalog whose rows the cases name."""

from collections import Counter
from pathlib import Path

import pytest

from tb_internet_use.expanded_tool_call._expand_file_uses_without_known_writer import (
    expand_file_uses_without_known_writer,
)
from tb_internet_use.expanded_tool_call._expand_poll_links import expand_poll_links
from tb_internet_use.expanded_tool_call._expand_ran_texts import (
    FileTouch,
    FileTouchKind,
    RanTextsOfToolCall,
    WrittenFileKey,
    expand_ran_texts,
)
from tb_internet_use.expanded_tool_call.model import (
    FileUseKind,
    FileUseWithoutKnownWriter,
)
from tb_internet_use.knowledge.expanded_tool_call_knowledge import (
    ExpandedToolCallKnowledge,
)
from tb_internet_use.tool_call.model import (
    DeleteFileAction,
    EditFileAction,
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    ReadFileAction,
    RunCommandAction,
    SearchFilesAction,
    ToolCall,
    ToolCallAction,
    ToolCallKey,
    ToolCallResult,
    WriteFileAction,
)
from tb_internet_use.tool_call.parse_shell_text import parse_shell_text

Use = FileUseWithoutKnownWriter
Kind = FileUseKind
FINISHED = ToolCallResult(execution_status=ExecutionStatus.FINISHED)
NOT_RUN = ToolCallResult(execution_status=ExecutionStatus.NOT_RUN)

# Made-up rows, each named by the program and the cells that differ from the defaults of `conftest.py`. mytool has no row.
PROGRAM_BEHAVIOR_ROWS: list[dict[str, str]] = [
    {
        "program_name": "bash",
        "first_argument_role": "run_file",
        "stdin_role": "run_text",
        "options_end_at_first_argument": "yes",
    },
    {"program_name": "make", "default_run_file": "Makefile"},
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
    {"program_name": "ls", "argument_role": "size_or_type_file"},
    {"program_name": "tar", "first_argument_role": "option_cluster"},
    {"program_name": "rm", "argument_role": "deleted_file"},
    {"program_name": "cd"},
    {"program_name": "echo"},
    {
        "program_name": "curl",
        "argument_role": "",
        "first_argument_role": "",
        "last_argument_role": "",
    },
]
# Made-up rows, each named by the program, the option and the cells that differ from the defaults of `conftest.py`.
PROGRAM_OPTION_BEHAVIOR_ROWS: list[dict[str, str]] = [
    {"program_name": "ls", "option_name": "-l"},
    {"program_name": "tar", "option_name": "-x"},
    {"program_name": "tar", "option_name": "-z"},
    {
        "program_name": "tar",
        "option_name": "-f",
        "takes_value": "yes",
        "value_role": "used_file",
    },
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
    {"runner_kind": "file_extension", "runner": ".sh"},
]

# (case id, the actions of the calls of one trial in order, the uses without a known writer of each call)
CASES: list[tuple[str, list[ToolCallAction | str], list[tuple[Use, ...]]]] = [
    (
        "a command shows a file of the task",
        ["cat README.md"],
        [(Use(0, "README.md", Kind.SHOWS_CONTENT),)],
    ),
    (
        "a read tool shows a file of the task",
        [ReadFileAction("README.md")],
        [(Use(None, "README.md", Kind.SHOWS_CONTENT),)],
    ),
    (
        "a search tool shows each of its files in order",
        [SearchFilesAction(("src/b.py", "src/a.py"))],
        [
            (
                Use(None, "src/b.py", Kind.SHOWS_CONTENT),
                Use(None, "src/a.py", Kind.SHOWS_CONTENT),
            )
        ],
    ),
    (
        "a run of a file of the task, of the default run file and of a file run by its path",
        ["bash setup.sh", "make", "./a.out"],
        [
            (Use(0, "setup.sh", Kind.USES_CONTENT),),
            (Use(0, "Makefile", Kind.USES_CONTENT),),
            (Use(0, "./a.out", Kind.USES_CONTENT),),
        ],
    ),
    (
        "a size, an archive that is unpacked and a stdin file",
        ["ls -l a.tgz", "tar xzf a.tgz", "grep error < build.log"],
        [
            (Use(0, "a.tgz", Kind.SHOWS_SIZE_OR_TYPE),),
            (Use(0, "a.tgz", Kind.USES_CONTENT),),
            (Use(0, "build.log", Kind.SHOWS_CONTENT),),
        ],
    ),
    (
        "a later command of a text and a repeated word in one command",
        ["cd /app && cat b.txt a.txt b.txt; cat b.txt"],
        [
            (
                Use(1, "b.txt", Kind.SHOWS_CONTENT),
                Use(1, "a.txt", Kind.SHOWS_CONTENT),
                Use(2, "b.txt", Kind.SHOWS_CONTENT),
            )
        ],
    ),
    (
        "a use before any write, in a later call and in the same call",
        ["cat log", "curl u > log", "cat out; curl u > out"],
        [
            (Use(0, "log", Kind.SHOWS_CONTENT),),
            (),
            (Use(0, "out", Kind.SHOWS_CONTENT),),
        ],
    ),
    (
        "uses of files that a redirect, a write tool and a program wrote",
        [
            "curl u > log",
            "cat log",
            WriteFileAction("notes.md", "x"),
            ReadFileAction("notes.md"),
            "curl -o a.tgz u",
            "tar xzf a.tgz",
        ],
        [(), (), (), (), (), ()],
    ),
    (
        "a command of a written file uses a file of the task",
        [WriteFileAction("f.sh", "cat notes.txt"), "bash f.sh"],
        [(), (Use(1, "notes.txt", Kind.SHOWS_CONTENT),)],
    ),
    (
        "a use after the file was deleted by a command and by a tool",
        [
            WriteFileAction("f.sh", "x"),
            "rm f.sh",
            "cat f.sh",
            WriteFileAction("g.sh", "x"),
            DeleteFileAction("g.sh"),
            ReadFileAction("g.sh"),
        ],
        [
            (),
            (),
            (Use(0, "f.sh", Kind.SHOWS_CONTENT),),
            (),
            (),
            (Use(None, "g.sh", Kind.SHOWS_CONTENT),),
        ],
    ),
    (
        "writes, an edit and removals of files of the task are no uses",
        [
            "echo x > out.txt",
            EditFileAction("README.md", "a", "b"),
            "rm old.txt",
            DeleteFileAction("older.txt"),
        ],
        [(), (), (), ()],
    ),
    (
        "a word that no fact covers and that names no written file",
        ["mytool README.md"],
        [()],
    ),
    (
        "a search of a folder that holds a written file",
        [WriteFileAction("scripts/f.sh", "x"), SearchFilesAction(("scripts",))],
        [(), (Use(None, "scripts", Kind.SHOWS_CONTENT),)],
    ),
]


def _key(step_id: int, *, trajectory_id: str = "main") -> ToolCallKey:
    return ToolCallKey("trial", trajectory_id, step_id, 0)


def _call(
    step_id: int,
    action: ToolCallAction | str,
    result: ToolCallResult | None = FINISHED,
    *,
    trajectory_id: str = "main",
    is_subagent: bool = False,
) -> ToolCall:
    """Make a call at a step of a trajectory, taking a string as the command of a `RunCommandAction`."""
    return ToolCall(
        HarnessToolCall(
            _key(step_id, trajectory_id=trajectory_id),
            HarnessTool("harness", "tool"),
            "",
            {},
            None,
            is_subagent=is_subagent,
        ),
        RunCommandAction(
            action, parse_shell_text(action, judgment_rule_use_counts=Counter())
        )
        if isinstance(action, str)
        else action,
        result,
    )


@pytest.fixture(scope="module")
def knowledge(catalogs_dir: Path) -> ExpandedToolCallKnowledge:
    return ExpandedToolCallKnowledge(catalogs_dir=catalogs_dir)


def _expand(
    knowledge: ExpandedToolCallKnowledge, *calls: ToolCall
) -> tuple[tuple[FileUseWithoutKnownWriter, ...], ...]:
    """Expand the uses without a known writer of calls from the file touches that the real earlier pieces record for them."""
    return expand_file_uses_without_known_writer(
        expand_ran_texts(
            calls,
            expand_poll_links(calls, judgment_rule_use_counts=Counter()),
            knowledge=knowledge,
            judgment_rule_use_counts=Counter(),
        )
    )


@pytest.mark.parametrize(
    ("actions", "expected"),
    [case[1:] for case in CASES],
    ids=[case[0] for case in CASES],
)
def test_uses_without_a_known_writer_of_each_call(
    knowledge: ExpandedToolCallKnowledge,
    actions: list[ToolCallAction | str],
    expected: list[tuple[Use, ...]],
):
    calls = [_call(step_id, action) for step_id, action in enumerate(actions, 1)]

    assert list(_expand(knowledge, *calls)) == expected


def test_a_call_that_did_not_run_uses_no_file_and_its_writes_leave_later_uses_without_writer(
    knowledge: ExpandedToolCallKnowledge,
):
    results = _expand(
        knowledge,
        _call(1, "curl u > log; cat README.md", NOT_RUN),
        _call(2, ReadFileAction("notes.md"), NOT_RUN),
        _call(3, "cat log"),
    )

    assert results == ((), (), (Use(0, "log", Kind.SHOWS_CONTENT),))


def test_reads_of_a_harness_output_file_are_left_out_only_after_its_call(
    knowledge: ExpandedToolCallKnowledge,
):
    with_output_path = ToolCallResult(
        execution_status=ExecutionStatus.RUNNING, output_path="/tmp/out1.txt"
    )

    results = _expand(
        knowledge,
        _call(1, "cat /tmp/out1.txt"),
        _call(2, "make", with_output_path),
        _call(3, ReadFileAction("/tmp/out1.txt")),
        _call(4, SearchFilesAction(("/tmp/out1.txt",))),
        _call(5, "cat /tmp/out1.txt /tmp/out2.txt"),
    )

    assert results == (
        (Use(0, "/tmp/out1.txt", Kind.SHOWS_CONTENT),),
        (Use(0, "Makefile", Kind.USES_CONTENT),),
        (),
        (),
        (Use(0, "/tmp/out2.txt", Kind.SHOWS_CONTENT),),
    )


@pytest.mark.parametrize(
    ("trajectory_id", "is_subagent"),
    [("main", True), ("main/sub0", False)],
    ids=["subagent calls marked in main", "subagent calls in their own trajectory"],
)
def test_a_file_that_only_another_trajectory_wrote_has_no_known_writer(
    knowledge: ExpandedToolCallKnowledge, trajectory_id: str, is_subagent: bool
):
    results = _expand(
        knowledge,
        _call(
            1,
            WriteFileAction("f.sh", "x"),
            trajectory_id=trajectory_id,
            is_subagent=is_subagent,
        ),
        _call(2, "bash f.sh"),
        _call(3, "bash f.sh", trajectory_id=trajectory_id, is_subagent=is_subagent),
    )

    assert results == ((), (Use(0, "f.sh", Kind.USES_CONTENT),), ())


def test_a_touch_of_unknown_use_without_written_file_is_a_use_of_unknown_kind():
    written_file_key = WrittenFileKey(_key(1), "f.sh")
    ran_texts_of_tool_call = RanTextsOfToolCall(
        _key(2),
        (),
        (
            FileTouch(0, "data.bin", FileTouchKind.UNKNOWN_USE, None, (), False, ()),
            FileTouch(
                1,
                "f.sh",
                FileTouchKind.UNKNOWN_USE,
                None,
                (written_file_key,),
                False,
                (),
            ),
        ),
    )

    assert expand_file_uses_without_known_writer([ran_texts_of_tool_call]) == (
        (Use(0, "data.bin", Kind.UNKNOWN),),
    )
