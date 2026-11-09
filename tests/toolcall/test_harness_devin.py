"""Devin converter tests, with made-up results shaped as in the trajectories."""

from typing import Any

from tb_internet_use.toolcall.convert import convert_call
from tb_internet_use.toolcall.harnesses.devin import DevinConverter
from tb_internet_use.toolcall.model import (
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    MatchedFormat,
    PollAction,
    RawToolCall,
    ToolCallKey,
)

S = ExecutionStatus
CONVERTER = DevinConverter()
BACKGROUND = "Command running in background with ID: sh1. Run get_output with timeout if you need to wait."


def _raw(tool: str, args: dict[str, Any], content: str) -> RawToolCall:
    return RawToolCall(
        ToolCallKey("t", "main", 1, 0),
        HarnessTool("devin", tool),
        "id",
        args,
        {"content": content},
    )


def test_exec_exited_names_the_shell_and_exit_code():
    output = convert_call(
        _raw(
            "exec",
            {"command": "x"},
            "Output from command in shell sh1:\nhi\nExit code: 0",
        ),
        CONVERTER,
    ).output
    assert output is not None
    assert (output.execution_status, output.exit_code, output.tool_output_text) == (
        S.FINISHED,
        0,
        "hi",
    )
    assert output.handles == (ExecutionHandle(ExecutionHandleKind.COMMAND, "sh1"),)


def test_exec_moved_to_background_after_partial_output():
    content = (
        "line\n\n===\nStopped waiting for output after 30.0 seconds. " + BACKGROUND
    )
    output = convert_call(_raw("exec", {"command": "x"}, content), CONVERTER).output
    assert output is not None
    assert (output.execution_status, output.tool_output_text, output.handles[0].id) == (
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
    output = convert_call(_raw("exec", {"command": "x"}, content), CONVERTER).output
    assert output is not None
    assert (output.exit_code, output.is_truncated, output.output_path) == (
        1,
        True,
        "/tmp/out.txt",
    )
    assert output.tool_output_text == "a\n… (40 lines truncated)\nz"


def test_get_output_without_exit_line_is_still_running_with_the_argument_shell():
    call = convert_call(
        _raw("get_output", {"shell_id": "sh1"}, "more lines\n"), CONVERTER
    )
    assert call.output is not None
    assert (call.output.execution_status, call.output.tool_output_text) == (
        S.RUNNING,
        "more lines\n",
    )
    assert call.action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "sh1"),)
    )
    assert call.output.handles == ()  # the result named no shell
    output = convert_call(
        _raw("get_output", {"shell_id": "sh1"}, "tail\nExit code: 3"), CONVERTER
    ).output
    assert output is not None and (output.execution_status, output.exit_code) == (
        S.FINISHED,
        3,
    )


def test_shell_output_with_a_cut_line_is_truncated_and_keeps_the_marker():
    output = convert_call(
        _raw(
            "exec",
            {"command": "x"},
            "Output from command in shell sh1:\nlong… (300 chars truncated)\nExit code: 0",
        ),
        CONVERTER,
    ).output
    assert output is not None and output.is_truncated is True
    text = "a\nlong… (300 chars truncated)\n"
    output = convert_call(
        _raw("get_output", {"shell_id": "sh1"}, text), CONVERTER
    ).output
    assert output is not None
    assert (output.is_truncated, output.tool_output_text) == (True, text)
    output = convert_call(
        _raw("get_output", {"shell_id": "sh1"}, "a\n"), CONVERTER
    ).output
    assert output is not None and output.is_truncated is None


def test_a_shell_named_in_the_result_wins_over_the_argument():
    call = convert_call(
        _raw(
            "get_output",
            {"shell_id": "sh1"},
            "No more output to read. Shell sh2 exited with code 0.",
        ),
        CONVERTER,
    )
    assert call.action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "sh2"),)
    )
    output = convert_call(
        _raw(
            "exec",
            {"command": "x", "shell_id": "sh1"},
            "Shell sh3 changed directory to /x\nOutput from command in shell sh3:\nhi\nExit code: 0",
        ),
        CONVERTER,
    ).output
    assert output is not None
    assert (output.handles, output.tool_output_text) == (
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "sh3"),),
        "hi",
    )


def test_read_image_has_no_text():
    output = convert_call(
        _raw("read", {"file_path": "/i.png"}, "[Image 1]"), CONVERTER
    ).output
    assert output is not None
    assert (output.execution_status, output.tool_output_text) == (S.FINISHED, None)


def test_kill_shell_is_a_terminate_whose_target_is_killed():
    call = convert_call(
        _raw("kill_shell", {"shell_id": "sh1"}, "Shell sh1 terminated successfully"),
        CONVERTER,
    )
    assert call.output is not None and call.output.execution_status is S.KILLED
    assert call.action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "sh1"),), None, True
    )


def test_read_listing_loses_line_numbers():
    content = '<file-view path="/f" start_line="1" end_line="2" total_lines="2">\n  1|a\n  2|b\n</file-view>'
    output = convert_call(_raw("read", {"file_path": "/f"}, content), CONVERTER).output
    assert output is not None and (
        output.tool_output_text,
        output.execution_status,
    ) == (
        "a\nb",
        S.FINISHED,
    )


def test_rejected_tool_calls_are_not_run():
    output = convert_call(
        _raw(
            "edit",
            {"file_path": "/f"},
            "Tool 'edit' validation failed: String not found in file.",
        ),
        CONVERTER,
    ).output
    assert output is not None and output.execution_status is S.NOT_RUN


def test_webfetch_page_and_http_error():
    output = convert_call(
        _raw("webfetch", {"url": "u"}, "# Web Content from http://x\n\nhello"),
        CONVERTER,
    ).output
    assert output is not None and (
        output.tool_output_text,
        output.execution_status,
    ) == (
        "\nhello",
        S.FINISHED,
    )
    output = convert_call(
        _raw("webfetch", {"url": "u"}, "HTTP request failed with status: 404"),
        CONVERTER,
    ).output
    assert output is not None and (
        output.tool_output_text,
        output.execution_status,
    ) == (
        "",
        S.FINISHED,
    )


def test_negative_exit_code_means_killed_without_a_real_exit_code():
    output = convert_call(
        _raw(
            "exec",
            {"command": "pkill -f x"},
            "Output from command in shell sh1:\n\nExit code: -1",
        ),
        CONVERTER,
    ).output
    assert output is not None
    assert (output.execution_status, output.exit_code, output.tool_output_text) == (
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
        output = convert_call(
            _raw(tool, {"shell_id": "sh1"}, content), CONVERTER
        ).output
        assert output is not None
        assert (output.execution_status, output.exit_code) == (S.KILLED, None), content


def test_live_file_preview_keeps_only_the_listed_lines():
    content = (
        "Output from command in shell sh1. The full terminal output is being written live to /tmp/live.log; "
        "read or grep it for anything omitted below. Preview:\n"
        '<file-view path="/tmp/live.log" start_line="1" end_line="2" total_lines="9">\n  1|a\n  2|b\n</file-view>\n'
        "\u2026 5 lines omitted \u2026\n"
        '<file-view path="/tmp/live.log" start_line="8" end_line="9" total_lines="9">\n  8|y\n  9|z\n</file-view>\n\nExit code: 0'
    )
    output = convert_call(_raw("exec", {"command": "x"}, content), CONVERTER).output
    assert output is not None
    assert (
        output.tool_output_text,
        output.output_path,
        output.is_truncated,
        output.exit_code,
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
    output = convert_call(
        _raw("get_output", {"shell_id": "sh1"}, content), CONVERTER
    ).output
    assert output is not None
    assert (output.execution_status, output.tool_output_text) == (
        S.RUNNING,
        "old\nnew1\nnew2\n",
    )
    output = convert_call(
        _raw("get_output", {"shell_id": "sh1"}, content + "Exit code: 0"), CONVERTER
    ).output
    assert output is not None and (
        output.execution_status,
        output.exit_code,
        output.tool_output_text,
    ) == (S.FINISHED, 0, "old\nnew1\nnew2")


def test_web_search_with_crlf_lines_is_recognized():
    content = '# Web Search Results for "q"\r\nline\r\n<truncation_notice>\nFull output written to: /tmp/s.txt\n</truncation_notice>'
    output = convert_call(_raw("web_search", {"query": "q"}, content), CONVERTER).output
    assert output is not None
    assert (
        output.harness_result_format,
        output.tool_output_text,
        output.is_truncated,
    ) == (
        MatchedFormat("results_crlf_truncated"),
        "line\r",
        True,
    )


def test_browser_preview_is_running_with_a_preview_handle():
    output = convert_call(
        _raw(
            "browser_preview",
            {"url": "http://localhost:3000"},
            "Browser preview running with ID: p1\nTarget: http://localhost:3000",
        ),
        CONVERTER,
    ).output
    assert output is not None
    assert (output.execution_status, output.handles) == (
        S.RUNNING,
        (ExecutionHandle(ExecutionHandleKind.UNKNOWN, "p1"),),
    )


def test_doubled_exit_lines_without_output():
    output = convert_call(
        _raw(
            "get_output",
            {"shell_id": "sh1"},
            "Exited with code 2 and no output\n\nExit code: 2",
        ),
        CONVERTER,
    ).output
    assert output is not None and (
        output.harness_result_format,
        output.exit_code,
        output.tool_output_text,
    ) == (MatchedFormat("exited_silent_twice"), 2, "")
    output = convert_call(
        _raw(
            "get_output",
            {"shell_id": "sh1"},
            "Exited with code -1 and no output\n\nExit code: -1",
        ),
        CONVERTER,
    ).output
    assert output is not None and (output.execution_status, output.exit_code) == (
        S.KILLED,
        None,
    )


def test_timeout_warning_right_after_the_header_leaves_text():
    content = (
        "Output from command in shell sh1:\n"
        "Warning: requested timeout 10m exceeds maximum of 5m 0s; clamping to 5m 0s.\n"
        "hi\nExit code: 0"
    )
    output = convert_call(_raw("exec", {"command": "x"}, content), CONVERTER).output
    assert output is not None
    assert (
        output.harness_result_format,
        output.tool_output_text,
        output.exit_code,
    ) == (
        MatchedFormat("exited_after_warning"),
        "hi",
        0,
    )
