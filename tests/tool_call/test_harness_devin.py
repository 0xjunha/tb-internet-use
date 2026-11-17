"""Test the conversion of Devin tool calls, which use the shared converter, with made-up results shaped as in the trajectories."""

from collections import Counter
from typing import Any

import pytest

from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge
from tb_internet_use.tool_call import convert_tool_calls
from tb_internet_use.tool_call._convert_tool_calls import convert_one_tool_call
from tb_internet_use.tool_call.harnesses import converter_for
from tb_internet_use.tool_call.model import (
    EditFileAction,
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    ListFilesAction,
    MatchedFormat,
    PollAction,
    ReadFileAction,
    RunCommandAction,
    SearchFilesAction,
    StartSubagentAction,
    ToolCallAction,
    ToolCallKey,
    ToolCallResult,
    WebFetchAction,
    WebSearchAction,
    WriteFileAction,
)

S = ExecutionStatus
CONVERTER = converter_for("devin")
BACKGROUND = "Command running in background with ID: sh1. Run get_output with timeout if you need to wait."


def _harness_tool_call(
    tool: str, args: dict[str, Any], content: str
) -> HarnessToolCall:
    return HarnessToolCall(
        ToolCallKey("t", "main", 1, 0),
        HarnessTool("devin", tool),
        "id",
        args,
        {"content": content},
    )


def _converted(harness_tool_call: HarnessToolCall):
    return convert_one_tool_call(
        harness_tool_call,
        CONVERTER,
        knowledge=ToolCallKnowledge(),
        judgment_rule_use_counts=Counter(),
    )


def _action_of_call_without_result(tool: str, args: dict[str, Any]) -> ToolCallAction:
    """Convert one call of Devin without a result through `convert_tool_calls`, which picks the converter of the harness, and give its action."""
    [tool_call] = convert_tool_calls(
        [
            HarnessToolCall(
                ToolCallKey("t", "main", 1, 0),
                HarnessTool("devin", tool),
                "id",
                args,
                None,
            )
        ],
        knowledge=ToolCallKnowledge(),
        judgment_rule_use_counts=Counter(),
    )
    return tool_call.action


_OUT = "Output from command in shell sh1:\n"
_WARNING = (
    "Warning: requested timeout 10m exceeds maximum of 5m 0s; clamping to 5m 0s.\n"
)
_NOTICE = (
    "<truncation_notice>\nFull output written to: /tmp/o.txt\n</truncation_notice>"
)
_STOPPED = "line\n\n===\nStopped waiting for output after 30.0 seconds. "
_LIVE = (
    "Output from command in shell sh1. The full terminal output is being written live to /tmp/live.log; "
    "read or grep it for anything omitted below. Preview:\n"
    '<file-view path="/tmp/live.log" start_line="1" end_line="2" total_lines="9">\n  1|a\n  2|b\n</file-view>\n'
    "… 5 lines omitted …\n"
)
_LIVE_TAIL = '<file-view path="/tmp/live.log" start_line="8" end_line="9" total_lines="9">\n  8|y\n  9|z\n</file-view>\n'
_DIFF_HEAD = (
    "[Changes since your last read, shown as a unified diff: '+' lines are new, '-' lines were "
    "replaced/removed in place, ' ' lines are unchanged context; '@@' line numbers index into the full output.]\n"
)
_DIFF = "@@ -3,2 +3,3 @@\n old\n-gone\n+new1\n+new2\n"
_SNIPPET = "The file /f has been updated. Here's the result of running `cat -n` on a snippet of the edited file:\n  1|a\n  2|b"
_CUT_LINES = "\n… (40 lines truncated)\n"
_SHELL_1 = (ExecutionHandle(ExecutionHandleKind.COMMAND, "sh1"),)


def _format(name: str) -> MatchedFormat:
    return MatchedFormat(name)


def _rejected_case(tool: str) -> tuple[str, str, ToolCallResult]:
    """Give the case of the `rejected` format of a tool, a call whose arguments failed validation."""
    return (
        tool,
        f"Tool '{tool}' validation failed: a required argument is missing",
        ToolCallResult("", S.NOT_RUN, harness_result_format=_format("rejected")),
    )


def _updated_cases(tool: str) -> list[tuple[str, str, ToolCallResult]]:
    """List the cases of the formats that `write` and `edit` share, of a file they changed."""
    return [
        (
            tool,
            _SNIPPET
            + _CUT_LINES
            + "<truncation_notice>\nFull output written to: /tmp/w.txt\n</truncation_notice>",
            ToolCallResult(
                "",
                S.FINISHED,
                output_path="/tmp/w.txt",
                is_truncated=True,
                harness_result_format=_format("updated_truncated_note"),
            ),
        ),
        (
            tool,
            _SNIPPET,
            ToolCallResult("", S.FINISHED, harness_result_format=_format("updated")),
        ),
    ]


# One made-up result per declared result format of Devin, built from the format, and the `ToolCallResult` it converts to.
# (tool, result text in the trajectory, expected result)
RESULT_FORMAT_CASES: list[tuple[str, str, ToolCallResult]] = [
    (
        "exec",
        _OUT + "\nExit code: -1",
        ToolCallResult(
            "", S.KILLED, handles=_SHELL_1, harness_result_format=_format("killed")
        ),
    ),
    (
        "exec",
        _OUT + _WARNING + "hi\nExit code: 1\n\nnote\n" + _NOTICE,
        ToolCallResult(
            "hi",
            S.FINISHED,
            1,
            handles=_SHELL_1,
            output_path="/tmp/o.txt",
            is_truncated=True,
            harness_result_format=_format("exited_truncated_after_warning"),
        ),
    ),
    (
        "exec",
        _OUT + _WARNING + "hi\nExit code: 0",
        ToolCallResult(
            "hi",
            S.FINISHED,
            0,
            handles=_SHELL_1,
            harness_result_format=_format("exited_after_warning"),
        ),
    ),
    (
        "exec",
        _OUT + "a\nz\nExit code: 1\n\nnote\n" + _NOTICE,
        ToolCallResult(
            "a\nz",
            S.FINISHED,
            1,
            handles=_SHELL_1,
            output_path="/tmp/o.txt",
            is_truncated=True,
            harness_result_format=_format("exited_truncated"),
        ),
    ),
    (
        "exec",
        _OUT + "hi\nExit code: 0",
        ToolCallResult(
            "hi",
            S.FINISHED,
            0,
            handles=_SHELL_1,
            harness_result_format=_format("exited"),
        ),
    ),
    (
        "exec",
        _LIVE + _LIVE_TAIL + "\nExit code: 0",
        ToolCallResult(
            "a\nb\ny\nz",
            S.FINISHED,
            0,
            handles=_SHELL_1,
            output_path="/tmp/live.log",
            is_truncated=True,
            harness_result_format=_format("exited_live_file"),
        ),
    ),
    (
        "exec",
        _LIVE + "\nExit code: 0",
        ToolCallResult(
            "a\nb",
            S.FINISHED,
            0,
            handles=_SHELL_1,
            output_path="/tmp/live.log",
            is_truncated=True,
            harness_result_format=_format("exited_live_file_head"),
        ),
    ),
    (
        "exec",
        "No output produced after 30 seconds. " + BACKGROUND,
        ToolCallResult(
            "",
            S.RUNNING,
            handles=_SHELL_1,
            harness_result_format=_format("background_silent"),
        ),
    ),
    (
        "exec",
        _STOPPED + BACKGROUND + "\n" + _NOTICE,
        ToolCallResult(
            "line",
            S.RUNNING,
            handles=_SHELL_1,
            output_path="/tmp/o.txt",
            is_truncated=True,
            harness_result_format=_format("background_after_output_truncated"),
        ),
    ),
    (
        "exec",
        _STOPPED + BACKGROUND,
        ToolCallResult(
            "line",
            S.RUNNING,
            handles=_SHELL_1,
            harness_result_format=_format("background_after_output"),
        ),
    ),
    (
        "exec",
        "Command running in background with ID: sh1",
        ToolCallResult(
            "",
            S.RUNNING,
            handles=_SHELL_1,
            harness_result_format=_format("background_requested"),
        ),
    ),
    _rejected_case("exec"),
    (
        "exec",
        "`env` can only be set when starting a new shell; start one with a new shell_id",
        ToolCallResult("", S.NOT_RUN, harness_result_format=_format("rejected_env")),
    ),
    (
        "exec",
        "Shell sh1 still has a running command. Wait for it first.",
        ToolCallResult(
            "",
            S.NOT_RUN,
            handles=_SHELL_1,
            harness_result_format=_format("rejected_busy"),
        ),
    ),
    (
        "get_output",
        "Exited with code -1 and no output\n\nExit code: -1",
        ToolCallResult(
            "", S.KILLED, harness_result_format=_format("killed_silent_twice")
        ),
    ),
    (
        "get_output",
        "Exited with code 2 and no output\n\nExit code: 2",
        ToolCallResult(
            "", S.FINISHED, 2, harness_result_format=_format("exited_silent_twice")
        ),
    ),
    (
        "get_output",
        _DIFF_HEAD + _DIFF + "Exit code: 0",
        ToolCallResult(
            "old\nnew1\nnew2",
            S.FINISHED,
            0,
            harness_result_format=_format("exited_incremental"),
        ),
    ),
    (
        "get_output",
        _DIFF_HEAD + _DIFF,
        ToolCallResult(
            "old\nnew1\nnew2\n",
            S.RUNNING,
            harness_result_format=_format("running_incremental"),
        ),
    ),
    (
        "get_output",
        "tail\nExit code: 3",
        ToolCallResult("tail", S.FINISHED, 3, harness_result_format=_format("exited")),
    ),
    (
        "get_output",
        "No more output to read. Shell sh2 exited with code 0.",
        ToolCallResult(
            "",
            S.FINISHED,
            0,
            handles=(ExecutionHandle(ExecutionHandleKind.COMMAND, "sh2"),),
            harness_result_format=_format("exited_no_more"),
        ),
    ),
    (
        "get_output",
        "No output yet (still running)",
        ToolCallResult("", S.RUNNING, harness_result_format=_format("running_silent")),
    ),
    _rejected_case("get_output"),
    (
        "get_output",
        "more lines\n",
        ToolCallResult(
            "more lines\n", S.RUNNING, harness_result_format=_format("running")
        ),
    ),
    (
        "kill_shell",
        "Shell sh1 terminated successfully",
        ToolCallResult(
            "", S.KILLED, handles=_SHELL_1, harness_result_format=_format("killed")
        ),
    ),
    _rejected_case("kill_shell"),
    (
        "write_to_process",
        "Written 3 bytes to shell sh1",
        ToolCallResult(
            "", S.RUNNING, handles=_SHELL_1, harness_result_format=_format("written")
        ),
    ),
    (
        "read",
        '<file-view path="/f" start_line="1" end_line="2" total_lines="2">\n  1|a\n  2|b\n</file-view>',
        ToolCallResult("a\nb", S.FINISHED, harness_result_format=_format("listing")),
    ),
    (
        "read",
        "[Image 1]",
        ToolCallResult(None, S.FINISHED, harness_result_format=_format("image")),
    ),
    _rejected_case("read"),
    (
        "write",
        "File created successfully at: /f",
        ToolCallResult("", S.FINISHED, harness_result_format=_format("created")),
    ),
    *_updated_cases("write"),
    (
        "write",
        _SNIPPET
        + "\nlong line cut"
        + _CUT_LINES
        + "<truncation_notice>\nFull output written to: /tmp/w.txt\n</truncation_notice>",
        ToolCallResult(
            "",
            S.FINISHED,
            output_path="/tmp/w.txt",
            is_truncated=True,
            harness_result_format=_format("updated_truncated_cut_line"),
        ),
    ),
    _rejected_case("write"),
    *_updated_cases("edit"),
    _rejected_case("edit"),
    (
        "webfetch",
        "# Web Content from http://x\nhello\n" + _NOTICE,
        ToolCallResult(
            "hello",
            S.FINISHED,
            output_path="/tmp/o.txt",
            is_truncated=True,
            harness_result_format=_format("page_truncated"),
        ),
    ),
    (
        "webfetch",
        "# Web Content from http://x\n\nhello",
        ToolCallResult("\nhello", S.FINISHED, harness_result_format=_format("page")),
    ),
    # A fetch that got an error status from the server ended on its own.
    (
        "webfetch",
        "HTTP request failed with status: 404",
        ToolCallResult(
            "", S.FINISHED, http_status=404, harness_result_format=_format("http_error")
        ),
    ),
    _rejected_case("webfetch"),
    (
        "web_search",
        '# Web Search Results for "q"\nline\n' + _NOTICE,
        ToolCallResult(
            "line",
            S.FINISHED,
            output_path="/tmp/o.txt",
            is_truncated=True,
            harness_result_format=_format("results_truncated"),
        ),
    ),
    (
        "web_search",
        '# Web Search Results for "q"\r\nline\r\n' + _NOTICE,
        ToolCallResult(
            "line\r",
            S.FINISHED,
            output_path="/tmp/o.txt",
            is_truncated=True,
            harness_result_format=_format("results_crlf_truncated"),
        ),
    ),
    (
        "web_search",
        '# Web Search Results for "q"\nline',
        ToolCallResult("line", S.FINISHED, harness_result_format=_format("results")),
    ),
    (
        "browser_preview",
        "Browser preview running with ID: p1\nTarget: http://localhost:3000",
        ToolCallResult(
            "",
            S.RUNNING,
            handles=(ExecutionHandle(ExecutionHandleKind.UNKNOWN, "p1"),),
            harness_result_format=_format("preview_running"),
        ),
    ),
]


# A made-up call of each tool with argument rows in the harness tool catalog, or whose action is a poll, and the `ToolCallAction` it converts to without a result.
# Every argument row has a case, and every `PollAction` states its `terminate`.
# (tool, arguments in the trajectory, expected action)
ACTION_CASES: list[tuple[str, dict[str, Any], ToolCallAction]] = [
    ("exec", {"command": "ls /app", "shell_id": "sh1"}, RunCommandAction("ls /app")),
    (
        "read",
        {"file_path": "/app/a.py", "offset": 10, "limit": 20},
        ReadFileAction("/app/a.py", 10, 20),
    ),
    (
        "write",
        {"file_path": "/app/a.txt", "content": "hi"},
        WriteFileAction("/app/a.txt", "hi"),
    ),
    (
        "edit",
        {"file_path": "/app/a.py", "old_string": "x = 1", "new_string": "x = 2"},
        EditFileAction("/app/a.py", "x = 1", "x = 2"),
    ),
    ("grep", {"pattern": "error", "path": "/app"}, SearchFilesAction(("/app",))),
    (
        "find_file_by_name",
        {"pattern": "*.log", "path": "/app"},
        ListFilesAction("/app"),
    ),
    (
        "webfetch",
        {"url": "https://example.org/a"},
        WebFetchAction(("https://example.org/a",)),
    ),
    (
        "browser_preview",
        {"url": "http://localhost:3000"},
        WebFetchAction(("http://localhost:3000",)),
    ),
    (
        "web_search",
        {"query": "pytest fixtures"},
        WebSearchAction(("pytest fixtures",)),
    ),
    ("run_subagent", {"task": "find the bug"}, StartSubagentAction()),
    (
        "get_output",
        {"shell_id": "sh1"},
        PollAction(
            (ExecutionHandle(ExecutionHandleKind.COMMAND, "sh1"),), terminate=False
        ),
    ),
    (
        "write_to_process",
        {"shell_id": "sh1", "text_input": "y\n"},
        PollAction(
            (ExecutionHandle(ExecutionHandleKind.COMMAND, "sh1"),),
            "y\n",
            terminate=False,
        ),
    ),
    (
        "kill_shell",
        {"shell_id": "sh1"},
        PollAction(
            (ExecutionHandle(ExecutionHandleKind.COMMAND, "sh1"),), terminate=True
        ),
    ),
    (
        "read_subagent",
        {"agent_id": "a1"},
        PollAction(
            (ExecutionHandle(ExecutionHandleKind.SUBAGENT, "a1"),), terminate=False
        ),
    ),
]


@pytest.mark.parametrize(("tool", "args", "expected"), ACTION_CASES)
def test_a_call_of_each_tool_converts_to_the_action_of_its_arguments(
    tool: str, args: dict[str, Any], expected: ToolCallAction
):
    assert _action_of_call_without_result(tool, args) == expected


@pytest.mark.parametrize(("tool", "content", "expected"), RESULT_FORMAT_CASES)
def test_a_result_of_each_declared_format_converts_to_its_fields(
    tool: str, content: str, expected: ToolCallResult
):
    assert _converted(_harness_tool_call(tool, {}, content)).result == expected


def test_exec_warning_notice_is_cut_and_truncated_output_keeps_the_cut_line():
    content = (
        "Warning: requested timeout 10m exceeds maximum of 5m 0s; clamping to 5m 0s.\n"
        "Output from command in shell sh1:\na\n… (40 lines truncated)\nz\nExit code: 1\n\n"
        "`| head -42` was parsed out (42 of 200 total lines shown).\n"
        "<truncation_notice>\nFull output written to: /tmp/out.txt\n</truncation_notice>"
    )
    tool_call_result = _converted(
        _harness_tool_call("exec", {"command": "x"}, content)
    ).result
    assert tool_call_result is not None
    assert (
        tool_call_result.exit_code,
        tool_call_result.is_truncated,
        tool_call_result.output_path,
    ) == (
        1,
        True,
        "/tmp/out.txt",
    )
    assert tool_call_result.tool_output_text == "a\n… (40 lines truncated)\nz"


def test_get_output_without_exit_line_is_still_running_with_the_argument_shell():
    tool_call = _converted(
        _harness_tool_call("get_output", {"shell_id": "sh1"}, "more lines\n")
    )
    assert tool_call.result is not None
    assert (tool_call.result.execution_status, tool_call.result.tool_output_text) == (
        S.RUNNING,
        "more lines\n",
    )
    assert tool_call.action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "sh1"),)
    )
    assert tool_call.result.handles == ()  # the result named no shell


def test_shell_output_with_a_cut_line_is_truncated_and_keeps_the_marker():
    tool_call_result = _converted(
        _harness_tool_call(
            "exec",
            {"command": "x"},
            "Output from command in shell sh1:\nlong… (300 chars truncated)\nExit code: 0",
        )
    ).result
    assert tool_call_result is not None and tool_call_result.is_truncated is True
    text = "a\nlong… (300 chars truncated)\n"
    tool_call_result = _converted(
        _harness_tool_call("get_output", {"shell_id": "sh1"}, text)
    ).result
    assert tool_call_result is not None
    assert (tool_call_result.is_truncated, tool_call_result.tool_output_text) == (
        True,
        text,
    )
    tool_call_result = _converted(
        _harness_tool_call("get_output", {"shell_id": "sh1"}, "a\n")
    ).result
    assert tool_call_result is not None and tool_call_result.is_truncated is None
    # A poll of a command that exited keeps the marker too.
    tool_call_result = _converted(
        _harness_tool_call("get_output", {"shell_id": "sh1"}, text + "Exit code: 0")
    ).result
    assert tool_call_result is not None
    assert (tool_call_result.is_truncated, tool_call_result.harness_result_format) == (
        True,
        MatchedFormat("exited"),
    )


def test_a_shell_named_in_the_result_wins_over_the_argument():
    tool_call = _converted(
        _harness_tool_call(
            "get_output",
            {"shell_id": "sh1"},
            "No more output to read. Shell sh2 exited with code 0.",
        )
    )
    assert tool_call.action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "sh2"),)
    )
    tool_call_result = _converted(
        _harness_tool_call(
            "exec",
            {"command": "x", "shell_id": "sh1"},
            "Shell sh3 changed directory to /x\nOutput from command in shell sh3:\nhi\nExit code: 0",
        )
    ).result
    assert tool_call_result is not None
    assert (tool_call_result.handles, tool_call_result.tool_output_text) == (
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "sh3"),),
        "hi",
    )
