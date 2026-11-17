"""Devin converter tests, with made-up results shaped as in the trajectories."""

from collections import Counter
from typing import Any

from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge
from tb_internet_use.tool_call._convert_tool_calls import convert_one_tool_call
from tb_internet_use.tool_call.harnesses.devin import DevinConverter
from tb_internet_use.tool_call.model import (
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    MatchedFormat,
    PollAction,
    ToolCallKey,
)

S = ExecutionStatus
CONVERTER = DevinConverter()
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


def test_exec_exited_names_the_shell_and_exit_code():
    tool_call_result = _converted(
        _harness_tool_call(
            "exec",
            {"command": "x"},
            "Output from command in shell sh1:\nhi\nExit code: 0",
        )
    ).result
    assert tool_call_result is not None
    assert (
        tool_call_result.execution_status,
        tool_call_result.exit_code,
        tool_call_result.tool_output_text,
    ) == (
        S.FINISHED,
        0,
        "hi",
    )
    assert tool_call_result.handles == (
        ExecutionHandle(ExecutionHandleKind.COMMAND, "sh1"),
    )


def test_exec_moved_to_background_after_partial_output():
    content = (
        "line\n\n===\nStopped waiting for output after 30.0 seconds. " + BACKGROUND
    )
    tool_call_result = _converted(
        _harness_tool_call("exec", {"command": "x"}, content)
    ).result
    assert tool_call_result is not None
    assert (
        tool_call_result.execution_status,
        tool_call_result.tool_output_text,
        tool_call_result.handles[0].id,
    ) == (
        S.RUNNING,
        "line",
        "sh1",
    )


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
    call = _converted(
        _harness_tool_call("get_output", {"shell_id": "sh1"}, "more lines\n")
    )
    assert call.result is not None
    assert (call.result.execution_status, call.result.tool_output_text) == (
        S.RUNNING,
        "more lines\n",
    )
    assert call.action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "sh1"),)
    )
    assert call.result.handles == ()  # the result named no shell
    tool_call_result = _converted(
        _harness_tool_call("get_output", {"shell_id": "sh1"}, "tail\nExit code: 3")
    ).result
    assert tool_call_result is not None and (
        tool_call_result.execution_status,
        tool_call_result.exit_code,
    ) == (
        S.FINISHED,
        3,
    )


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


def test_a_shell_named_in_the_result_wins_over_the_argument():
    call = _converted(
        _harness_tool_call(
            "get_output",
            {"shell_id": "sh1"},
            "No more output to read. Shell sh2 exited with code 0.",
        )
    )
    assert call.action == PollAction(
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


def test_read_image_has_no_text():
    tool_call_result = _converted(
        _harness_tool_call("read", {"file_path": "/i.png"}, "[Image 1]")
    ).result
    assert tool_call_result is not None
    assert (tool_call_result.execution_status, tool_call_result.tool_output_text) == (
        S.FINISHED,
        None,
    )


def test_kill_shell_is_a_terminate_whose_target_is_killed():
    call = _converted(
        _harness_tool_call(
            "kill_shell", {"shell_id": "sh1"}, "Shell sh1 terminated successfully"
        )
    )
    assert call.result is not None and call.result.execution_status is S.KILLED
    assert call.action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "sh1"),), None, True
    )


def test_read_listing_loses_line_numbers():
    content = '<file-view path="/f" start_line="1" end_line="2" total_lines="2">\n  1|a\n  2|b\n</file-view>'
    tool_call_result = _converted(
        _harness_tool_call("read", {"file_path": "/f"}, content)
    ).result
    assert tool_call_result is not None and (
        tool_call_result.tool_output_text,
        tool_call_result.execution_status,
    ) == (
        "a\nb",
        S.FINISHED,
    )


def test_rejected_tool_calls_are_not_run():
    tool_call_result = _converted(
        _harness_tool_call(
            "edit",
            {"file_path": "/f"},
            "Tool 'edit' validation failed: String not found in file.",
        )
    ).result
    assert (
        tool_call_result is not None and tool_call_result.execution_status is S.NOT_RUN
    )


def test_webfetch_page_and_http_error():
    tool_call_result = _converted(
        _harness_tool_call(
            "webfetch", {"url": "u"}, "# Web Content from http://x\n\nhello"
        )
    ).result
    assert tool_call_result is not None and (
        tool_call_result.tool_output_text,
        tool_call_result.execution_status,
    ) == (
        "\nhello",
        S.FINISHED,
    )
    tool_call_result = _converted(
        _harness_tool_call(
            "webfetch", {"url": "u"}, "HTTP request failed with status: 404"
        )
    ).result
    assert tool_call_result is not None and (
        tool_call_result.tool_output_text,
        tool_call_result.execution_status,
        tool_call_result.http_status,
    ) == (
        "",
        S.FINISHED,
        404,
    )


def test_negative_exit_code_means_killed_without_a_real_exit_code():
    tool_call_result = _converted(
        _harness_tool_call(
            "exec",
            {"command": "pkill -f x"},
            "Output from command in shell sh1:\n\nExit code: -1",
        )
    ).result
    assert tool_call_result is not None
    assert (
        tool_call_result.execution_status,
        tool_call_result.exit_code,
        tool_call_result.tool_output_text,
    ) == (
        S.KILLED,
        None,
        "",
    )


def test_any_negative_exit_code_is_killed_whatever_the_format():
    for tool, content in (
        ("get_output", "foo\nExit code: -1"),
        ("get_output", "No more output to read. Shell s1 exited with code -1."),
        (
            "exec",
            "Output from command in shell sh1:\nfoo\nExit code: -1\n\nnote\n<truncation_notice>\nFull output written to: /o\n</truncation_notice>",
        ),
    ):
        tool_call_result = _converted(
            _harness_tool_call(tool, {"shell_id": "sh1"}, content)
        ).result
        assert tool_call_result is not None
        assert (tool_call_result.execution_status, tool_call_result.exit_code) == (
            S.KILLED,
            None,
        ), content


def test_live_file_preview_keeps_only_the_listed_lines():
    content = (
        "Output from command in shell sh1. The full terminal output is being written live to /tmp/live.log; "
        "read or grep it for anything omitted below. Preview:\n"
        '<file-view path="/tmp/live.log" start_line="1" end_line="2" total_lines="9">\n  1|a\n  2|b\n</file-view>\n'
        "\u2026 5 lines omitted \u2026\n"
        '<file-view path="/tmp/live.log" start_line="8" end_line="9" total_lines="9">\n  8|y\n  9|z\n</file-view>\n\nExit code: 0'
    )
    tool_call_result = _converted(
        _harness_tool_call("exec", {"command": "x"}, content)
    ).result
    assert tool_call_result is not None
    assert (
        tool_call_result.tool_output_text,
        tool_call_result.output_path,
        tool_call_result.is_truncated,
        tool_call_result.exit_code,
    ) == (
        "a\nb\ny\nz",
        "/tmp/live.log",
        True,
        0,
    )


def test_incremental_get_output_keeps_new_and_context_lines_only():
    header = (
        "[Changes since your last read, shown as a unified diff: '+' lines are new, '-' lines were "
        "replaced/removed in place, ' ' lines are unchanged context; '@@' line numbers index into the full output.]"
    )
    content = header + "\n@@ -3,2 +3,3 @@\n old\n-gone\n+new1\n+new2\n"
    tool_call_result = _converted(
        _harness_tool_call("get_output", {"shell_id": "sh1"}, content)
    ).result
    assert tool_call_result is not None
    assert (tool_call_result.execution_status, tool_call_result.tool_output_text) == (
        S.RUNNING,
        "old\nnew1\nnew2\n",
    )
    tool_call_result = _converted(
        _harness_tool_call("get_output", {"shell_id": "sh1"}, content + "Exit code: 0")
    ).result
    assert tool_call_result is not None and (
        tool_call_result.execution_status,
        tool_call_result.exit_code,
        tool_call_result.tool_output_text,
    ) == (S.FINISHED, 0, "old\nnew1\nnew2")


def test_web_search_with_crlf_lines_is_recognized():
    content = '# Web Search Results for "q"\r\nline\r\n<truncation_notice>\nFull output written to: /tmp/s.txt\n</truncation_notice>'
    tool_call_result = _converted(
        _harness_tool_call("web_search", {"query": "q"}, content)
    ).result
    assert tool_call_result is not None
    assert (
        tool_call_result.harness_result_format,
        tool_call_result.tool_output_text,
        tool_call_result.is_truncated,
    ) == (
        MatchedFormat("results_crlf_truncated"),
        "line\r",
        True,
    )


def test_browser_preview_is_running_with_a_preview_handle():
    tool_call_result = _converted(
        _harness_tool_call(
            "browser_preview",
            {"url": "http://localhost:3000"},
            "Browser preview running with ID: p1\nTarget: http://localhost:3000",
        )
    ).result
    assert tool_call_result is not None
    assert (tool_call_result.execution_status, tool_call_result.handles) == (
        S.RUNNING,
        (ExecutionHandle(ExecutionHandleKind.UNKNOWN, "p1"),),
    )


def test_doubled_exit_lines_without_output():
    tool_call_result = _converted(
        _harness_tool_call(
            "get_output",
            {"shell_id": "sh1"},
            "Exited with code 2 and no output\n\nExit code: 2",
        )
    ).result
    assert tool_call_result is not None and (
        tool_call_result.harness_result_format,
        tool_call_result.exit_code,
        tool_call_result.tool_output_text,
    ) == (MatchedFormat("exited_silent_twice"), 2, "")
    tool_call_result = _converted(
        _harness_tool_call(
            "get_output",
            {"shell_id": "sh1"},
            "Exited with code -1 and no output\n\nExit code: -1",
        )
    ).result
    assert tool_call_result is not None and (
        tool_call_result.execution_status,
        tool_call_result.exit_code,
    ) == (
        S.KILLED,
        None,
    )


def test_timeout_warning_right_after_the_header_leaves_text():
    content = (
        "Output from command in shell sh1:\n"
        "Warning: requested timeout 10m exceeds maximum of 5m 0s; clamping to 5m 0s.\n"
        "hi\nExit code: 0"
    )
    tool_call_result = _converted(
        _harness_tool_call("exec", {"command": "x"}, content)
    ).result
    assert tool_call_result is not None
    assert (
        tool_call_result.harness_result_format,
        tool_call_result.tool_output_text,
        tool_call_result.exit_code,
    ) == (
        MatchedFormat("exited_after_warning"),
        "hi",
        0,
    )
