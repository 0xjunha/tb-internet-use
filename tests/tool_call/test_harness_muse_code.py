"""Test the conversion of Muse Code tool calls by the Muse Code converter, with made-up results shaped as in the trajectories."""

import json
from collections import Counter
from dataclasses import replace
from typing import Any

import pytest

from tb_internet_use.knowledge.harness_result_format_declaration import (
    template_regex_of,
)
from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge
from tb_internet_use.tool_call import convert_tool_calls
from tb_internet_use.tool_call._convert_tool_calls import convert_one_tool_call
from tb_internet_use.tool_call.harnesses.muse_code import (
    _SAVED_OUTPUT_REMINDER,
    MuseCodeConverter,
)
from tb_internet_use.tool_call.model import (
    EditFileAction,
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    MatchedFormat,
    PollAction,
    ReadFileAction,
    RunCommandAction,
    SearchFilesAction,
    StartSubagentAction,
    ToolCallAction,
    ToolCallKey,
    ToolCallResult,
    UnmatchedFormat,
    WebFetchAction,
    WebSearchAction,
    WriteFileAction,
)
from tb_internet_use.tool_call.parse_shell_text import parse_shell_text

S = ExecutionStatus
CONVERTER = MuseCodeConverter()
# The reminder that Muse Code puts at the end of a truncated shell output, with a made-up path.
TRUNCATION_REMINDER_TEXT = (
    "\n<system-reminder>\nFull output saved to: /tmp/out.log\n"
    "Full output is longer than the visible window.\n"
    "Use bash tools like head, tail, cat, sed, or grep to inspect and search the full output.\n"
    "</system-reminder>"
)


def _format(name: str) -> MatchedFormat:
    return MatchedFormat(name)


def _command_handles(*handle_ids: str) -> tuple[ExecutionHandle, ...]:
    return tuple(ExecutionHandle(ExecutionHandleKind.COMMAND, i) for i in handle_ids)


def _shell(terminal_status: str, output: str, **fields: Any) -> dict[str, Any]:
    """Give a shell result object of `bash` or `bash_input` with made-up values."""
    return {
        "terminal_status": terminal_status,
        "output": output,
        "truncated": False,
        **fields,
    }


_BACKGROUND = {
    "execution_state": "background_running",
    "session_id": 4,
    "work_id": "w1",
    "output": "partial",
    "truncated": False,
}
_READ_HEAD = "Read text file `/f` (lines 1-2 of 9)"

# One made-up result per declared result format of Muse Code, built from the format, and the `ToolCallResult` it converts to.
# (tool, result text or the object of the JSON text in the trajectory, expected result)
RESULT_FORMAT_CASES: list[tuple[str, str | dict[str, Any], ToolCallResult]] = [
    (
        "bash",
        "tool failed: unmanaged shell backgrounding is not allowed",
        ToolCallResult("", S.NOT_RUN, harness_result_format=_format("rejected")),
    ),
    (
        "bash_input",
        "tool failed: no session 4",
        ToolCallResult("", S.NOT_RUN, harness_result_format=_format("rejected")),
    ),
    (
        "read_file",
        _READ_HEAD + "\n1|a\n2|b",
        ToolCallResult("a\nb", S.FINISHED, harness_result_format=_format("listing")),
    ),
    (
        "read_file",
        _READ_HEAD + "\n(2 line(s) above)\n3|c\n4|d",
        ToolCallResult(
            "c\nd", S.FINISHED, harness_result_format=_format("listing_after")
        ),
    ),
    (
        "read_file",
        _READ_HEAD + "\n1|a\n2|b\n(more lines below)",
        ToolCallResult(
            "a\nb", S.FINISHED, harness_result_format=_format("listing_before")
        ),
    ),
    (
        "read_file",
        _READ_HEAD + "\n(0 line(s) above)\n1|a\n2|b\n(more lines below)",
        ToolCallResult(
            "a\nb", S.FINISHED, harness_result_format=_format("listing_between")
        ),
    ),
    (
        "read_file",
        "Read text file `/f` (lines 10-9 of 9)\n(9 line(s) above)",
        ToolCallResult(
            "", S.FINISHED, harness_result_format=_format("listing_nothing_below")
        ),
    ),
    (
        "read_file",
        "Read text file `/f` (empty file)",
        ToolCallResult("", S.FINISHED, harness_result_format=_format("header_only")),
    ),
    (
        "read_file",
        "Read image file `/i.png` as model-visible image output.\nmedia_type: image/png\nsource_bytes: 10",
        ToolCallResult(None, S.FINISHED, harness_result_format=_format("image")),
    ),
    (
        "read_file",
        "tool failed: path is a directory",
        ToolCallResult("", S.NOT_RUN, harness_result_format=_format("rejected")),
    ),
    (
        "write_file",
        "wrote 12 bytes to /f note: created the parent folder",
        ToolCallResult("", S.FINISHED, harness_result_format=_format("written_note")),
    ),
    (
        "write_file",
        "wrote 12 bytes to /f",
        ToolCallResult("", S.FINISHED, harness_result_format=_format("written")),
    ),
    (
        "edit_file",
        "edited\nchanged lines: line 3\n",
        ToolCallResult("", S.FINISHED, harness_result_format=_format("edited")),
    ),
    (
        "edit_file",
        "tool failed: no exact match found",
        ToolCallResult("", S.NOT_RUN, harness_result_format=_format("rejected")),
    ),
    (
        "bash",
        _shell("completed", "ok", exit_code=0),
        ToolCallResult(
            "ok",
            S.FINISHED,
            0,
            is_truncated=False,
            harness_result_format=_format("exited"),
        ),
    ),
    (
        "bash",
        _shell("failed", "err", exit_code=2),
        ToolCallResult(
            "err",
            S.FINISHED,
            2,
            is_truncated=False,
            harness_result_format=_format("failed"),
        ),
    ),
    (
        "bash",
        _shell("failed", "", terminal_reason="process exited with signal: 9 (SIGKILL)"),
        ToolCallResult(
            "", S.KILLED, is_truncated=False, harness_result_format=_format("signaled")
        ),
    ),
    (
        "bash",
        _BACKGROUND,
        ToolCallResult(
            "partial",
            S.RUNNING,
            handles=_command_handles("4", "w1"),
            is_truncated=False,
            harness_result_format=_format("background"),
        ),
    ),
    (
        "bash_input",
        _shell("completed", "ok", exit_code=0),
        ToolCallResult(
            "ok",
            S.FINISHED,
            0,
            is_truncated=False,
            harness_result_format=_format("exited"),
        ),
    ),
    (
        "bash_input",
        _shell("failed", "err", exit_code=1),
        ToolCallResult(
            "err",
            S.FINISHED,
            1,
            is_truncated=False,
            harness_result_format=_format("failed"),
        ),
    ),
    (
        "bash_input",
        _shell("cancelled", "", terminal_reason="terminated by bash_input"),
        ToolCallResult(
            "", S.KILLED, is_truncated=False, harness_result_format=_format("cancelled")
        ),
    ),
    (
        "bash_input",
        _BACKGROUND,
        ToolCallResult(
            "partial",
            S.RUNNING,
            handles=_command_handles("4", "w1"),
            is_truncated=False,
            harness_result_format=_format("background"),
        ),
    ),
    (
        "work_stop",
        {"status": "accepted", "request_id": "r", "work_id": "w1"},
        ToolCallResult(
            "",
            S.KILLED,
            handles=_command_handles("w1"),
            harness_result_format=_format("accepted"),
        ),
    ),
    (
        "work_stop",
        {"status": "already_terminal", "work_id": "w1"},
        ToolCallResult(
            "",
            S.FINISHED,
            handles=_command_handles("w1"),
            harness_result_format=_format("already_ended"),
        ),
    ),
    (
        "web_search",
        {"query": "q", "results": [{"url": "u"}]},
        ToolCallResult(
            '[{"url": "u"}]', S.FINISHED, harness_result_format=_format("results")
        ),
    ),
    (
        "web_fetch",
        "tool failed: web_fetch failed: HTTP 404 Not Found",
        ToolCallResult(
            "", S.FINISHED, http_status=404, harness_result_format=_format("http_error")
        ),
    ),
    (
        "web_fetch",
        "tool failed: web_fetch failed: request failed: error sending request for url (https://a.org/): operation timed out",
        ToolCallResult("", S.FINISHED, harness_result_format=_format("request_failed")),
    ),
    (
        "web_fetch",
        "# A page\n\ntext",
        ToolCallResult(
            "# A page\n\ntext", S.FINISHED, harness_result_format=_format("page")
        ),
    ),
    (
        "monitor",
        {"work_id": "w2", "status": "started"},
        ToolCallResult(
            "",
            S.RUNNING,
            handles=_command_handles("w2"),
            harness_result_format=_format("started"),
        ),
    ),
]


# A made-up call of each tool with argument rows in the harness tool catalog, or whose action is a poll, and the `ToolCallAction` it converts to without a result.
# Every argument row has a case, and every `PollAction` states its `terminate`.
# (tool, arguments in the trajectory, expected action)
ACTION_CASES: list[tuple[str, dict[str, Any], ToolCallAction]] = [
    (
        "bash",
        {"command": "ls /app"},
        RunCommandAction(
            "ls /app", parse_shell_text("ls /app", judgment_rule_use_counts=Counter())
        ),
    ),
    (
        "monitor",
        {"command": "tail -f /app/run.log"},
        RunCommandAction(
            "tail -f /app/run.log",
            parse_shell_text(
                "tail -f /app/run.log", judgment_rule_use_counts=Counter()
            ),
        ),
    ),
    (
        "read_file",
        {"path": "/app/a.py", "offset": 10, "limit": 20},
        ReadFileAction("/app/a.py", 10, 20),
    ),
    (
        "write_file",
        {"path": "/app/a.txt", "content": "hi"},
        WriteFileAction("/app/a.txt", "hi"),
    ),
    (
        "edit_file",
        {"path": "/app/a.py", "find": "x = 1", "replace": "x = 2"},
        EditFileAction("/app/a.py", "x = 1", "x = 2"),
    ),
    (
        "search",
        {"pattern": "error", "paths": ["/app/a", "/app/b"]},
        SearchFilesAction(("/app/a", "/app/b")),
    ),
    (
        "web_search",
        {"query": "pytest fixtures"},
        WebSearchAction(("pytest fixtures",)),
    ),
    (
        "web_fetch",
        {"url": "https://a.org/docs"},
        WebFetchAction(("https://a.org/docs",)),
    ),
    ("subagent_spawn", {"objective": "find the bug"}, StartSubagentAction()),
    ("workflow", {"script": "run two agents"}, StartSubagentAction()),
    (
        "bash_input",
        {"session_id": "s1"},
        PollAction(
            (ExecutionHandle(ExecutionHandleKind.COMMAND, "s1"),), terminate=False
        ),
    ),
    (
        "bash_input",
        {"session_id": "s1", "terminate": True},
        PollAction(
            (ExecutionHandle(ExecutionHandleKind.COMMAND, "s1"),), terminate=True
        ),
    ),
    (
        "subagent_status",
        {"subagent_id": "a1"},
        PollAction(
            (ExecutionHandle(ExecutionHandleKind.SUBAGENT, "a1"),), terminate=False
        ),
    ),
    # The row gives no handle kind, so the kind stays unknown until a result names it.
    (
        "work_stop",
        {"work_id": "w1"},
        PollAction(
            (ExecutionHandle(ExecutionHandleKind.UNKNOWN, "w1"),), terminate=True
        ),
    ),
]


def _harness_tool_call(
    tool: str, args: dict[str, Any], content: Any
) -> HarnessToolCall:
    raw_text = content if isinstance(content, str) else json.dumps(content)
    return HarnessToolCall(
        ToolCallKey("t", "main", 1, 0),
        HarnessTool("muse-code", tool),
        "id",
        args,
        {"content": raw_text},
    )


def _converted(harness_tool_call: HarnessToolCall):
    return convert_one_tool_call(
        harness_tool_call,
        CONVERTER,
        knowledge=ToolCallKnowledge(),
        judgment_rule_use_counts=Counter(),
    )


def _action_of_call_without_result(tool: str, args: dict[str, Any]) -> ToolCallAction:
    """Convert one call of Muse Code without a result through `convert_tool_calls`, which picks the converter of the harness, and give its action."""
    [tool_call] = convert_tool_calls(
        [
            HarnessToolCall(
                ToolCallKey("t", "main", 1, 0),
                HarnessTool("muse-code", tool),
                "id",
                args,
                None,
            )
        ],
        knowledge=ToolCallKnowledge(),
        judgment_rule_use_counts=Counter(),
    )
    return tool_call.action


@pytest.mark.parametrize(("tool", "args", "expected"), ACTION_CASES)
def test_a_call_of_each_tool_converts_to_the_action_of_its_arguments(
    tool: str, args: dict[str, Any], expected: ToolCallAction
):
    assert _action_of_call_without_result(tool, args) == expected


@pytest.mark.parametrize(("tool", "content", "expected"), RESULT_FORMAT_CASES)
def test_a_result_of_each_declared_format_converts_to_its_fields(
    tool: str, content: str | dict[str, Any], expected: ToolCallResult
):
    assert _converted(_harness_tool_call(tool, {}, content)).result == expected


def test_bash_input_cancelled_is_killed_and_polls_the_session():
    tool_call = _converted(
        _harness_tool_call(
            "bash_input",
            {"session_id": 4, "terminate": True},
            {
                "terminal_status": "cancelled",
                "terminal_reason": "terminated by bash_input",
                "output": "",
                "truncated": False,
            },
        )
    )
    assert (
        tool_call.result is not None and tool_call.result.execution_status is S.KILLED
    )
    assert tool_call.action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "4"),), None, True
    )


def test_work_stop_is_a_terminate():
    tool_call = _converted(
        _harness_tool_call(
            "work_stop",
            {"work_id": "w1"},
            {"status": "accepted", "request_id": "r", "work_id": "w1"},
        )
    )
    assert (
        tool_call.result is not None and tool_call.result.execution_status is S.KILLED
    )
    assert tool_call.action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "w1"),), None, True
    )


def test_bash_output_loses_the_note_about_replaced_bytes():
    tool_call_result = _converted(
        _harness_tool_call(
            "bash",
            {"command": "x"},
            {
                "terminal_status": "completed",
                "exit_code": 0,
                "output": "[unified exec output: 3 invalid UTF-8 bytes replaced with U+FFFD]\nok\n",
                "truncated": False,
            },
        )
    ).result
    assert tool_call_result is not None
    assert (tool_call_result.tool_output_text, tool_call_result.exit_code) == (
        "ok\n",
        0,
    )
    single = "[unified exec output: 1 invalid UTF-8 byte replaced with U+FFFD]\nok"
    tool_call_result = _converted(
        _harness_tool_call(
            "bash",
            {"command": "x"},
            {
                "terminal_status": "completed",
                "exit_code": 0,
                "output": single,
                "truncated": False,
            },
        )
    ).result
    assert tool_call_result is not None and tool_call_result.tool_output_text == "ok"


@pytest.mark.parametrize(
    ("tool", "args"), [("bash", {"command": "x"}), ("bash_input", {"session_id": 4})]
)
def test_truncated_shell_output_loses_the_reminder_and_names_the_saved_file(tool, args):
    tool_call_result = _converted(
        _harness_tool_call(
            tool,
            args,
            {
                "terminal_status": "completed",
                "exit_code": 0,
                "output": "first lines" + TRUNCATION_REMINDER_TEXT,
                "truncated": True,
            },
        )
    ).result
    assert tool_call_result is not None
    assert (
        tool_call_result.tool_output_text,
        tool_call_result.output_path,
        tool_call_result.is_truncated,
    ) == (
        "first lines",
        "/tmp/out.log",
        True,
    )


def test_reminder_in_the_text_of_a_tool_that_is_no_shell_stays():
    text = "x" + TRUNCATION_REMINDER_TEXT
    tool_call_result = _converted(
        _harness_tool_call("subagent_spawn", {"objective": "p"}, text)
    ).result
    assert tool_call_result is not None
    assert (tool_call_result.tool_output_text, tool_call_result.output_path) == (
        text,
        None,
    )


def test_shell_result_without_text_stays_unknown():
    harness_tool_call = replace(
        _harness_tool_call("bash", {"command": "x"}, ""), result={"content": None}
    )
    tool_call_result = _converted(harness_tool_call).result
    assert tool_call_result is not None
    assert (
        tool_call_result.harness_result_format,
        tool_call_result.tool_output_text,
    ) == (UnmatchedFormat.UNKNOWN, None)


def test_bash_output_that_is_not_a_string_is_json_and_a_later_note_stays():
    def output_of(value: Any) -> str | None:
        result = {"terminal_status": "completed", "exit_code": 0, "output": value}
        tool_call_result = _converted(
            _harness_tool_call("bash", {"command": "x"}, result)
        ).result
        return None if tool_call_result is None else tool_call_result.tool_output_text

    assert output_of([1, "a"]) == '[1, "a"]'
    note = "[unified exec output: 2 invalid UTF-8 bytes replaced with U+FFFD]"
    assert output_of("ok\n" + note) == "ok\n" + note


def test_saved_output_reminder_matches_the_texts_of_its_template():
    # The step writes the pattern as a plain regex, since templates belong to `knowledge/`.
    template = (
        "{tool_output:text}\n<system-reminder>\nFull output saved to: {output_path:line}\n"
        "Full output is longer than the visible window.\n"
        "Use bash tools like head, tail, cat, sed, or grep to inspect and search the full output.\n"
        "</system-reminder>"
    )
    reminder = template.replace("{tool_output:text}", "").replace(
        "{output_path:line}", "/tmp/out.log"
    )
    texts = [
        "first lines" + reminder,
        "a\n" + reminder + reminder,
        reminder,
        "x" + reminder.replace("window.", "window!"),
        "x" + reminder.replace("/tmp/out.log", "/a\nb"),
        "x" + reminder + "\n",
    ]
    by_template = [template_regex_of(template).fullmatch(text) for text in texts]
    by_step = [_SAVED_OUTPUT_REMINDER.fullmatch(text) for text in texts]
    assert [found is not None for found in by_template] == [True] * 3 + [False] * 3
    assert [found and found.groupdict() for found in by_step] == [
        found and found.groupdict() for found in by_template
    ]
