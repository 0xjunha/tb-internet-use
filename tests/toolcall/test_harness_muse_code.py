"""Muse Code converter tests, with made-up results shaped as in the trajectories."""

import json
from typing import Any

from tb_internet_use.toolcall.convert import convert_call
from tb_internet_use.toolcall.harnesses.muse_code import MuseCodeConverter
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
CONVERTER = MuseCodeConverter()


def _raw(tool: str, args: dict[str, Any], content: Any) -> RawToolCall:
    raw_text = content if isinstance(content, str) else json.dumps(content)
    return RawToolCall(
        ToolCallKey("t", "main", 1, 0),
        HarnessTool("muse-code", tool),
        "id",
        args,
        {"content": raw_text},
    )


def test_bash_states():
    output = convert_call(
        _raw(
            "bash",
            {"command": "x"},
            {
                "terminal_status": "completed",
                "exit_code": 0,
                "output": "ok",
                "truncated": False,
            },
        ),
        CONVERTER,
    ).output
    assert output is not None and (
        output.execution_status,
        output.exit_code,
        output.tool_output_text,
        output.is_truncated,
    ) == (S.FINISHED, 0, "ok", False)
    output = convert_call(
        _raw(
            "bash",
            {"command": "x"},
            {
                "terminal_status": "failed",
                "terminal_reason": "process exited with signal: 9 (SIGKILL)",
                "output": "",
                "truncated": False,
            },
        ),
        CONVERTER,
    ).output
    assert output is not None and (output.execution_status, output.exit_code) == (
        S.KILLED,
        None,
    )
    output = convert_call(
        _raw(
            "bash",
            {"command": "x"},
            {
                "execution_state": "background_running",
                "session_id": 4,
                "output": "partial",
                "truncated": False,
            },
        ),
        CONVERTER,
    ).output
    assert output is not None and output.execution_status is S.RUNNING
    assert output.handles == (ExecutionHandle(ExecutionHandleKind.COMMAND, "4"),)


def test_bash_text_failure_is_not_run():
    output = convert_call(
        _raw(
            "bash",
            {"command": "x &"},
            "tool failed: unmanaged shell backgrounding is not allowed",
        ),
        CONVERTER,
    ).output
    assert output is not None and output.execution_status is S.NOT_RUN


def test_bash_input_cancelled_is_killed_and_polls_the_session():
    call = convert_call(
        _raw(
            "bash_input",
            {"session_id": 4, "terminate": True},
            {
                "terminal_status": "cancelled",
                "terminal_reason": "terminated by bash_input",
                "output": "",
                "truncated": False,
            },
        ),
        CONVERTER,
    )
    assert call.output is not None and call.output.execution_status is S.KILLED
    assert call.action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "4"),), None, True
    )


def test_work_stop_is_a_terminate():
    call = convert_call(
        _raw(
            "work_stop",
            {"work_id": "w1"},
            {"status": "accepted", "request_id": "r", "work_id": "w1"},
        ),
        CONVERTER,
    )
    assert call.output is not None and call.output.execution_status is S.KILLED
    assert call.action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "w1"),), None, True
    )


def test_read_file_listing_variants():
    content = "Read text file `/f` (lines 1-2 of 9)\n(0 line(s) above)\n1|a\n2|b\n(more lines below)"
    output = convert_call(_raw("read_file", {"path": "/f"}, content), CONVERTER).output
    assert output is not None and (
        output.tool_output_text,
        output.harness_result_format,
    ) == (
        "a\nb",
        MatchedFormat("listing_between"),
    )
    output = convert_call(
        _raw(
            "read_file",
            {"path": "/i"},
            "Read image file `/i.png` as model-visible image output.\nmedia_type: image/png\nsource_bytes: 10",
        ),
        CONVERTER,
    ).output
    assert output is not None and (
        output.tool_output_text,
        output.execution_status,
    ) == (
        None,
        S.FINISHED,
    )


def test_write_and_edit():
    output = convert_call(
        _raw("write_file", {"path": "/f"}, "wrote 12 bytes to /f"), CONVERTER
    ).output
    assert output is not None and output.execution_status is S.FINISHED
    output = convert_call(
        _raw("edit_file", {"path": "/f"}, "edited\nchanged lines: line 3\n"), CONVERTER
    ).output
    assert output is not None and (
        output.execution_status,
        output.tool_output_text,
    ) == (
        S.FINISHED,
        "",
    )
    output = convert_call(
        _raw("edit_file", {"path": "/f"}, "tool failed: no exact match found"),
        CONVERTER,
    ).output
    assert output is not None and output.execution_status is S.NOT_RUN


def test_web_search_results_are_kept_as_json_text():
    output = convert_call(
        _raw("web_search", {"query": "q"}, {"query": "q", "results": [{"url": "u"}]}),
        CONVERTER,
    ).output
    assert output is not None and (
        output.execution_status,
        output.tool_output_text,
    ) == (
        S.FINISHED,
        '[{"url": "u"}]',
    )


def test_background_shell_names_the_session_and_the_work_as_commands():
    output = convert_call(
        _raw(
            "bash",
            {"command": "x"},
            {
                "execution_state": "background_running",
                "session_id": 4,
                "work_id": "w1",
                "output": "",
                "truncated": False,
            },
        ),
        CONVERTER,
    ).output
    assert output is not None
    assert [(h.kind, h.id) for h in output.handles] == [
        (ExecutionHandleKind.COMMAND, "4"),
        (ExecutionHandleKind.COMMAND, "w1"),
    ]


def test_bash_output_loses_the_note_about_replaced_bytes():
    output = convert_call(
        _raw(
            "bash",
            {"command": "x"},
            {
                "terminal_status": "completed",
                "exit_code": 0,
                "output": "[unified exec output: 3 invalid UTF-8 bytes replaced with U+FFFD]\nok\n",
                "truncated": False,
            },
        ),
        CONVERTER,
    ).output
    assert output is not None
    assert (output.tool_output_text, output.exit_code) == ("ok\n", 0)
    single = "[unified exec output: 1 invalid UTF-8 byte replaced with U+FFFD]\nok"
    output = convert_call(
        _raw(
            "bash",
            {"command": "x"},
            {
                "terminal_status": "completed",
                "exit_code": 0,
                "output": single,
                "truncated": False,
            },
        ),
        CONVERTER,
    ).output
    assert output is not None and output.tool_output_text == "ok"


def test_truncated_bash_output_loses_the_reminder_and_names_the_saved_file():
    reminder = (
        "\n<system-reminder>\nFull output saved to: /tmp/out.log\n"
        "Full output is longer than the visible window.\n"
        "Use bash tools like head, tail, cat, sed, or grep to inspect and search the full output.\n"
        "</system-reminder>"
    )
    output = convert_call(
        _raw(
            "bash",
            {"command": "x"},
            {
                "terminal_status": "completed",
                "exit_code": 0,
                "output": "first lines" + reminder,
                "truncated": True,
            },
        ),
        CONVERTER,
    ).output
    assert output is not None
    assert (output.tool_output_text, output.output_path, output.is_truncated) == (
        "first lines",
        "/tmp/out.log",
        True,
    )


def test_bash_output_that_is_not_a_string_is_json_and_a_later_note_stays():
    def output_of(value: Any) -> str | None:
        result = {"terminal_status": "completed", "exit_code": 0, "output": value}
        output = convert_call(_raw("bash", {"command": "x"}, result), CONVERTER).output
        return None if output is None else output.tool_output_text

    assert output_of([1, "a"]) == '[1, "a"]'
    note = "[unified exec output: 2 invalid UTF-8 bytes replaced with U+FFFD]"
    assert output_of("ok\n" + note) == "ok\n" + note
