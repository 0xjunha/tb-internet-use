"""Tests for expanded_tool_call/_expand_ran_texts.py, on made-up calls of one trial and a made-up program catalog whose rows the cases name, so that a case does not change when the real catalog gains rows."""

from collections import Counter
from collections.abc import Sequence
from pathlib import Path

import pytest

from tb_internet_use.expanded_tool_call import _expand_ran_texts
from tb_internet_use.expanded_tool_call._expand_poll_links import expand_poll_links
from tb_internet_use.expanded_tool_call._expand_ran_texts import (
    FileTouch,
    FileTouchKind,
    RanTextsOfToolCall,
    TrialFileContents,
    WrittenFileKey,
    expand_ran_texts,
)
from tb_internet_use.expanded_tool_call.judgment_rules import (
    treat_calls_of_other_trajectory_as_not_linked,
    treat_copy_with_two_arguments_as_unknown_content,
    treat_file_without_interpreter_line_as_of_unknown_language,
    treat_typed_text_as_of_unknown_language,
    treat_use_of_path_that_fits_several_written_files_as_use_of_none,
)
from tb_internet_use.expanded_tool_call.model import (
    ArgumentText,
    CallCommandText,
    CodeLanguage,
    FileText,
    FileTextWithoutKnownWriter,
    FileWriteChannel,
    PollInputText,
    RanCodeText,
    RanShellText,
    RanText,
    ScriptStepText,
    StdinText,
    UnknownRanText,
    UnknownRanTextReason,
    VariableValues,
)
from tb_internet_use.knowledge.expanded_tool_call_knowledge import (
    ExpandedToolCallKnowledge,
)
from tb_internet_use.tool_call.model import (
    DeleteFileAction,
    EditFileAction,
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    PollAction,
    ReadFileAction,
    RunCommandAction,
    RunToolScriptAction,
    SearchFilesAction,
    ToolCall,
    ToolCallAction,
    ToolCallKey,
    ToolCallResult,
    UnknownAction,
    WriteFileAction,
)
from tb_internet_use.tool_call.parse_shell_text import parse_shell_text

Reason = UnknownRanTextReason
Channel = FileWriteChannel
Kind = FileTouchKind
FINISHED = ToolCallResult(execution_status=ExecutionStatus.FINISHED)
NOT_RUN = ToolCallResult(execution_status=ExecutionStatus.NOT_RUN)
HANDLE = ExecutionHandle(ExecutionHandleKind.COMMAND, "h1")
RUNNING = ToolCallResult(execution_status=ExecutionStatus.RUNNING, handles=(HANDLE,))
OTHER_TRAJECTORY_RULE_NAME = treat_calls_of_other_trajectory_as_not_linked.__name__
COPY_RULE_NAME = treat_copy_with_two_arguments_as_unknown_content.__name__
EXTENSION_RULE_NAME = (
    treat_file_without_interpreter_line_as_of_unknown_language.__name__
)
TYPED_TEXT_LANGUAGE_RULE_NAME = treat_typed_text_as_of_unknown_language.__name__
SEVERAL_WRITTEN_FILES_USE_RULE_NAME = (
    treat_use_of_path_that_fits_several_written_files_as_use_of_none.__name__
)
OVERWRITE_RULE_NAME = (
    "treat_use_after_overwrite_that_may_not_have_happened_as_use_without_known_writer"
)

# Made-up rows, each named by the program and the cells that differ from the defaults of `conftest.py`. mytool, gdb and test have no row, and the row of echo gives its words no file role.
PROGRAM_BEHAVIOR_ROWS: list[dict[str, str]] = [
    {
        "program_name": "bash",
        "first_argument_role": "run_file",
        "stdin_role": "run_text",
        "options_end_at_first_argument": "yes",
    },
    {
        "program_name": "python",
        "first_argument_role": "run_file",
        "stdin_role": "run_text",
        "options_end_at_first_argument": "yes",
        "name_may_end_with_version": "yes",
    },
    {
        "program_name": "sudo",
        "argument_role": "program",
        "options_end_at_first_argument": "yes",
    },
    {
        "program_name": "eval",
        "argument_role": "run_text",
        "options_end_at_first_argument": "yes",
        "runs_text_in_calling_shell": "yes",
    },
    {"program_name": "make", "default_run_file": "Makefile"},
    {
        "program_name": "cat",
        "argument_role": "read_file",
        "stdin_role": "read_file",
        "visibility_of_piped_input": "whole",
    },
    {
        "program_name": "tee",
        "argument_role": "written_file",
        "visibility_of_piped_input": "whole",
    },
    {
        "program_name": "tail",
        "argument_role": "read_file",
        "visibility_of_piped_input": "partial",
    },
    {
        "program_name": "grep",
        "argument_role": "read_file",
        "first_argument_role": "pattern",
        "stdin_role": "read_file",
        "visibility_of_piped_input": "partial",
    },
    {
        "program_name": "sed",
        "argument_role": "read_file",
        "first_argument_role": "pattern",
    },
    {"program_name": "ls", "argument_role": "size_or_type_file"},
    {"program_name": "chmod"},
    {
        "program_name": "cp",
        "argument_role": "copy_source",
        "last_argument_role": "copy_destination",
    },
    {"program_name": "rm", "argument_role": "deleted_file"},
    {
        "program_name": "apply_patch",
        "argument_role": "patch_text",
        "stdin_role": "patch_text",
        "options_end_at_first_argument": "yes",
    },
    {
        "program_name": "curl",
        "argument_role": "",
        "first_argument_role": "",
        "last_argument_role": "",
    },
    {
        "program_name": "xargs",
        "argument_role": "program",
        "gives_arguments_at_run_time": "yes",
        "options_end_at_first_argument": "yes",
    },
    {"program_name": "find", "takes_one_letter_options_joined": "no"},
    {"program_name": "tar", "first_argument_role": "option_cluster"},
    {"program_name": "echo"},
    {"program_name": "read", "argument_role": "variable_name_set_at_run_time"},
    {"program_name": "node", "stdin_role": ""},
    {"program_name": "php", "argument_role": "", "stdin_role": "run_text"},
    # deno runs files, and no fact says which file it runs when its words name none.
    {"program_name": "deno", "first_argument_role": "run_file", "default_run_file": ""},
    # git runs no file that its words name, and no fact says which file it runs by default.
    {"program_name": "git", "default_run_file": ""},
]
# Made-up rows, each named by the program, the option and the cells that differ from the defaults of `conftest.py`.
PROGRAM_OPTION_BEHAVIOR_ROWS: list[dict[str, str]] = [
    {
        "program_name": "bash",
        "option_name": "-c",
        "first_argument_role_with_option": "run_text",
    },
    {"program_name": "bash", "option_name": "-e"},
    {
        "program_name": "bash",
        "option_name": "-n",
        "first_argument_role_with_option": "",
    },
    {
        "program_name": "bash",
        "option_name": "-O",
        "takes_value": "yes",
        "value_role": "",
    },
    {
        "program_name": "find",
        "option_name": "-exec",
        "argument_role_with_option": "program",
        "gives_arguments_at_run_time": "yes",
        "next_program_end_words": ";",
    },
    {
        "program_name": "find",
        "option_name": "-path",
        "takes_value": "yes",
        "value_role": "pattern",
    },
    {"program_name": "tar", "option_name": "-x"},
    {"program_name": "tar", "option_name": "-z"},
    {
        "program_name": "tar",
        "option_name": "-f",
        "takes_value": "yes",
        "value_role": "used_file",
    },
    {
        "program_name": "python",
        "option_name": "-c",
        "first_argument_role_with_option": "run_text",
    },
    {"program_name": "cat", "option_name": "-n"},
    {
        "program_name": "tee",
        "option_name": "-a",
        "argument_role_with_option": "appended_file",
    },
    {
        "program_name": "sed",
        "option_name": "-i",
        "argument_role_with_option": "changed_file",
    },
    {
        "program_name": "sed",
        "option_name": "-e",
        "takes_value": "yes",
        "value_role": "pattern",
        "first_argument_role_with_option": "same",
    },
    {"program_name": "ls", "option_name": "-l"},
    {"program_name": "rm", "option_name": "-r"},
    {"program_name": "rm", "option_name": "-f"},
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
    {"runner_kind": "program_name", "runner": "eval"},
    {
        "runner_kind": "program_name",
        "runner": "python",
        "ran_text_language": "python",
    },
    {
        "runner_kind": "file_extension",
        "runner": ".py",
        "ran_text_language": "python",
    },
    {"runner_kind": "file_extension", "runner": ".sh"},
]


def _key(step_id: int, *, trajectory_id: str = "main") -> ToolCallKey:
    return ToolCallKey("trial", trajectory_id, step_id, 0)


K1, K2, K3, K4 = (_key(step_id) for step_id in (1, 2, 3, 4))


def _command(text: str | None) -> RunCommandAction:
    if text is None:
        return RunCommandAction()
    return RunCommandAction(
        text, parse_shell_text(text, judgment_rule_use_counts=Counter())
    )


def _call(
    step_id: int,
    action: ToolCallAction | str,
    result: ToolCallResult | None = FINISHED,
    *,
    is_subagent: bool = False,
) -> ToolCall:
    """Make a call at a step of the main trajectory, taking a string as the command of a `RunCommandAction`."""
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


@pytest.fixture(scope="module")
def knowledge(catalogs_dir: Path) -> ExpandedToolCallKnowledge:
    return ExpandedToolCallKnowledge(catalogs_dir=catalogs_dir)


def _answer(monkeypatch: pytest.MonkeyPatch, rule_name: str, answer: bool) -> None:
    """Make a rule that `expand_ran_texts` asks give an answer, e.g. the other one."""
    monkeypatch.setattr(_expand_ran_texts, rule_name, lambda *_, use_counts: answer)


def _expand(
    knowledge: ExpandedToolCallKnowledge,
    *calls: ToolCall,
    judgment_rule_use_counts: Counter[str] | None = None,
) -> tuple[RanTextsOfToolCall, ...]:
    """Expand the texts of calls with the poll links that `expand_poll_links` gives for them."""
    return expand_ran_texts(
        calls,
        expand_poll_links(calls, judgment_rule_use_counts=Counter()),
        knowledge=knowledge,
        judgment_rule_use_counts=Counter()
        if judgment_rule_use_counts is None
        else judgment_rule_use_counts,
    )


def _texts_with_words(
    ran_texts: Sequence[RanText],
) -> list[tuple[object, tuple[tuple[str, ...], ...] | str]]:
    """Give each text as its source and the words of its commands, its code, or its reason."""
    described: list[tuple[object, tuple[tuple[str, ...], ...] | str]] = []
    for ran_text in ran_texts:
        if isinstance(ran_text, RanShellText):
            described.append(
                (
                    ran_text.source,
                    tuple(
                        ran_command.shell_command.words
                        for ran_command in ran_text.ran_commands
                    ),
                )
            )
        elif isinstance(ran_text, RanCodeText):
            described.append(
                (ran_text.source, f"{ran_text.code_language}:{ran_text.code}")
            )
        else:
            described.append((ran_text.source, ran_text.reason))
    return described


def _last_text(knowledge: ExpandedToolCallKnowledge, *calls: ToolCall) -> RanText:
    return _expand(knowledge, *calls)[-1].ran_texts[-1]


def _touch(
    command_id: int | None,
    path: str,
    kind: FileTouchKind,
    *written_file_keys: WrittenFileKey,
    channel: FileWriteChannel | None = None,
    fits_several_written_files: bool = False,
    harness_output_file_tool_call_keys: tuple[ToolCallKey, ...] = (),
) -> FileTouch:
    return FileTouch(
        command_id,
        path,
        kind,
        channel,
        written_file_keys,
        fits_several_written_files,
        harness_output_file_tool_call_keys,
    )


# (case id, the command after an earlier call wrote `curl a` to f.sh, the result of its call, the file that the next `bash` runs, its commands or the reason they cannot be followed, the call that wrote it last)
FILE_CHANGE_CASES = [
    ("read only", "cat f.sh", FINISHED, "f.sh", (("curl", "a"),), K1),
    ("chmod with a row", "chmod +x f.sh", FINISHED, "f.sh", (("curl", "a"),), K1),
    (
        "program without a row",
        "mytool f.sh",
        FINISHED,
        "f.sh",
        Reason.CHANGED_BY_UNREAD_COMMAND,
        K1,
    ),
    (
        "changed in place",
        "sed -i s/a/b/ f.sh",
        FINISHED,
        "f.sh",
        Reason.CHANGED_BY_UNREAD_COMMAND,
        K2,
    ),
    (
        "changed in place after -e",
        "sed -i -e s/a/b/ f.sh",
        FINISHED,
        "f.sh",
        Reason.CHANGED_BY_UNREAD_COMMAND,
        K2,
    ),
    (
        "downloaded over it",
        "curl -o f.sh u",
        FINISHED,
        "f.sh",
        Reason.CHANGED_BY_UNREAD_COMMAND,
        K2,
    ),
    (
        "redirect of unknown content",
        "echo x > f.sh",
        FINISHED,
        "f.sh",
        Reason.CHANGED_BY_UNREAD_COMMAND,
        K2,
    ),
    (
        "appended",
        "cat >> f.sh <<EOF\ncurl b\nEOF",
        FINISHED,
        "f.sh",
        Reason.CHANGED_BY_UNREAD_COMMAND,
        K2,
    ),
    # The glob may name f.sh, which keeps its writer while its content is unknown.
    (
        "glob",
        "sed -i s/a/b/ *.sh",
        FINISHED,
        "f.sh",
        Reason.CHANGED_BY_UNREAD_COMMAND,
        K1,
    ),
    ("copied", "cp f.sh g.sh", FINISHED, "g.sh", Reason.CHANGED_BY_UNREAD_COMMAND, K2),
    (
        "heredoc of cat",
        "cat > g.sh <<EOF\ncurl b\nEOF",
        FINISHED,
        "g.sh",
        (("curl", "b"),),
        K2,
    ),
    (
        "heredoc of tee",
        "tee g.sh <<EOF\ncurl b\nEOF",
        FINISHED,
        "g.sh",
        (("curl", "b"),),
        K2,
    ),
    (
        "heredoc of cat with an option",
        "cat -n > g.sh <<EOF\ncurl b\nEOF",
        FINISHED,
        "g.sh",
        Reason.CHANGED_BY_UNREAD_COMMAND,
        K2,
    ),
    (
        "heredoc of cat with a variable under an unquoted delimiter",
        "cat > g.sh <<EOF\ncurl $HOME\nEOF",
        FINISHED,
        "g.sh",
        Reason.CHANGED_BY_UNREAD_COMMAND,
        K2,
    ),
    (
        "heredoc of tee with a command substitution under an unquoted delimiter",
        "tee g.sh <<EOF\ncurl $(cat u.txt)\nEOF",
        FINISHED,
        "g.sh",
        Reason.CHANGED_BY_UNREAD_COMMAND,
        K2,
    ),
    (
        "heredoc of cat with a backtick under an unquoted delimiter",
        "cat > g.sh <<EOF\ncurl `cat u.txt`\nEOF",
        FINISHED,
        "g.sh",
        Reason.CHANGED_BY_UNREAD_COMMAND,
        K2,
    ),
    (
        "heredoc of cat with a variable under an unquoted delimiter of <<-",
        "cat > g.sh <<-EOF\n\tcurl ${U}\n\tEOF",
        FINISHED,
        "g.sh",
        Reason.CHANGED_BY_UNREAD_COMMAND,
        K2,
    ),
    (
        "heredoc of cat with a variable under a quoted delimiter",
        "cat > g.sh <<'EOF'\ncurl $HOME\nEOF",
        FINISHED,
        "g.sh",
        (("curl", "$HOME"),),
        K2,
    ),
    (
        "heredoc of cat with an escaped variable under an unquoted delimiter",
        "cat > g.sh <<EOF\ncurl \\$HOME\nEOF",
        FINISHED,
        "g.sh",
        (("curl", "$HOME"),),
        K2,
    ),
    (
        "heredoc of cat with an escaped backslash under an unquoted delimiter",
        "cat > g.sh <<EOF\necho a\\\\b\nEOF",
        FINISHED,
        "g.sh",
        (("echo", "ab"),),
        K2,
    ),
    (
        "heredoc of cat with a dollar that starts no expansion",
        'cat > g.sh <<EOF\necho "cost is 5$"\nEOF',
        FINISHED,
        "g.sh",
        (("echo", "cost is 5$"),),
        K2,
    ),
    (
        "heredoc of cat with a positional parameter under an unquoted delimiter",
        "cat > g.sh <<EOF\ncurl $1\nEOF",
        FINISHED,
        "g.sh",
        Reason.CHANGED_BY_UNREAD_COMMAND,
        K2,
    ),
    (
        "heredoc of cat with all parameters under an unquoted delimiter",
        "cat > g.sh <<EOF\ncurl $@\nEOF",
        FINISHED,
        "g.sh",
        Reason.CHANGED_BY_UNREAD_COMMAND,
        K2,
    ),
    (
        "heredoc of cat with an escaped backslash before a variable",
        "cat > g.sh <<EOF\ncurl \\\\$U\nEOF",
        FINISHED,
        "g.sh",
        Reason.CHANGED_BY_UNREAD_COMMAND,
        K2,
    ),
    (
        "heredoc of cat with a backslash and line break inside single quotes",
        "cat > g.sh <<EOF\necho 'a\\\nb'\nEOF",
        FINISHED,
        "g.sh",
        (("echo", "ab"),),
        K2,
    ),
    (
        "heredoc of cat keeps the backslash before a double quote",
        'cat > g.sh <<EOF\necho "a\\"b"\nEOF',
        FINISHED,
        "g.sh",
        (("echo", 'a"b'),),
        K2,
    ),
    (
        "heredoc of cat drops the backslash before a backtick",
        "cat > g.sh <<EOF\necho \\`x\\`\nEOF",
        FINISHED,
        "g.sh",
        (("echo", "`x`"), ("x",)),
        K2,
    ),
    (
        "herestring of cat with a command substitution",
        'cat <<< "curl $(cat u.txt)" > g.sh',
        FINISHED,
        "g.sh",
        Reason.CHANGED_BY_UNREAD_COMMAND,
        K2,
    ),
    (
        "herestring of cat without an expansion",
        "cat <<< 'curl b' > g.sh",
        FINISHED,
        "g.sh",
        (("curl", "b"),),
        K2,
    ),
    (
        "cat of another file",
        "cat f.sh > g.sh <<EOF\ncurl b\nEOF",
        FINISHED,
        "g.sh",
        Reason.CHANGED_BY_UNREAD_COMMAND,
        K2,
    ),
    (
        "in a call that did not run",
        "echo x > f.sh",
        NOT_RUN,
        "f.sh",
        (("curl", "a"),),
        K1,
    ),
]


# (case id, text typed into the handle that the starting call started, the command of the starting call or None when no call started it, the expected texts of the poll)
# On the other answer of `treat_typed_text_as_of_unknown_language`, the reader of typed text is the innermost program of the last command of the starting call.
TYPED_TEXT_CASES = [
    ("shell", "curl u\n", "bash", [(PollInputText(None, K1), (("curl", "u"),))]),
    ("code", "import x\n", "python3", [(PollInputText(None, K1), "python:import x\n")]),
    (
        "program without a row",
        "run\n",
        "cd /app && gdb ./a.out",
        [(PollInputText(None, K1), Reason.LANGUAGE_NOT_KNOWN)],
    ),
    (
        "no starter",
        "ls\n",
        None,
        [(PollInputText(None, None), Reason.LANGUAGE_NOT_KNOWN)],
    ),
    ("stdin that runs nothing", "hello\n", "cat > notes.txt", []),
    (
        "last command of several",
        "curl u\n",
        "python3 x.py; bash",
        [(PollInputText(None, K1), (("curl", "u"),))],
    ),
    (
        "innermost program of the last command",
        "curl u\n",
        "sudo bash",
        [(PollInputText(None, K1), (("curl", "u"),))],
    ),
    (
        "shell that runs a file",
        "y\n",
        "bash install.sh",
        [(PollInputText(None, K1), Reason.LANGUAGE_NOT_KNOWN)],
    ),
    (
        "code runner that runs a file",
        "yes\n",
        "python3 get.py",
        [(PollInputText(None, K1), Reason.LANGUAGE_NOT_KNOWN)],
    ),
    ("key presses only", "\n", "bash", []),
    (
        "program whose row leaves the role of stdin blank",
        "run\n",
        "node",
        [(PollInputText(None, K1), Reason.LANGUAGE_NOT_KNOWN)],
    ),
]


def test_text_in_an_argument_is_followed_with_ids_after_those_of_the_call(
    knowledge: ExpandedToolCallKnowledge,
):
    (ran_texts_of_tool_call,) = _expand(knowledge, _call(1, "sudo bash -c 'curl u'"))

    assert _texts_with_words(ran_texts_of_tool_call.ran_texts) == [
        (CallCommandText(), (("sudo", "bash", "-c", "curl u"),)),
        (ArgumentText(0), (("curl", "u"),)),
    ]
    inner_text = ran_texts_of_tool_call.ran_texts[1]
    assert isinstance(inner_text, RanShellText)
    assert inner_text.ran_commands[0].shell_command.id == 1


def test_file_written_by_an_earlier_tool_is_followed_and_its_writes_and_uses_recorded(
    knowledge: ExpandedToolCallKnowledge,
):
    write, run = _expand(
        knowledge,
        _call(1, WriteFileAction("fetch.sh", "curl a")),
        _call(2, "bash fetch.sh > log"),
    )

    assert write.file_touches == (
        _touch(
            None,
            "fetch.sh",
            Kind.WRITES,
            WrittenFileKey(K1, "fetch.sh"),
            channel=Channel.TOOL_ARGUMENT,
        ),
    )
    assert _texts_with_words(run.ran_texts)[1] == (
        FileText(0, "fetch.sh", K1),
        (("curl", "a"),),
    )
    log = WrittenFileKey(K2, "log")
    assert run.file_touches == (
        _touch(0, "log", Kind.WRITES, log, channel=Channel.STDOUT),
        _touch(0, "fetch.sh", Kind.USES_CONTENT, WrittenFileKey(K1, "fetch.sh")),
        _touch(1, "log", Kind.WRITES, log, channel=Channel.STDOUT),
    )


def test_ids_of_a_file_text_come_after_all_commands_of_the_call(
    knowledge: ExpandedToolCallKnowledge,
):
    ran_text = _expand(
        knowledge,
        _call(1, WriteFileAction("fetch.sh", "curl a; curl b")),
        _call(2, "cd /app && bash fetch.sh"),
    )[-1].ran_texts[-1]

    assert isinstance(ran_text, RanShellText)
    assert [rc.shell_command.id for rc in ran_text.ran_commands] == [2, 3]


@pytest.mark.parametrize(
    ("shell_text", "ran_text"),
    [
        (
            "python - <<EOF\nimport x\nEOF",
            RanCodeText(StdinText(0), CodeLanguage.PYTHON, "import x\n"),
        ),
        (
            "python3 -c 'import x'",
            RanCodeText(ArgumentText(0), CodeLanguage.PYTHON, "import x"),
        ),
        ('bash -c "$CMD"', UnknownRanText(ArgumentText(0), Reason.BUILT_AT_RUN_TIME)),
        (
            'bash -c "$(curl u)"',
            UnknownRanText(ArgumentText(0), Reason.BUILT_AT_RUN_TIME),
        ),
        ("curl u | bash", UnknownRanText(StdinText(1), Reason.READ_FROM_PIPE)),
        (
            "mytool <<EOF\nrun\nEOF",
            UnknownRanText(StdinText(0), Reason.LANGUAGE_NOT_KNOWN),
        ),
        (
            "bash setup.sh",
            UnknownRanText(
                FileTextWithoutKnownWriter(0, "setup.sh"), Reason.NOT_WRITTEN_IN_TRIAL
            ),
        ),
        (
            "make",
            UnknownRanText(
                FileTextWithoutKnownWriter(0, None), Reason.NOT_WRITTEN_IN_TRIAL
            ),
        ),
        (
            "./a.out",
            UnknownRanText(
                FileTextWithoutKnownWriter(0, "./a.out"), Reason.NOT_WRITTEN_IN_TRIAL
            ),
        ),
        (
            "bash $F",
            UnknownRanText(
                FileTextWithoutKnownWriter(0, "$F"), Reason.BUILT_AT_RUN_TIME
            ),
        ),
        (")))", UnknownRanText(CallCommandText(), Reason.UNREADABLE_SHELL_TEXT)),
    ],
)
def test_last_text_of_a_command_alone(
    knowledge: ExpandedToolCallKnowledge, shell_text: str, ran_text: RanText
):
    assert _last_text(knowledge, _call(1, shell_text)) == ran_text


@pytest.mark.parametrize(
    "shell_text",
    [
        "mytool run x",
        "curl $(cat urls.txt)",
        "run.sh",
        "cat > notes.txt <<EOF\nhi\nEOF",
    ],
)
def test_a_command_that_runs_no_text_adds_none(
    knowledge: ExpandedToolCallKnowledge, shell_text: str
):
    (ran_texts_of_tool_call,) = _expand(knowledge, _call(1, shell_text))

    assert [type(ran_text.source) for ran_text in ran_texts_of_tool_call.ran_texts] == [
        CallCommandText
    ]


def test_heredoc_run_by_a_shell_and_the_command_text_of_a_script_step(
    knowledge: ExpandedToolCallKnowledge,
):
    (heredoc,) = _expand(knowledge, _call(1, "bash <<EOF\ncurl u\nEOF"))
    (script,) = _expand(
        knowledge,
        _call(1, RunToolScriptAction("...", (_command("ls"), _command(None)))),
    )

    assert _texts_with_words(heredoc.ran_texts)[1] == (StdinText(0), (("curl", "u"),))
    assert _texts_with_words(script.ran_texts) == [
        (ScriptStepText(0), (("ls",),)),
        (ScriptStepText(1), Reason.MISSING_FROM_TRAJECTORY),
    ]


# (case id, a command whose shell reads its heredoc or herestring as stdin, the commands of that stdin text or the reason they cannot be followed)
STDIN_TEXT_CASES = [
    (
        "unquoted heredoc with a command substitution",
        "bash <<EOF\necho $(curl u)\nEOF",
        Reason.BUILT_AT_RUN_TIME,
    ),
    (
        "unquoted heredoc of python with a variable",
        'python - <<EOF\nprint("$HOME")\nEOF',
        Reason.BUILT_AT_RUN_TIME,
    ),
    (
        "quoted heredoc with a command substitution",
        "bash <<'EOF'\necho $(curl u)\nEOF",
        (("echo", "$(curl u)"), ("curl", "u")),
    ),
    (
        "unquoted heredoc with an escaped variable inside single quotes",
        "bash <<EOF\necho '\\$HOME'\nEOF",
        (("echo", "$HOME"),),
    ),
    (
        "herestring with a command substitution",
        'bash <<< "echo $(curl u)"',
        Reason.BUILT_AT_RUN_TIME,
    ),
    # The text of a herestring no longer shows its quotes, so a single-quoted one with a variable is unknown too.
    (
        "single-quoted herestring with a variable",
        "bash <<< 'echo $HOME'",
        Reason.BUILT_AT_RUN_TIME,
    ),
    # Its text has the escapes removed too, e.g. `\\$HOME` for `"\\\\$HOME"`, so a backslash before an expansion in it does not keep it.
    (
        "herestring with an escaped backslash before a variable",
        'bash <<< "echo \\\\$HOME"',
        Reason.BUILT_AT_RUN_TIME,
    ),
    ("herestring without an expansion", "bash <<< 'curl u'", (("curl", "u"),)),
]


@pytest.mark.parametrize(
    ("command_text", "followed"),
    [case[1:] for case in STDIN_TEXT_CASES],
    ids=[case[0] for case in STDIN_TEXT_CASES],
)
def test_stdin_text_that_a_shell_expands_before_its_program_reads_it(
    knowledge: ExpandedToolCallKnowledge,
    command_text: str,
    followed: tuple[tuple[str, ...], ...] | UnknownRanTextReason,
):
    (ran_texts_of_tool_call,) = _expand(knowledge, _call(1, command_text))
    *_, (source, stdin_followed) = _texts_with_words(ran_texts_of_tool_call.ran_texts)

    assert isinstance(source, StdinText)
    assert stdin_followed == followed


def test_a_substitution_in_an_unquoted_heredoc_is_a_command_of_the_call_only(
    knowledge: ExpandedToolCallKnowledge,
):
    (ran_texts_of_tool_call,) = _expand(
        knowledge, _call(1, "bash <<EOF\necho $(curl u)\nEOF")
    )

    assert _texts_with_words(ran_texts_of_tool_call.ran_texts) == [
        (CallCommandText(), (("curl", "u"), ("bash",))),
        (StdinText(1), Reason.BUILT_AT_RUN_TIME),
    ]


@pytest.mark.parametrize(
    ("command_text", "result", "run_path", "followed", "writer"),
    [case[1:] for case in FILE_CHANGE_CASES],
    ids=[case[0] for case in FILE_CHANGE_CASES],
)
def test_text_of_a_written_file_after_a_command_touched_it(
    knowledge: ExpandedToolCallKnowledge,
    command_text: str,
    result: ToolCallResult,
    run_path: str,
    followed: tuple[tuple[str, ...], ...] | UnknownRanTextReason,
    writer: ToolCallKey,
):
    ran_text = _last_text(
        knowledge,
        _call(1, WriteFileAction("f.sh", "curl a")),
        _call(2, command_text, result),
        _call(3, f"bash {run_path}"),
    )

    assert _texts_with_words((ran_text,)) == [(FileText(0, run_path, writer), followed)]


def test_a_use_by_a_program_without_a_row_is_recorded_on_the_written_file(
    knowledge: ExpandedToolCallKnowledge,
):
    touches = _expand(
        knowledge,
        _call(1, "curl -s -o a.tgz u"),
        _call(2, "ls -l a.tgz; mytool a.tgz; mytool other"),
    )[-1].file_touches

    a_tgz = WrittenFileKey(K1, "a.tgz")
    assert touches == (
        _touch(0, "a.tgz", Kind.SHOWS_SIZE_OR_TYPE, a_tgz),
        _touch(1, "a.tgz", Kind.UNKNOWN_USE, a_tgz),
    )


def test_the_pipe_reader_that_copies_to_a_file_leaves_the_write_to_the_command_before_it(
    knowledge: ExpandedToolCallKnowledge,
):
    (ran_texts_of_tool_call,) = _expand(
        knowledge, _call(1, "curl u | tee log | tail -1")
    )

    assert ran_texts_of_tool_call.file_touches == (
        _touch(
            0, "log", Kind.WRITES, WrittenFileKey(K1, "log"), channel=Channel.STDOUT
        ),
    )


def test_appended_and_stdin_files_are_written_and_read(
    knowledge: ExpandedToolCallKnowledge,
):
    tee, grep = _expand(
        knowledge,
        _call(1, "tee -a log <<EOF\nx\nEOF"),
        _call(2, "grep error < log"),
    )

    log = WrittenFileKey(K1, "log")
    assert tee.file_touches == (
        _touch(0, "log", Kind.WRITES, log, channel=Channel.STDOUT),
    )
    assert grep.file_touches == (_touch(0, "log", Kind.SHOWS_CONTENT, log),)


def test_a_use_belongs_to_the_writes_since_the_last_overwrite(
    knowledge: ExpandedToolCallKnowledge,
):
    use_counts: Counter[str] = Counter()
    results = _expand(
        knowledge,
        _call(1, "curl a > log"),
        _call(2, "cat log"),
        _call(3, "curl b > log"),
        _call(4, "cat log"),
        _call(5, "curl c >> log"),
        _call(6, "cat log"),
        judgment_rule_use_counts=use_counts,
    )

    keys = [
        [key.tool_call_key.step_id for key in r.file_touches[0].written_file_keys]
        for r in results
    ]
    assert keys[1] == [1] and keys[3] == [3] and keys[5] == [3, 5]
    # Each overwrite ran by the result of its call, so no rule is asked.
    assert use_counts[OVERWRITE_RULE_NAME] == 0


@pytest.mark.parametrize(
    "overwriting_result", [None, ToolCallResult()], ids=["no result", "unknown status"]
)
def test_a_use_after_an_overwrite_that_may_not_have_happened_has_no_known_writer(
    knowledge: ExpandedToolCallKnowledge, overwriting_result: ToolCallResult | None
):
    use_counts: Counter[str] = Counter()
    results = _expand(
        knowledge,
        _call(1, "curl a > log"),
        _call(2, "curl b > log", overwriting_result),
        _call(3, "cat log"),
        judgment_rule_use_counts=use_counts,
    )

    assert results[-1].file_touches == (_touch(0, "log", Kind.SHOWS_CONTENT),)
    assert use_counts[OVERWRITE_RULE_NAME] == 1


def test_a_use_after_an_overwrite_under_a_condition_belongs_to_the_overwrite(
    knowledge: ExpandedToolCallKnowledge,
):
    use_counts: Counter[str] = Counter()
    results = _expand(
        knowledge,
        _call(1, "curl a > log"),
        _call(2, "test -f x && curl b > log"),
        _call(3, "cat log"),
        judgment_rule_use_counts=use_counts,
    )

    # The rule on a command under a condition records the overwrite as if it ran.
    assert results[-1].file_touches == (
        _touch(0, "log", Kind.SHOWS_CONTENT, WrittenFileKey(K2, "log")),
    )
    assert use_counts[OVERWRITE_RULE_NAME] == 0


def test_a_call_that_did_not_run_writes_only_for_itself(
    knowledge: ExpandedToolCallKnowledge,
):
    not_run, reader = _expand(
        knowledge,
        _call(1, "curl u > log; curl -o a.tgz u; cat x", NOT_RUN),
        _call(2, "cat log"),
    )

    assert not_run.file_touches == (
        _touch(
            0, "log", Kind.WRITES, WrittenFileKey(K1, "log"), channel=Channel.STDOUT
        ),
        _touch(
            1,
            "a.tgz",
            Kind.WRITES,
            WrittenFileKey(K1, "a.tgz"),
            channel=Channel.OWN_OUTPUT_FILE,
        ),
    )
    assert reader.file_touches == (_touch(0, "log", Kind.SHOWS_CONTENT),)


def test_a_path_that_fits_several_written_files(knowledge: ExpandedToolCallKnowledge):
    use_counts: Counter[str] = Counter()
    results = _expand(
        knowledge,
        _call(1, WriteFileAction("/a/fetch.sh", "curl a")),
        _call(2, WriteFileAction("/b/fetch.sh", "curl b")),
        _call(3, "bash fetch.sh"),
        judgment_rule_use_counts=use_counts,
    )

    assert results[-1].ran_texts[-1] == UnknownRanText(
        FileTextWithoutKnownWriter(0, "fetch.sh"), Reason.FITS_SEVERAL_WRITTEN_FILES
    )
    assert results[-1].file_touches == (_touch(0, "fetch.sh", Kind.USES_CONTENT),)
    assert use_counts["treat_path_that_fits_several_written_files_as_unknown_text"] == 1
    assert use_counts[SEVERAL_WRITTEN_FILES_USE_RULE_NAME] == 1


def test_a_use_of_a_path_that_fits_several_written_files_is_on_each_on_the_other_answer(
    knowledge: ExpandedToolCallKnowledge, monkeypatch: pytest.MonkeyPatch
):
    _answer(monkeypatch, SEVERAL_WRITTEN_FILES_USE_RULE_NAME, False)
    results = _expand(
        knowledge,
        _call(1, WriteFileAction("/a/fetch.sh", "curl a")),
        _call(2, WriteFileAction("/b/fetch.sh", "curl b")),
        _call(3, "bash fetch.sh"),
    )

    assert results[-1].file_touches == (
        _touch(
            0,
            "fetch.sh",
            Kind.USES_CONTENT,
            WrittenFileKey(K1, "/a/fetch.sh"),
            WrittenFileKey(K2, "/b/fetch.sh"),
            fits_several_written_files=True,
        ),
    )


def test_a_path_names_a_file_written_by_several_paths_only_if_it_can_name_each(
    knowledge: ExpandedToolCallKnowledge,
):
    """A file written as `run.sh` and then as `/app/v3/run.sh` is one file under both paths, so `/app/run.sh` names another file, which no call wrote, as in a trajectory where the agent ran `/app/run.sh` after writing `run.sh` and `/app/v3/run.sh`."""
    results = _expand(
        knowledge,
        _call(1, WriteFileAction("run.sh", "curl a")),
        _call(2, WriteFileAction("/app/v3/run.sh", "curl b")),
        _call(3, "bash /app/run.sh"),
        _call(4, "bash run.sh"),
    )

    assert results[2].ran_texts[-1] == UnknownRanText(
        FileTextWithoutKnownWriter(0, "/app/run.sh"), Reason.NOT_WRITTEN_IN_TRIAL
    )
    assert results[3].ran_texts[-1].source == FileText(0, "run.sh", K2)


def _heredoc_write(path: str, line: str) -> str:
    return f"cat > {path} <<'E'\n{line}\nE"


def _writes_in_one_call_or_one_call_each(
    writes: Sequence[str], *, in_one_call: bool
) -> list[ToolCall]:
    """Make calls that make the shell writes, all in a call at step 1 or each in a call of its own from step 1 on."""
    if in_one_call:
        return [_call(1, "\n".join(writes))]
    return [_call(step_id, write) for step_id, write in enumerate(writes, start=1)]


@pytest.mark.parametrize(
    "in_one_call", [True, False], ids=["one call", "one call each"]
)
def test_writes_in_one_call_name_one_file_only_if_each_path_can_name_it(
    knowledge: ExpandedToolCallKnowledge, in_one_call: bool
):
    """Writes to `run.sh`, `/a/run.sh` and `/b/run.sh` make one file under the first two paths and another under `/b/run.sh`, whether one call or three make them, since `/b/run.sh` cannot name the file at `/a/run.sh`."""
    calls = _writes_in_one_call_or_one_call_each(
        [
            _heredoc_write("run.sh", "curl x"),
            _heredoc_write("/a/run.sh", "curl a"),
            _heredoc_write("/b/run.sh", "curl b"),
        ],
        in_one_call=in_one_call,
    )
    step_id = len(calls) + 1
    results = _expand(
        knowledge,
        *calls,
        _call(step_id, "bash /a/run.sh"),
        _call(step_id + 1, "bash run.sh"),
    )

    assert _texts_with_words(results[-2].ran_texts)[-1][1] == (("curl", "a"),)
    assert results[-1].ran_texts[-1] == UnknownRanText(
        FileTextWithoutKnownWriter(0, "run.sh"), Reason.FITS_SEVERAL_WRITTEN_FILES
    )


def test_writes_in_one_call_to_paths_of_two_files_keep_them_apart(
    knowledge: ExpandedToolCallKnowledge,
):
    """One call that writes `run.sh` and then `/app/v3/run.sh` makes one file under both paths, so `/app/run.sh` names another file, as when two calls write them."""
    writer, runner = _expand(
        knowledge,
        _call(
            1,
            _heredoc_write("run.sh", "curl a")
            + "\n"
            + _heredoc_write("/app/v3/run.sh", "curl b"),
        ),
        _call(2, "bash /app/run.sh"),
    )

    assert [touch.written_file_keys for touch in writer.file_touches] == [
        (WrittenFileKey(K1, "run.sh"),),
        (WrittenFileKey(K1, "run.sh"),),
    ]
    assert runner.ran_texts[-1] == UnknownRanText(
        FileTextWithoutKnownWriter(0, "/app/run.sh"), Reason.NOT_WRITTEN_IN_TRIAL
    )


def test_a_write_and_an_append_of_one_call_by_two_paths_of_one_file(
    knowledge: ExpandedToolCallKnowledge,
):
    """One call that writes `/app/run.sh` and appends to `run.sh` writes one file, so a later run of either path uses that file, whose content is not known after the append."""
    writer, runner = _expand(
        knowledge,
        _call(1, _heredoc_write("/app/run.sh", "curl a") + "\necho 'curl b' >> run.sh"),
        _call(2, "bash run.sh"),
    )

    run_sh = WrittenFileKey(K1, "/app/run.sh")
    assert [touch.written_file_keys for touch in writer.file_touches] == [
        (run_sh,),
        (run_sh,),
    ]
    assert runner.file_touches == (_touch(0, "run.sh", Kind.USES_CONTENT, run_sh),)


def test_a_write_of_one_call_that_fits_several_of_its_files_leaves_them_unknown(
    knowledge: ExpandedToolCallKnowledge,
):
    """A fourth write to `run.sh` after writes to `run.sh`, `/a/run.sh` and `/b/run.sh` in one call may write either file, so a later run of `/a/run.sh` runs no known content."""
    _, runner = _expand(
        knowledge,
        _call(
            1,
            "\n".join(
                [
                    _heredoc_write("run.sh", "curl x"),
                    _heredoc_write("/a/run.sh", "curl a"),
                    _heredoc_write("/b/run.sh", "curl b"),
                    _heredoc_write("run.sh", "curl y"),
                ]
            ),
        ),
        _call(2, "bash /a/run.sh"),
    )

    assert runner.ran_texts[-1] == UnknownRanText(
        FileText(0, "/a/run.sh", K1), Reason.CHANGED_BY_UNREAD_COMMAND
    )


@pytest.mark.parametrize(
    ("fourth_path", "written_file_keys", "fits_several_written_files"),
    [
        ("run.sh", (WrittenFileKey(K1, "run.sh"),), False),
        # The read fits the file of run.sh and that of ./run.sh, so by a rule it is a use of neither.
        ("./run.sh", (), False),
    ],
    ids=["same text as the first write", "other text"],
)
def test_a_write_of_one_call_that_fits_several_of_its_files_joins_only_the_file_of_the_same_path_text(
    knowledge: ExpandedToolCallKnowledge,
    fourth_path: str,
    written_file_keys: tuple[WrittenFileKey, ...],
    fits_several_written_files: bool,
):
    """A fourth write after writes to `run.sh`, `/a/run.sh` and `/b/run.sh` in one call joins the file of `run.sh` when its path text is `run.sh`, since a key holds the call and the path text, and starts a file of its own otherwise, which a later read of `/a/run.sh` also fits."""
    _, reader = _expand(
        knowledge,
        _call(
            1,
            "\n".join(
                [
                    _heredoc_write("run.sh", "curl x"),
                    _heredoc_write("/a/run.sh", "curl a"),
                    _heredoc_write("/b/run.sh", "curl b"),
                    _heredoc_write(fourth_path, "curl y"),
                ]
            ),
        ),
        _call(2, "cat /a/run.sh"),
    )

    assert reader.file_touches == (
        _touch(
            0,
            "/a/run.sh",
            Kind.SHOWS_CONTENT,
            *written_file_keys,
            fits_several_written_files=fits_several_written_files,
        ),
    )


def test_a_write_of_one_call_joins_its_file_only_if_it_fits_the_paths_of_earlier_calls(
    knowledge: ExpandedToolCallKnowledge,
):
    """After a write to `/b/run.sh`, one call that writes `run.sh` and then `/a/run.sh` writes the file at `/b/run.sh` and another file, since `/a/run.sh` cannot name the file at `/b/run.sh`, as when two calls make the last two writes."""
    results = _expand(
        knowledge,
        _call(1, _heredoc_write("/b/run.sh", "curl b")),
        _call(
            2,
            _heredoc_write("run.sh", "curl r")
            + "\n"
            + _heredoc_write("/a/run.sh", "curl a"),
        ),
        _call(3, "bash /a/run.sh"),
        _call(4, "bash /b/run.sh"),
    )

    assert _texts_with_words(results[2].ran_texts)[-1][1] == (("curl", "a"),)
    assert _texts_with_words(results[3].ran_texts)[-1][1] == (("curl", "r"),)


def test_a_write_of_one_call_leaves_unknown_the_other_files_its_path_fits(
    knowledge: ExpandedToolCallKnowledge,
):
    """One call that writes `x/run.sh` and then `run.sh` writes its own file, but `run.sh` may also name the file at `/a/run.sh` written earlier, so a later run of `/a/run.sh` runs no known content."""
    results = _expand(
        knowledge,
        _call(1, _heredoc_write("/a/run.sh", "curl a")),
        _call(
            2,
            _heredoc_write("x/run.sh", "curl x")
            + "\n"
            + _heredoc_write("run.sh", "curl r"),
        ),
        _call(3, "bash /a/run.sh"),
    )

    assert results[-1].ran_texts[-1] == UnknownRanText(
        FileText(0, "/a/run.sh", K1), Reason.CHANGED_BY_UNREAD_COMMAND
    )


@pytest.mark.parametrize(
    ("old", "followed", "rule_uses"),
    [
        ("a", (("curl", "b", "u", "u"),), 0),
        ("x", Reason.CHANGED_BY_UNREAD_COMMAND, 1),
        ("u", Reason.CHANGED_BY_UNREAD_COMMAND, 1),
    ],
)
def test_an_edit_applies_only_where_its_text_occurs_once(
    knowledge: ExpandedToolCallKnowledge,
    old: str,
    followed: tuple[tuple[str, ...], ...] | UnknownRanTextReason,
    rule_uses: int,
):
    use_counts: Counter[str] = Counter()
    results = _expand(
        knowledge,
        _call(1, WriteFileAction("f.sh", "curl a u u")),
        _call(2, EditFileAction("f.sh", old, "b")),
        _call(3, "bash f.sh"),
        judgment_rule_use_counts=use_counts,
    )

    assert _texts_with_words(results[-1].ran_texts[-1:]) == [
        (FileText(0, "f.sh", K2), followed)
    ]
    assert results[-1].file_touches == (
        _touch(0, "f.sh", Kind.USES_CONTENT, WrittenFileKey(K2, "f.sh")),
    )
    assert (
        use_counts["treat_edit_of_text_not_found_once_as_unknown_content"] == rule_uses
    )


# Cursor `editToolCall` gives no old text, and its new text was the whole content of the file in only 27 of its 70 edits in the 100 sample trials, so the content after such an edit stays unknown.
@pytest.mark.parametrize(
    "earlier_calls",
    [(), (_call(0, WriteFileAction("f.sh", "curl a")),)],
    ids=["file not written before", "file written by an earlier call"],
)
def test_an_edit_without_old_text_leaves_the_content_unknown(
    knowledge: ExpandedToolCallKnowledge, earlier_calls: tuple[ToolCall, ...]
):
    ran_text = _last_text(
        knowledge,
        *earlier_calls,
        _call(1, EditFileAction("f.sh", None, "curl b")),
        _call(2, "bash f.sh"),
    )

    assert _texts_with_words((ran_text,)) == [
        (FileText(0, "f.sh", K1), Reason.CHANGED_BY_UNREAD_COMMAND)
    ]


def _patch(*lines: str) -> str:
    return "\n".join(("*** Begin Patch", *lines, "*** End Patch"))


ADD_F_SH = _patch("*** Add File: f.sh", "+curl a")


# (case id, the command that gives apply_patch its patch, the file that the next `bash` runs, its commands or the reason they cannot be followed)
PATCH_CASES = [
    ("heredoc", f"apply_patch <<'EOF'\n{ADD_F_SH}\nEOF", (("curl", "a"),)),
    ("argument", f"apply_patch '{ADD_F_SH}'", (("curl", "a"),)),
    ("herestring", f"apply_patch <<< '{ADD_F_SH}'", (("curl", "a"),)),
    (
        "heredoc that bash expands",
        "apply_patch <<EOF\n" + _patch("*** Add File: f.sh", "+curl $U") + "\nEOF",
        Reason.NOT_WRITTEN_IN_TRIAL,
    ),
    (
        "argument built at run time",
        'apply_patch "$PATCH"',
        Reason.NOT_WRITTEN_IN_TRIAL,
    ),
]


@pytest.mark.parametrize(
    ("patching_text", "followed"),
    [case[1:] for case in PATCH_CASES],
    ids=[case[0] for case in PATCH_CASES],
)
def test_a_file_that_a_patch_adds_is_written_by_the_command_that_takes_the_patch(
    knowledge: ExpandedToolCallKnowledge,
    patching_text: str,
    followed: tuple[tuple[str, ...], ...] | UnknownRanTextReason,
):
    patching, running = _expand(
        knowledge, _call(1, patching_text), _call(2, "bash f.sh")
    )

    if isinstance(followed, UnknownRanTextReason):
        assert patching.file_touches == ()
        assert _texts_with_words(running.ran_texts[-1:]) == [
            (FileTextWithoutKnownWriter(0, "f.sh"), followed)
        ]
    else:
        assert patching.file_touches == (
            _touch(
                0,
                "f.sh",
                Kind.WRITES,
                WrittenFileKey(K1, "f.sh"),
                channel=Channel.OWN_OUTPUT_FILE,
            ),
        )
        assert _texts_with_words(running.ran_texts[-1:]) == [
            (FileText(0, "f.sh", K1), followed)
        ]


def test_a_patch_edits_and_removes_the_files_it_names_in_its_order(
    knowledge: ExpandedToolCallKnowledge,
):
    patch = _patch(
        "*** Update File: f.sh",
        "@@",
        "-curl a",
        "+curl b",
        "*** Delete File: g.sh",
    )
    results = _expand(
        knowledge,
        _call(1, WriteFileAction("f.sh", "curl a")),
        _call(2, WriteFileAction("g.sh", "curl c")),
        _call(3, f"cd /app && apply_patch <<'EOF'\n{patch}\nEOF"),
        _call(4, "bash f.sh"),
    )

    assert results[2].file_touches == (
        _touch(
            1,
            "f.sh",
            Kind.WRITES,
            WrittenFileKey(K3, "f.sh"),
            channel=Channel.OWN_OUTPUT_FILE,
        ),
        _touch(1, "g.sh", Kind.DELETES, WrittenFileKey(K2, "g.sh")),
    )
    assert _texts_with_words(results[3].ran_texts[-1:]) == [
        (FileText(0, "f.sh", K3), (("curl", "b"),))
    ]


def test_a_patch_from_a_stdin_file_is_a_use_of_that_file(
    knowledge: ExpandedToolCallKnowledge,
):
    _, patching = _expand(
        knowledge,
        _call(1, WriteFileAction("p.txt", ADD_F_SH)),
        _call(2, "apply_patch < p.txt"),
    )

    assert patching.file_touches == (
        _touch(0, "p.txt", Kind.USES_CONTENT, WrittenFileKey(K1, "p.txt")),
    )


def test_reads_of_the_harness_output_file_are_marked(
    knowledge: ExpandedToolCallKnowledge,
):
    results = _expand(
        knowledge,
        _call(
            1,
            "make",
            ToolCallResult(
                execution_status=ExecutionStatus.FINISHED, output_path="/tmp/out1.txt"
            ),
        ),
        _call(2, ReadFileAction("/tmp/out1.txt")),
        _call(3, SearchFilesAction(("/tmp/out1.txt", "src"))),
        _call(4, "cat /tmp/out1.txt README.md"),
    )

    assert [
        touch.reads_harness_output_file for r in results[1:] for touch in r.file_touches
    ] == [
        True,
        True,
        False,
        True,
        False,
    ]
    assert results[1].file_touches[0] == _touch(
        None,
        "/tmp/out1.txt",
        Kind.SHOWS_CONTENT,
        harness_output_file_tool_call_keys=(K1,),
    )


@pytest.mark.parametrize(
    ("path", "content", "followed"),
    [
        ("get.py", "import x", "python:import x"),
        (
            "./run",
            "#!/usr/bin/env python3\nimport x",
            "python:#!/usr/bin/env python3\nimport x",
        ),
        ("./run", "#!/bin/bash\ncurl u", (("curl", "u"),)),
        # Without a `#!` line the language is not known by a rule, whatever the extension.
        ("./get.py", "import x", Reason.LANGUAGE_NOT_KNOWN),
        ("./get.py", "#!/bin/bash\ncurl u", (("curl", "u"),)),
        ("./run", "import x", Reason.LANGUAGE_NOT_KNOWN),
        ("./run", "#!\nimport x", Reason.LANGUAGE_NOT_KNOWN),
        ("./run.pl", "#!/usr/bin/perl", Reason.LANGUAGE_NOT_KNOWN),
    ],
)
def test_language_of_a_written_file_that_a_command_runs(
    knowledge: ExpandedToolCallKnowledge,
    path: str,
    content: str,
    followed: str | tuple[tuple[str, ...], ...] | UnknownRanTextReason,
):
    command_text = f"python {path}" if path == "get.py" else path
    ran_text = _last_text(
        knowledge, _call(1, WriteFileAction(path, content)), _call(2, command_text)
    )

    assert _texts_with_words((ran_text,)) == [(FileText(0, path, K1), followed)]


def test_a_file_without_an_interpreter_line_is_read_by_its_extension_on_the_other_answer(
    knowledge: ExpandedToolCallKnowledge, monkeypatch: pytest.MonkeyPatch
):
    _answer(monkeypatch, EXTENSION_RULE_NAME, False)
    by_extension, without_extension = (
        _last_text(
            knowledge, _call(1, WriteFileAction(path, "import x")), _call(2, path)
        )
        for path in ("./get.py", "./run")
    )

    assert _texts_with_words((by_extension, without_extension)) == [
        (FileText(0, "./get.py", K1), "python:import x"),
        (FileText(0, "./run", K1), Reason.LANGUAGE_NOT_KNOWN),
    ]


def test_a_copy_has_the_content_of_its_source_on_the_other_answer(
    knowledge: ExpandedToolCallKnowledge, monkeypatch: pytest.MonkeyPatch
):
    _answer(monkeypatch, COPY_RULE_NAME, False)
    ran_text = _last_text(
        knowledge,
        _call(1, WriteFileAction("f.sh", "curl a")),
        _call(2, "cp f.sh g.sh"),
        _call(3, "bash g.sh"),
    )

    assert _texts_with_words((ran_text,)) == [
        (FileText(0, "g.sh", K2), (("curl", "a"),))
    ]


def test_a_file_from_the_stdin_redirect_and_the_default_run_file(
    knowledge: ExpandedToolCallKnowledge,
):
    stdin_run = _last_text(
        knowledge, _call(1, WriteFileAction("f.sh", "curl a")), _call(2, "bash < f.sh")
    )
    make = _last_text(
        knowledge, _call(1, WriteFileAction("Makefile", "all:")), _call(2, "make")
    )

    assert _texts_with_words((stdin_run,)) == [
        (FileText(0, "f.sh", K1), (("curl", "a"),))
    ]
    assert make == UnknownRanText(FileText(0, None, K1), Reason.LANGUAGE_NOT_KNOWN)


def test_a_file_that_runs_itself_is_followed_once(knowledge: ExpandedToolCallKnowledge):
    ran_texts = _expand(
        knowledge, _call(1, WriteFileAction("f.sh", "bash f.sh")), _call(2, "bash f.sh")
    )[-1].ran_texts

    assert _texts_with_words(ran_texts) == [
        (CallCommandText(), (("bash", "f.sh"),)),
        (FileText(0, "f.sh", K1), (("bash", "f.sh"),)),
        (FileText(1, "f.sh", K1), Reason.FILE_ALREADY_RUNNING),
    ]


def test_a_file_in_another_trajectory_is_not_linked(
    knowledge: ExpandedToolCallKnowledge,
):
    results = _expand(
        knowledge,
        _call(1, WriteFileAction("f.sh", "curl a"), is_subagent=True),
        _call(2, "bash f.sh"),
        _call(3, "bash f.sh", is_subagent=True),
    )

    assert results[1].ran_texts[-1] == UnknownRanText(
        FileTextWithoutKnownWriter(0, "f.sh"), Reason.NOT_WRITTEN_IN_TRIAL
    )
    assert _texts_with_words(results[2].ran_texts[-1:]) == [
        (FileText(0, "f.sh", K1), (("curl", "a"),))
    ]


@pytest.mark.parametrize(
    ("shell_text", "variable_values"),
    [
        ("U=a.org; bash -c 'curl $U'", ()),
        ("U=a.org; eval 'curl $U'", (VariableValues("U", ("a.org",), False, False),)),
        (
            "U=a.org; eval 'curl $U'; U=b.org",
            (VariableValues("U", ("a.org",), False, False),),
        ),
    ],
)
def test_outer_assignments_reach_only_text_run_in_the_calling_shell(
    knowledge: ExpandedToolCallKnowledge,
    shell_text: str,
    variable_values: tuple[VariableValues, ...],
):
    ran_text = _last_text(knowledge, _call(1, shell_text))

    assert isinstance(ran_text, RanShellText)
    assert ran_text.ran_commands[0].variable_values == variable_values


def test_a_variable_with_one_value_fills_the_text_and_the_path(
    knowledge: ExpandedToolCallKnowledge,
):
    argument = _last_text(knowledge, _call(1, 'U=a.org; bash -c "curl $U"'))
    file = _last_text(
        knowledge,
        _call(1, WriteFileAction("f.sh", "curl a")),
        _call(2, "F=f.sh; bash $F"),
    )

    assert _texts_with_words((argument, file)) == [
        (ArgumentText(0), (("curl", "a.org"),)),
        (FileText(0, "f.sh", K1), (("curl", "a"),)),
    ]


def test_options_of_a_new_shell_reach_the_text_it_runs(
    knowledge: ExpandedToolCallKnowledge,
):
    with_option, without_option = (
        _last_text(knowledge, _call(1, WriteFileAction("f.sh", "a\nb")), _call(2, text))
        for text in ("bash -e f.sh", "bash f.sh")
    )

    assert isinstance(with_option, RanShellText) and isinstance(
        without_option, RanShellText
    )
    assert with_option.ran_commands[1].shell_command.runs_if
    assert not without_option.ran_commands[1].shell_command.runs_if


def test_output_of_a_file_text_goes_through_the_pipe_of_its_runner(
    knowledge: ExpandedToolCallKnowledge,
):
    ran_text = _last_text(
        knowledge,
        _call(1, WriteFileAction("f.sh", "curl a")),
        _call(2, "bash f.sh | tail -1"),
    )

    assert isinstance(ran_text, RanShellText)
    assert ran_text.ran_commands[0].stdout_routes[0].pipe_reader_command_ids == (1,)


def test_a_removed_file_is_read_as_never_written(knowledge: ExpandedToolCallKnowledge):
    use_counts: Counter[str] = Counter()
    for removal in ("rm f.sh", DeleteFileAction("f.sh")):
        results = _expand(
            knowledge,
            _call(1, WriteFileAction("f.sh", "curl a")),
            _call(2, removal),
            _call(3, "bash f.sh"),
            judgment_rule_use_counts=use_counts,
        )
        assert results[-1].ran_texts[-1] == UnknownRanText(
            FileTextWithoutKnownWriter(0, "f.sh"), Reason.NOT_WRITTEN_IN_TRIAL
        )
        assert results[-1].file_touches == (_touch(0, "f.sh", Kind.USES_CONTENT),)
    assert use_counts["treat_deleted_file_as_never_written"] == 4


def test_removing_a_folder_of_a_written_file_leaves_the_content_of_its_files_unknown(
    knowledge: ExpandedToolCallKnowledge,
):
    use_counts: Counter[str] = Counter()
    results = _expand(
        knowledge,
        _call(1, WriteFileAction("/app/scripts/f.sh", "curl a")),
        _call(2, WriteFileAction("g.sh", "curl b")),
        _call(3, "rm -rf scripts"),
        _call(4, "bash scripts/f.sh; bash g.sh"),
        judgment_rule_use_counts=use_counts,
    )

    assert results[2].file_touches == ()
    assert _texts_with_words(results[-1].ran_texts[1:]) == [
        (FileText(0, "scripts/f.sh", K1), Reason.CHANGED_BY_UNREAD_COMMAND),
        (FileText(1, "g.sh", K2), (("curl", "b"),)),
    ]
    assert use_counts["treat_file_not_named_by_command_words_as_unknown_content"] == 1
    assert use_counts["treat_path_that_ends_another_as_same_file"] >= 1


@pytest.mark.parametrize(
    ("typed_text", "starter_text", "ran_texts"),
    [case[1:] for case in TYPED_TEXT_CASES],
    ids=[case[0] for case in TYPED_TEXT_CASES],
)
def test_text_typed_into_a_started_handle_on_the_other_answer_of_the_reader_rule(
    knowledge: ExpandedToolCallKnowledge,
    monkeypatch: pytest.MonkeyPatch,
    typed_text: str,
    starter_text: str | None,
    ran_texts: list[tuple[object, object]],
):
    use_counts: Counter[str] = Counter()
    _answer(monkeypatch, TYPED_TEXT_LANGUAGE_RULE_NAME, False)
    # Without a starter text the first call ends and starts no handle.
    results = _expand(
        knowledge,
        _call(1, starter_text or "ls", FINISHED if starter_text is None else RUNNING),
        _call(2, PollAction((HANDLE,), typed_text)),
        judgment_rule_use_counts=use_counts,
    )

    assert _texts_with_words(results[-1].ran_texts) == ran_texts
    assert use_counts["treat_input_of_key_presses_only_as_no_text"] == (
        typed_text == "\n"
    )


@pytest.mark.parametrize(
    ("typed_text", "starter_text"),
    [("curl u\n", "bash"), ("import x\n", "python3"), ("hello\n", "cat > notes.txt")],
)
def test_text_typed_into_a_started_handle_is_of_a_language_not_known(
    knowledge: ExpandedToolCallKnowledge, typed_text: str, starter_text: str
):
    use_counts: Counter[str] = Counter()
    results = _expand(
        knowledge,
        _call(1, starter_text, RUNNING),
        _call(2, PollAction((HANDLE,), typed_text)),
        judgment_rule_use_counts=use_counts,
    )

    assert _texts_with_words(results[-1].ran_texts) == [
        (PollInputText(None, K1), Reason.LANGUAGE_NOT_KNOWN)
    ]
    assert use_counts[TYPED_TEXT_LANGUAGE_RULE_NAME] == 1


@pytest.mark.parametrize(
    ("result", "may_have_run", "rule_uses"),
    [
        (None, True, 1),
        (ToolCallResult(), True, 1),
        (FINISHED, True, 0),
        (NOT_RUN, False, 0),
    ],
)
def test_a_call_may_have_run_unless_its_result_says_not_run(
    knowledge: ExpandedToolCallKnowledge,
    result: ToolCallResult | None,
    may_have_run: bool,
    rule_uses: int,
):
    use_counts: Counter[str] = Counter()
    results = _expand(
        knowledge,
        _call(1, "curl a > log", result),
        _call(2, "cat log"),
        judgment_rule_use_counts=use_counts,
    )

    assert bool(results[-1].file_touches[0].written_file_keys) == may_have_run
    assert use_counts["treat_tool_call_not_marked_not_run_as_maybe_run"] == rule_uses


@pytest.mark.parametrize(
    "result", [None, ToolCallResult()], ids=["no result", "unknown status"]
)
def test_a_write_of_a_call_whose_result_does_not_say_it_ran_has_unknown_content(
    knowledge: ExpandedToolCallKnowledge, result: ToolCallResult | None
):
    ran_text = _last_text(
        knowledge,
        _call(1, WriteFileAction("fetch.sh", "curl a"), result),
        _call(2, "bash fetch.sh"),
    )

    assert ran_text == UnknownRanText(
        FileText(0, "fetch.sh", K1), Reason.CHANGED_BY_UNREAD_COMMAND
    )


def test_a_message_that_the_harness_wrote_in_no_known_format_is_not_asked_whether_it_ran(
    knowledge: ExpandedToolCallKnowledge,
):
    """The prompt of an Antigravity CLI `schedule` timer is such a message, an `UnknownAction` whose result has the status `UNKNOWN`."""
    message = ToolCall(
        HarnessToolCall(
            _key(1),
            HarnessTool("harness", "message"),
            "",
            {},
            {"content": "Check the build."},
            is_harness_message=True,
        ),
        UnknownAction(),
        ToolCallResult(),
    )
    use_counts: Counter[str] = Counter()
    _expand(knowledge, message, judgment_rule_use_counts=use_counts)

    assert use_counts["treat_tool_call_not_marked_not_run_as_maybe_run"] == 0


def test_rules_counted_by_their_situation(knowledge: ExpandedToolCallKnowledge):
    use_counts: Counter[str] = Counter()
    _expand(
        knowledge,
        _call(1, WriteFileAction("/app/f.sh", "curl a")),
        _call(
            2,
            "test -f x && cat f.sh; cp f.sh g.sh; U=a; bash -c 'curl $U'; ls | xargs rm",
        ),
        judgment_rule_use_counts=use_counts,
    )

    assert use_counts["treat_command_under_run_condition_as_run"] == 1
    assert use_counts["treat_copy_with_two_arguments_as_unknown_content"] == 1
    assert use_counts["treat_outer_assignment_as_not_visible_in_new_shell"] == 1
    assert use_counts["treat_file_not_named_by_command_words_as_unknown_content"] == 1
    # The use of f.sh by cat asks the rule on two paths, and the copy, whose content is unknown by a rule, does not look up its source.
    assert use_counts["treat_path_that_ends_another_as_same_file"] == 1


@pytest.mark.parametrize(
    ("written_path", "path", "same"),
    [
        ("fetch.log", "fetch.log", True),
        ("./fetch.log", "fetch.log", True),
        ("/app/fetch.log", "fetch.log", True),
        ("/app/fetch.log", "logs/../fetch.log", True),
        ("/app/out/fetch.log", "out/fetch.log", True),
        ("/tmp/fetch.log", "$LOG/fetch.log", True),
        ("/root/fetch.log", "~/fetch.log", True),
        ("/app/fetch.log", "/tmp/fetch.log", False),
        ("a/fetch.log", "b/fetch.log", False),
        ("/app/b/fetch.log", "a/fetch.log", False),
        ("app/fetch.log", "/fetch.log", False),
        ("/tmp/fetch.log", "$LOG", False),
        ("fetch.log.1", "fetch.log", False),
        ("/fetch.log", "/../fetch.log", True),
        ("/tmp/fetch.log", "/../fetch.log", False),
        ("/tmp/fetch.log", "/$D/fetch.log", False),
        ("/fetch.log", "/$D/fetch.log", False),
    ],
)
def test_paths_that_name_one_written_file(written_path: str, path: str, same: bool):
    for first, second in ((written_path, path), (path, written_path)):
        trial_file_contents = TrialFileContents(judgment_rule_use_counts=Counter())
        trial_file_contents.record_write(
            K1,
            None,
            first,
            Channel.TOOL_ARGUMENT,
            "x",
            appends=False,
            may_have_run=True,
            is_call_sure_to_have_run=True,
            may_be_glob=False,
        )
        assert bool(trial_file_contents.file_text(second).written_file_keys) == same


def test_eval_runs_its_arguments_joined_as_one_text(
    knowledge: ExpandedToolCallKnowledge,
):
    ran_texts = _expand(knowledge, _call(1, "eval curl u"))[-1].ran_texts

    assert _texts_with_words(ran_texts[1:]) == [(ArgumentText(0), (("curl", "u"),))]


def test_text_typed_into_handles_of_two_starting_calls_has_no_starter(
    knowledge: ExpandedToolCallKnowledge,
):
    other_handle = ExecutionHandle(ExecutionHandleKind.COMMAND, "h2")
    results = _expand(
        knowledge,
        _call(1, "bash", RUNNING),
        _call(
            2,
            "bash",
            ToolCallResult(
                execution_status=ExecutionStatus.RUNNING, handles=(other_handle,)
            ),
        ),
        _call(3, PollAction((HANDLE, other_handle), "curl u\n")),
    )

    assert results[-1].ran_texts == (
        UnknownRanText(PollInputText(None, None), Reason.LANGUAGE_NOT_KNOWN),
    )


def test_texts_of_two_arguments_get_ids_after_all_commands_of_the_call(
    knowledge: ExpandedToolCallKnowledge,
):
    ran_texts = _expand(knowledge, _call(1, "bash -c 'curl a'; bash -c 'curl b'"))[
        -1
    ].ran_texts

    assert [
        (ran_command.shell_command.id, ran_command.shell_command.words)
        for ran_text in ran_texts[1:]
        if isinstance(ran_text, RanShellText)
        for ran_command in ran_text.ran_commands
    ] == [(2, ("curl", "a")), (3, ("curl", "b"))]


# (case id, the call that did not run after an earlier call wrote `curl a` to f.sh, its file touches, the command of the next call and its last text)
NOT_RUN_CASES = [
    (
        "write tool",
        WriteFileAction("g.sh", "curl b"),
        (
            _touch(
                None,
                "g.sh",
                Kind.WRITES,
                WrittenFileKey(K2, "g.sh"),
                channel=Channel.TOOL_ARGUMENT,
            ),
        ),
        "bash g.sh",
        UnknownRanText(
            FileTextWithoutKnownWriter(0, "g.sh"), Reason.NOT_WRITTEN_IN_TRIAL
        ),
    ),
    ("read tool", ReadFileAction("f.sh"), (), "bash f.sh", (("curl", "a"),)),
    ("delete tool", DeleteFileAction("f.sh"), (), "bash f.sh", (("curl", "a"),)),
    ("rm", "rm f.sh", (), "bash f.sh", (("curl", "a"),)),
    (
        "cp",
        "cp f.sh g.sh",
        (
            _touch(
                0,
                "g.sh",
                Kind.WRITES,
                WrittenFileKey(K2, "g.sh"),
                channel=Channel.OWN_OUTPUT_FILE,
            ),
        ),
        "bash g.sh",
        UnknownRanText(
            FileTextWithoutKnownWriter(0, "g.sh"), Reason.NOT_WRITTEN_IN_TRIAL
        ),
    ),
    ("program without a row", "mytool f.sh", (), "bash f.sh", (("curl", "a"),)),
]


@pytest.mark.parametrize(
    ("action", "file_touches", "next_command_text", "next_text"),
    [case[1:] for case in NOT_RUN_CASES],
    ids=[case[0] for case in NOT_RUN_CASES],
)
def test_a_call_that_did_not_run_changes_no_file_for_later_calls(
    knowledge: ExpandedToolCallKnowledge,
    action: ToolCallAction | str,
    file_touches: tuple[FileTouch, ...],
    next_command_text: str,
    next_text: RanText | tuple[tuple[str, ...], ...],
):
    _, not_run, later = _expand(
        knowledge,
        _call(1, WriteFileAction("f.sh", "curl a")),
        _call(2, action, NOT_RUN),
        _call(3, next_command_text),
    )

    assert not_run.file_touches == file_touches
    if isinstance(next_text, tuple):
        assert _texts_with_words(later.ran_texts[-1:]) == [
            (FileText(0, "f.sh", K1), next_text)
        ]
    else:
        assert later.ran_texts[-1] == next_text


def test_a_run_that_did_not_happen_follows_the_file_but_records_no_use(
    knowledge: ExpandedToolCallKnowledge,
):
    not_run = _expand(
        knowledge,
        _call(1, WriteFileAction("f.sh", "curl a")),
        _call(2, "bash f.sh", NOT_RUN),
    )[-1]

    assert _texts_with_words(not_run.ran_texts[-1:]) == [
        (FileText(0, "f.sh", K1), (("curl", "a"),))
    ]
    assert not_run.file_touches == ()


def test_a_file_written_again_after_its_removal_is_followed(
    knowledge: ExpandedToolCallKnowledge,
):
    _, removal, _, run = _expand(
        knowledge,
        _call(1, WriteFileAction("f.sh", "curl a")),
        _call(2, "rm f.sh"),
        _call(3, WriteFileAction("f.sh", "curl b")),
        _call(4, "bash f.sh"),
    )

    assert removal.file_touches == (
        _touch(0, "f.sh", Kind.DELETES, WrittenFileKey(K1, "f.sh")),
    )
    assert _texts_with_words(run.ran_texts[-1:]) == [
        (FileText(0, "f.sh", K3), (("curl", "b"),))
    ]


@pytest.mark.parametrize(
    ("shell_text", "ran_text"),
    [
        (
            "F=a.sh; F=$(cat n); bash $F",
            UnknownRanText(
                FileTextWithoutKnownWriter(1, "$F"), Reason.BUILT_AT_RUN_TIME
            ),
        ),
        (
            "for f in a.sh b.sh; do bash $f; done",
            UnknownRanText(
                FileTextWithoutKnownWriter(0, "$f"), Reason.BUILT_AT_RUN_TIME
            ),
        ),
    ],
)
def test_a_variable_of_several_values_is_not_filled(
    knowledge: ExpandedToolCallKnowledge, shell_text: str, ran_text: RanText
):
    assert (
        _last_text(
            knowledge, _call(1, WriteFileAction("a.sh", "curl a")), _call(2, shell_text)
        )
        == ran_text
    )


def test_a_variable_with_one_value_fills_the_path_of_a_redirect(
    knowledge: ExpandedToolCallKnowledge,
):
    (ran_texts_of_tool_call,) = _expand(knowledge, _call(1, "F=log; curl u > $F"))

    assert ran_texts_of_tool_call.file_touches == (
        _touch(
            0, "log", Kind.WRITES, WrittenFileKey(K1, "log"), channel=Channel.STDOUT
        ),
    )


@pytest.mark.parametrize(
    ("shell_text", "words", "variable_values"),
    [
        (
            "U=a.org; read U; eval 'curl $U'",
            ("curl", "$U"),
            (VariableValues("U", ("a.org",), False, True),),
        ),
        # The outer eval fills `$U` into the text of the inner eval, as the shell does.
        ("U=a.org; eval eval curl '$U'", ("curl", "a.org"), ()),
    ],
)
def test_eval_sees_the_names_set_at_run_time_and_the_values_of_outer_evals(
    knowledge: ExpandedToolCallKnowledge,
    shell_text: str,
    words: tuple[str, ...],
    variable_values: tuple[VariableValues, ...],
):
    ran_text = _last_text(knowledge, _call(1, shell_text))

    assert isinstance(ran_text, RanShellText)
    assert ran_text.ran_commands[0].shell_command.words == words
    assert ran_text.ran_commands[0].variable_values == variable_values


def test_an_archive_that_tar_unpacks_is_a_use_of_its_content(
    knowledge: ExpandedToolCallKnowledge,
):
    touches = _expand(
        knowledge, _call(1, "curl -s -o a.tgz u"), _call(2, "tar xzf a.tgz")
    )[-1].file_touches

    assert touches == (
        _touch(0, "a.tgz", Kind.USES_CONTENT, WrittenFileKey(K1, "a.tgz")),
    )


def test_a_copy_with_three_arguments_writes_no_copy(
    knowledge: ExpandedToolCallKnowledge,
):
    use_counts: Counter[str] = Counter()
    _, copy, run = _expand(
        knowledge,
        _call(1, WriteFileAction("a.sh", "curl a")),
        _call(2, "cp a.sh b.sh c.sh"),
        _call(3, "bash c.sh"),
        judgment_rule_use_counts=use_counts,
    )

    assert copy.file_touches == ()
    assert run.ran_texts[-1] == UnknownRanText(
        FileTextWithoutKnownWriter(0, "c.sh"), Reason.NOT_WRITTEN_IN_TRIAL
    )
    assert use_counts["treat_copy_with_two_arguments_as_unknown_content"] == 0


def test_two_files_that_run_each_other_are_followed_once_each(
    knowledge: ExpandedToolCallKnowledge,
):
    ran_texts = _expand(
        knowledge,
        _call(1, WriteFileAction("a.sh", "bash b.sh")),
        _call(2, WriteFileAction("b.sh", "bash a.sh")),
        _call(3, "bash a.sh"),
    )[-1].ran_texts

    assert _texts_with_words(ran_texts) == [
        (CallCommandText(), (("bash", "a.sh"),)),
        (FileText(0, "a.sh", K1), (("bash", "b.sh"),)),
        (FileText(1, "b.sh", K2), (("bash", "a.sh"),)),
        (FileText(2, "a.sh", K1), Reason.FILE_ALREADY_RUNNING),
    ]


def test_a_file_of_another_trajectory_id_is_not_linked_and_the_rule_is_counted_once(
    knowledge: ExpandedToolCallKnowledge,
):
    use_counts: Counter[str] = Counter()
    subagent_write = ToolCall(
        HarnessToolCall(
            _key(1, trajectory_id="subagent-1"),
            HarnessTool("harness", "tool"),
            "",
            {},
            None,
        ),
        WriteFileAction("f.sh", "curl a"),
        FINISHED,
    )
    results = _expand(
        knowledge,
        subagent_write,
        _call(2, "bash f.sh"),
        judgment_rule_use_counts=use_counts,
    )

    assert results[-1].ran_texts[-1] == UnknownRanText(
        FileTextWithoutKnownWriter(0, "f.sh"), Reason.NOT_WRITTEN_IN_TRIAL
    )
    assert results[-1].file_touches == (_touch(0, "f.sh", Kind.USES_CONTENT),)
    assert use_counts["treat_calls_of_other_trajectory_as_not_linked"] == 1


def test_a_written_file_that_the_shell_cannot_read_is_unreadable(
    knowledge: ExpandedToolCallKnowledge,
):
    ran_text = _last_text(
        knowledge, _call(1, WriteFileAction("f.sh", ")))")), _call(2, "bash f.sh")
    )

    assert ran_text == UnknownRanText(
        FileText(0, "f.sh", K1), Reason.UNREADABLE_SHELL_TEXT
    )


@pytest.mark.parametrize(
    "shell_text",
    [
        "f() { cat f.sh; }",
        "case x in a) cat f.sh;; esac",
    ],
)
def test_a_command_that_may_not_run_records_its_use_by_a_rule(
    knowledge: ExpandedToolCallKnowledge, shell_text: str
):
    use_counts: Counter[str] = Counter()
    touches = _expand(
        knowledge,
        _call(1, WriteFileAction("f.sh", "curl a")),
        _call(2, shell_text),
        judgment_rule_use_counts=use_counts,
    )[-1].file_touches

    assert touches == (
        _touch(0, "f.sh", Kind.SHOWS_CONTENT, WrittenFileKey(K1, "f.sh")),
    )
    assert use_counts["treat_command_under_run_condition_as_run"] == 1


@pytest.mark.parametrize(
    ("shell_text", "may_name_file"),
    [
        ("sed -i s/a/b/ *.sh", True),
        ("sed -i s/a/b/ /app/*.sh", True),
        ("sed -i s/a/b/ {f,g}.sh", True),
        ("rm -f /app/f.s?", True),
        ("sed -i s/a/b/ /app/*/*.sh", False),
        ("sed -i s/a/b/ /tmp/*.sh", False),
        ("sed -i s/a/b/ *.py", False),
    ],
    ids=[
        "relative",
        "absolute",
        "brace list",
        "removal",
        "more parts",
        "other folder",
        "other ending",
    ],
)
def test_a_glob_that_a_command_changes_leaves_the_content_of_each_written_file_it_may_name_unknown(
    knowledge: ExpandedToolCallKnowledge, shell_text: str, may_name_file: bool
):
    use_counts: Counter[str] = Counter()
    results = _expand(
        knowledge,
        _call(1, WriteFileAction("/app/f.sh", "curl a")),
        _call(2, shell_text),
        _call(3, "bash /app/f.sh"),
        judgment_rule_use_counts=use_counts,
    )

    assert results[1].file_touches == ()
    assert _texts_with_words(results[-1].ran_texts[-1:]) == [
        (
            FileText(0, "/app/f.sh", K1),
            Reason.CHANGED_BY_UNREAD_COMMAND if may_name_file else (("curl", "a"),),
        )
    ]
    assert use_counts["treat_file_not_named_by_command_words_as_unknown_content"] == 1


def test_a_copy_from_a_glob_writes_its_destination_with_unknown_content(
    knowledge: ExpandedToolCallKnowledge,
):
    results = _expand(
        knowledge,
        _call(1, WriteFileAction("f.sh", "curl a")),
        _call(2, "cp *.sh g.sh"),
        _call(3, "bash g.sh"),
    )

    assert results[1].file_touches == (
        _touch(
            0,
            "g.sh",
            Kind.WRITES,
            WrittenFileKey(K2, "g.sh"),
            channel=Channel.OWN_OUTPUT_FILE,
        ),
    )
    assert _texts_with_words(results[-1].ran_texts[-1:]) == [
        (FileText(0, "g.sh", K2), Reason.CHANGED_BY_UNREAD_COMMAND)
    ]


@pytest.mark.parametrize(
    ("shell_text", "followed"),
    [
        ("ls | xargs sed -i s/a/b/", Reason.CHANGED_BY_UNREAD_COMMAND),
        ("ls | xargs cat", (("curl", "a"),)),
    ],
    ids=["changes", "reads"],
)
def test_a_program_that_changes_files_it_gets_at_run_time_leaves_the_content_of_every_written_file_unknown(
    knowledge: ExpandedToolCallKnowledge,
    shell_text: str,
    followed: tuple[tuple[str, ...], ...] | UnknownRanTextReason,
):
    ran_text = _last_text(
        knowledge,
        _call(1, WriteFileAction("/app/f.sh", "curl a")),
        _call(2, shell_text),
        _call(3, "bash /app/f.sh"),
    )

    assert _texts_with_words((ran_text,)) == [(FileText(0, "/app/f.sh", K1), followed)]


def test_a_parameter_in_braces_is_no_glob(knowledge: ExpandedToolCallKnowledge):
    use_counts: Counter[str] = Counter()
    (ran_texts_of_tool_call,) = _expand(
        knowledge,
        _call(1, "cat > ${D}/f.sh <<EOF\ncurl b\nEOF"),
        judgment_rule_use_counts=use_counts,
    )

    assert ran_texts_of_tool_call.file_touches == (
        _touch(
            0,
            "${D}/f.sh",
            Kind.WRITES,
            WrittenFileKey(K1, "${D}/f.sh"),
            channel=Channel.STDOUT,
        ),
    )
    assert use_counts["treat_file_not_named_by_command_words_as_unknown_content"] == 0


def test_the_path_of_a_tool_names_one_file_while_a_command_word_may_be_a_glob(
    knowledge: ExpandedToolCallKnowledge,
):
    use_counts: Counter[str] = Counter()
    path = "app/[id]/page.tsx"
    written_file_key = WrittenFileKey(K1, path)

    results = _expand(
        knowledge,
        _call(1, WriteFileAction(path, "x")),
        _call(2, ReadFileAction(path)),
        _call(3, f"cat '{path}'"),
        _call(4, DeleteFileAction(path)),
        judgment_rule_use_counts=use_counts,
    )

    assert [result.file_touches for result in results] == [
        (
            _touch(
                None, path, Kind.WRITES, written_file_key, channel=Channel.TOOL_ARGUMENT
            ),
        ),
        (_touch(None, path, Kind.SHOWS_CONTENT, written_file_key),),
        (),
        (_touch(None, path, Kind.DELETES, written_file_key),),
    ]
    assert use_counts["treat_file_not_named_by_command_words_as_unknown_content"] == 1


@pytest.mark.parametrize(
    ("shell_text", "paths"),
    [
        # The words of find after `;` hold a path, which is not the file run.
        ("find . -exec ./a.sh \\; -path ./x/y", ["./a.sh"]),
        ("find . -exec ./b.sh \\; -exec ./a.sh \\;", ["./b.sh", "./a.sh"]),
    ],
)
def test_each_file_that_a_command_runs_by_its_path_is_followed(
    knowledge: ExpandedToolCallKnowledge, shell_text: str, paths: list[str]
):
    ran_texts = _expand(
        knowledge,
        _call(1, WriteFileAction("a.sh", "#!/bin/bash\ncurl a")),
        _call(2, WriteFileAction("b.sh", "#!/bin/bash\ncurl b")),
        _call(3, shell_text),
    )[-1].ran_texts

    assert [
        (ran_text_source, words)
        for ran_text_source, words in _texts_with_words(ran_texts)
        if isinstance(ran_text_source, FileText)
    ] == [
        (FileText(0, path, {"./a.sh": K1, "./b.sh": K2}[path]), (("curl", path[2]),))
        for path in paths
    ]


@pytest.mark.parametrize(
    ("interpreter_line", "programs_that_decide_whether_c_runs"),
    [
        ("#!/bin/bash", None),
        ("#!/bin/bash -e", ("b",)),
        ("#!/bin/bash -o pipefail -e", ("a", "b")),
        # The name after a cluster of options is not passed on, so pipefail stays off.
        ("#!/bin/bash -eo pipefail", ("b",)),
        # `set` takes no long option, so passing one would end the options before -e.
        ("#!/bin/bash --norc -e", ("b",)),
    ],
)
def test_options_of_the_interpreter_line_reach_the_text_it_runs(
    knowledge: ExpandedToolCallKnowledge,
    interpreter_line: str,
    programs_that_decide_whether_c_runs: tuple[str, ...] | None,
):
    ran_text = _last_text(
        knowledge,
        _call(1, WriteFileAction("./run", f"{interpreter_line}\na | b\nc")),
        _call(2, "./run"),
    )

    assert isinstance(ran_text, RanShellText)
    program_of_command_id = {
        ran_command.shell_command.id: ran_command.shell_command.words[0]
        for ran_command in ran_text.ran_commands
    }
    assert [
        tuple(
            program_of_command_id[command_id]
            for command_id in run_condition.deciding_command_ids
        )
        for run_condition in ran_text.ran_commands[-1].shell_command.runs_if
    ] == (
        []
        if programs_that_decide_whether_c_runs is None
        else [programs_that_decide_whether_c_runs]
    )


@pytest.mark.parametrize(
    ("shell_text", "argument_texts"),
    [
        ("bash -n f.sh", [(ArgumentText(0), Reason.WORD_ROLE_NOT_KNOWN)]),
        # php runs text only from its stdin, and its row leaves the role of its arguments blank.
        ("php x", [(ArgumentText(0), Reason.WORD_ROLE_NOT_KNOWN)]),
        # The value of -O has a blank role but is no argument that bash may run.
        ("bash -O extglob -c 'curl a'", [(ArgumentText(0), (("curl", "a"),))]),
        # The words after an option without a row are unread, and bash may run them.
        ("bash --foo f.sh", [(ArgumentText(0), Reason.WORD_ROLE_NOT_KNOWN)]),
        ("sudo bash --foo f.sh", [(ArgumentText(0), Reason.WORD_ROLE_NOT_KNOWN)]),
        # curl runs no text, so its unread words give none.
        ("curl --foo u", []),
    ],
)
def test_an_argument_whose_role_no_fact_gives_is_an_unknown_text(
    knowledge: ExpandedToolCallKnowledge,
    shell_text: str,
    argument_texts: list[tuple[object, object]],
):
    ran_texts = _expand(knowledge, _call(1, shell_text))[-1].ran_texts

    assert _texts_with_words(ran_texts[1:]) == argument_texts


@pytest.mark.parametrize(
    ("shell_text", "texts"),
    [
        (
            "deno",
            [(FileTextWithoutKnownWriter(0, None), Reason.DEFAULT_RUN_FILE_NOT_KNOWN)],
        ),
        # The program that sudo runs is asked too.
        (
            "sudo deno",
            [(FileTextWithoutKnownWriter(0, None), Reason.DEFAULT_RUN_FILE_NOT_KNOWN)],
        ),
        # A file that the words name is the file it runs.
        (
            "deno f.ts",
            [(FileTextWithoutKnownWriter(0, "f.ts"), Reason.NOT_WRITTEN_IN_TRIAL)],
        ),
        ("git status", []),
    ],
)
def test_a_program_whose_default_run_file_no_fact_gives_runs_an_unknown_text_only_when_its_row_runs_files(
    knowledge: ExpandedToolCallKnowledge,
    shell_text: str,
    texts: list[tuple[object, object]],
):
    ran_texts = _expand(knowledge, _call(1, shell_text))[-1].ran_texts

    assert _texts_with_words(ran_texts[1:]) == texts


def test_a_use_of_a_file_that_only_another_trajectory_wrote_asks_the_rule(
    knowledge: ExpandedToolCallKnowledge,
):
    use_counts: Counter[str] = Counter()
    results = _expand(
        knowledge,
        _call(1, WriteFileAction("f.sh", "curl a"), is_subagent=True),
        _call(2, "cat f.sh"),
        judgment_rule_use_counts=use_counts,
    )

    assert results[-1].file_touches == (_touch(0, "f.sh", Kind.SHOWS_CONTENT),)
    assert use_counts[OTHER_TRAJECTORY_RULE_NAME] == 1


def test_a_file_that_its_own_trajectory_removed_does_not_ask_the_rule(
    knowledge: ExpandedToolCallKnowledge,
):
    use_counts: Counter[str] = Counter()
    results = _expand(
        knowledge,
        _call(1, WriteFileAction("f.sh", "curl a")),
        _call(2, "rm f.sh"),
        _call(3, "bash f.sh"),
        _call(4, WriteFileAction("f.sh", "curl b"), is_subagent=True),
        judgment_rule_use_counts=use_counts,
    )

    assert results[2].ran_texts[-1] == UnknownRanText(
        FileTextWithoutKnownWriter(0, "f.sh"), Reason.NOT_WRITTEN_IN_TRIAL
    )
    assert use_counts[OTHER_TRAJECTORY_RULE_NAME] == 0


def test_the_other_choice_of_the_other_trajectory_rule_links_the_file_and_counts_one_reading(
    catalogs_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    def answer_false(*, use_counts: Counter[str]) -> bool:
        use_counts[OTHER_TRAJECTORY_RULE_NAME] += 1
        return False

    # mytool has no row, and the missing result of the run asks a rule, so `ExpandedToolCallKnowledge` and the rules count something for one reading.
    one_trajectory_knowledge = ExpandedToolCallKnowledge(catalogs_dir=catalogs_dir)
    one_trajectory_use_counts: Counter[str] = Counter()
    _expand(
        one_trajectory_knowledge,
        _call(1, WriteFileAction("f.sh", "curl a")),
        _call(2, "bash f.sh; mytool", None),
        judgment_rule_use_counts=one_trajectory_use_counts,
    )
    monkeypatch.setattr(_expand_ran_texts, OTHER_TRAJECTORY_RULE_NAME, answer_false)
    two_trajectory_knowledge = ExpandedToolCallKnowledge(catalogs_dir=catalogs_dir)
    two_trajectory_use_counts: Counter[str] = Counter()
    results = _expand(
        two_trajectory_knowledge,
        _call(1, WriteFileAction("f.sh", "curl a"), is_subagent=True),
        _call(2, "bash f.sh; mytool", None),
        judgment_rule_use_counts=two_trajectory_use_counts,
    )

    assert _texts_with_words(results[-1].ran_texts[-1:]) == [
        (FileText(0, "f.sh", K1), (("curl", "a"),))
    ]
    assert (
        one_trajectory_use_counts and one_trajectory_knowledge.uses.unknown_input_counts
    )
    assert two_trajectory_use_counts == one_trajectory_use_counts + Counter(
        {OTHER_TRAJECTORY_RULE_NAME: 1}
    )
    assert two_trajectory_knowledge.uses == one_trajectory_knowledge.uses
