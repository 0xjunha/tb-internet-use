"""Claude Code converter tests, with made-up results shaped as in the trajectories."""

from typing import Any

from tb_internet_use.toolcall.convert import convert_call
from tb_internet_use.toolcall.harnesses.claude_code import ClaudeCodeConverter
from tb_internet_use.toolcall.model import (
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    MatchedFormat,
    PollAction,
    RawToolCall,
    ToolCallKey,
    UnmatchedFormat,
)

S = ExecutionStatus
CONVERTER = ClaudeCodeConverter()


def _raw(tool: str, args: dict[str, Any], result: dict[str, Any]) -> RawToolCall:
    return RawToolCall(
        ToolCallKey("t", "main", 1, 0),
        HarnessTool("claude-code", tool),
        "id",
        args,
        result,
    )


def _result(
    block: Any, structured: dict[str, Any] | None = None, is_error: bool | None = None
) -> dict[str, Any]:
    """A result as Harbor writes it in the trajectory: the original block kept in the metadata, blocks appended to content."""
    metadata: dict[str, Any] = {
        "raw_tool_result": {"type": "tool_result", "content": block}
    }
    if structured is not None:
        metadata["tool_use_result"] = structured
    extra: dict[str, Any] = {"tool_result_metadata": metadata}
    if is_error is not None:
        extra["tool_result_is_error"] = is_error
    return {"content": "(harbor view)", "extra": extra}


def _bash(
    block: str, structured: dict[str, Any] | None = None, is_error: bool | None = None
):
    return convert_call(
        _raw("Bash", {"command": "x"}, _result(block, structured, is_error)), CONVERTER
    ).output


def test_bash_body_without_header_is_exit_zero_and_structured_stdout_wins():
    structured = {"stdout": "full stdout\n", "stderr": "", "interrupted": False}
    output = _bash("shown", structured)
    assert output is not None
    assert (output.execution_status, output.tool_output_text, output.exit_code) == (
        S.FINISHED,
        "full stdout\n",
        0,
    )
    assert output.harness_result_format == MatchedFormat("bare_output")


def test_bash_exit_code_without_header_needs_the_structured_result():
    no_match = {"stdout": "", "interrupted": False}
    output = _bash(
        "(Bash completed with no output)",
        {**no_match, "returnCodeInterpretation": "No matches found"},
    )
    assert output is not None and (output.exit_code, output.tool_output_text) == (1, "")
    output = _bash("shown")  # no structured result: 0 and 1 look the same
    assert output is not None and (output.execution_status, output.exit_code) == (
        S.FINISHED,
        None,
    )
    output = _bash("shown", {"stdout": "shown", "interrupted": True})
    assert output is not None and output.exit_code is None


def test_bash_background_notice_names_the_task_and_its_output_file():
    block = (
        "Command running in background with ID: b1a2c3d4e. Output is being written to: /tmp/b1a2c3d4e.output."
        " You will be notified when it completes. To check interim output, use Read on that file path."
    )
    output = _bash(block)
    assert output is not None
    assert output.execution_status is S.RUNNING
    assert output.handles == (
        ExecutionHandle(ExecutionHandleKind.COMMAND, "b1a2c3d4e"),
    )
    assert output.output_path == "/tmp/b1a2c3d4e.output"
    assert output.tool_output_text == ""


def test_bash_structured_result_gives_the_task_and_the_saved_output():
    block = (
        "Command running in background with ID: b1. Output is being written to: /tmp/b1.output."
        " You will be notified when it completes. To check interim output, use Read on that file path."
    )
    output = _bash(
        block, {"stdout": "", "backgroundTaskId": "b2", "interrupted": False}
    )
    assert output is not None
    assert (output.handles, output.exit_code) == (
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "b2"),),
        None,  # still running, so no exit code
    )
    output = _bash(
        "big",
        {"stdout": "big", "persistedOutputPath": "/tmp/p.txt", "interrupted": False},
    )
    assert output is not None
    assert (output.output_path, output.is_truncated) == ("/tmp/p.txt", True)


def test_bash_structured_result_does_not_touch_an_unmatched_result():
    output = _bash("something else went wrong", {"stdout": "x"}, is_error=True)
    assert output is not None
    assert (output.harness_result_format, output.tool_output_text) == (
        UnmatchedFormat.UNKNOWN,
        "something else went wrong",
    )


def test_trailing_notices_are_cut_from_bash_and_write_results():
    for block in (
        "out\nShell cwd was reset to /app",
        "out\n[This command modified 2 files you've previously read: a, b]",
        "out\n\nSession cwd was changed to /app",
        "out\nSession cwd was changed to /app",
    ):
        output = _bash(block)
        assert output is not None and output.tool_output_text == "out", block
    for block in ("Shell cwd was reset to /app", "[This command modified 1 file]"):
        output = _bash(block)
        assert output is not None and output.tool_output_text == "", block
    output = convert_call(
        _raw(
            "Write",
            {"file_path": "/a"},
            _result(
                "File created successfully at: /a\n\n"
                "Note: Write's parameters are named file_path and content."
            ),
        ),
        CONVERTER,
    ).output
    assert output is not None
    assert output.harness_result_format == MatchedFormat("created")


def test_bash_background_notice_after_partial_output_is_recognized():
    block = (
        "early line\n"
        "Command running in background with ID: abc123xyz."
        " Output is being written to: /tmp/abc123xyz.output."
        " You will be notified when it completes. To check interim output, use Read on that file path."
    )
    output = _bash(block)
    assert output is not None
    assert output.execution_status is S.RUNNING
    assert output.handles[0].id == "abc123xyz"
    assert output.tool_output_text == "early line"


def test_bash_error_output_cut_by_claude_code_is_truncated_and_keeps_the_marker():
    text = "head\n... [120 characters truncated] ...\ntail"
    output = _bash("Exit code 1\n" + text, is_error=True)
    assert output is not None
    assert (output.is_truncated, output.tool_output_text) == (True, text)
    output = _bash("Exit code 1\nwhole", is_error=True)
    assert output is not None and output.is_truncated is None


def test_bash_timeout_with_cut_output_has_no_exit_code_and_is_truncated():
    output = _bash(
        "Exit code 143\nCommand timed out after 2m\nhead\n... [9 characters truncated] ...\ntail",
        is_error=True,
    )
    assert output is not None
    assert (output.execution_status, output.exit_code, output.is_truncated) == (
        S.TIMED_OUT,
        None,
        True,
    )


def test_structured_result_that_is_not_an_object_is_ignored():
    output = _bash("shown", "not an object")  # type: ignore[arg-type]
    assert output is not None and output.tool_output_text == "shown"


def test_bash_exit_header_and_timeout():
    output = _bash("Exit code 2\nboom", is_error=True)
    assert output is not None
    assert (output.execution_status, output.exit_code, output.tool_output_text) == (
        S.FINISHED,
        2,
        "boom",
    )
    output = _bash("Exit code 143\nCommand timed out after 2m 0.0s", is_error=True)
    assert output is not None
    assert (output.execution_status, output.exit_code, output.tool_output_text) == (
        S.TIMED_OUT,
        None,
        "",
    )


def test_bash_refusals_are_not_run_and_an_unlabeled_error_body_is_unknown_format():
    for block in (
        "Permission to use Bash with command rm -rf x has been denied.",
        "Dangerous rm operation detected: '/x' This is blocked.",
        "This Bash command contains multiple operations. Split them.",
        "<tool_use_error>InputValidationError: bad</tool_use_error>",
    ):
        output = _bash(block, is_error=True)
        assert output is not None and output.execution_status is S.NOT_RUN, block
    # The classifier stopped a call that was running and may have completed.
    output = _bash(
        "Interrupted: the response that made this tool call was stopped by a safety classifier.",
        is_error=True,
    )
    assert output is not None and output.execution_status is S.UNKNOWN
    output = _bash("something else went wrong", is_error=True)
    assert output is not None
    assert (output.execution_status, output.harness_result_format) == (
        S.UNKNOWN,
        UnmatchedFormat.UNKNOWN,
    )


def test_read_listing_without_structured_result_loses_line_numbers():
    output = convert_call(
        _raw("Read", {"file_path": "/a"}, _result("1\ta\n2\tb\n3")), CONVERTER
    ).output
    assert output is not None
    assert (
        output.tool_output_text,
        output.execution_status,
        output.harness_result_format,
    ) == (
        "a\nb\n",
        S.FINISHED,
        MatchedFormat("listing"),
    )


def test_read_structured_file_content_is_the_text():
    structured = {
        "type": "text",
        "file": {"filePath": "/a", "content": "a\r\nb\n", "numLines": 2},
    }
    output = convert_call(
        _raw("Read", {"file_path": "/a"}, _result("1\ta\n2\tb\n3", structured)),
        CONVERTER,
    ).output
    assert output is not None and output.tool_output_text == "a\r\nb\n"


def test_read_cut_at_the_token_cap_is_truncated():
    structured = {
        "type": "text",
        "file": {"filePath": "/a", "content": "a\n", "truncatedByTokenCap": True},
    }
    output = convert_call(
        _raw("Read", {"file_path": "/a"}, _result("1\ta\n", structured)),
        CONVERTER,
    ).output
    assert output is not None and output.is_truncated is True


def test_read_image_items_give_no_text_and_finished():
    block = [{"type": "image", "source": {"type": "base64", "data": "AAAA"}}]
    output = convert_call(
        _raw("Read", {"file_path": "/i.png"}, _result(block)), CONVERTER
    ).output
    assert output is not None
    assert (
        output.tool_output_text,
        output.execution_status,
        output.harness_result_format,
    ) == (
        None,
        S.FINISHED,
        MatchedFormat("image"),
    )


def test_read_pdf_has_no_text_and_an_unchanged_file_is_not_read():
    def read(block: str):
        return convert_call(
            _raw("Read", {"file_path": "/d.pdf"}, _result(block)), CONVERTER
        ).output

    output = read("PDF file read: /d.pdf (102.8KB)")
    assert output is not None and (
        output.tool_output_text,
        output.execution_status,
    ) == (
        None,
        S.FINISHED,
    )
    output = read(
        "Wasted call — file unchanged since your last Read. Refer to that earlier tool_result instead."
    )
    assert output is not None and (
        output.tool_output_text,
        output.execution_status,
    ) == (
        "",
        S.NOT_RUN,
    )


def test_harbor_json_items_without_a_metadata_block_are_decoded():
    content = '{"type": "text", "text": "File created successfully at: /f.py"}'
    output = convert_call(
        _raw("Write", {"file_path": "/f.py"}, {"content": content}), CONVERTER
    ).output
    assert output is not None
    assert (output.execution_status, output.harness_result_format) == (
        S.FINISHED,
        MatchedFormat("created"),
    )


def test_failed_file_tool_is_not_run():
    block = "<tool_use_error>File has not been read yet. Read it first before writing to it.</tool_use_error>"
    output = convert_call(
        _raw("Edit", {"file_path": "/f"}, _result(block, is_error=True)), CONVERTER
    ).output
    assert output is not None and output.execution_status is S.NOT_RUN


def test_task_output_uses_the_structured_task():
    structured = {
        "retrieval_status": "success",
        "task": {
            "task_id": "t1",
            "task_type": "local_agent",
            "status": "completed",
            "output": "all good",
            "exitCode": 0,
        },
    }
    call = convert_call(
        _raw(
            "TaskOutput",
            {"task_id": "t1"},
            _result("<retrieval_status>success</retrieval_status>", structured),
        ),
        CONVERTER,
    )
    assert call.output is not None
    assert (
        call.output.execution_status,
        call.output.tool_output_text,
        call.output.exit_code,
    ) == (
        S.FINISHED,
        "all good",
        0,
    )
    assert call.output.handles == (ExecutionHandle(ExecutionHandleKind.SUBAGENT, "t1"),)
    assert call.action == PollAction(call.output.handles)


def test_task_stop_is_a_terminate_whose_target_is_killed():
    call = convert_call(
        _raw(
            "TaskStop",
            {"task_id": "t1"},
            _result(
                '{"message":"Successfully stopped task: t1 (sleep 99)","task_id":"t1",'
                '"task_type":"local_bash","command":"sleep 99"}'
            ),
        ),
        CONVERTER,
    )
    assert call.output is not None and call.output.execution_status is S.KILLED
    assert call.action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "t1"),), None, True
    )


def test_web_tools_that_reached_the_server_are_finished_even_on_errors():
    for block, name in (
        (
            "The server returned HTTP 404 Not Found\n\nThe response body was not retrieved. Try another URL.",
            "http_error_body_not_retrieved",
        ),
        ("connect ECONNREFUSED 1.2.3.4:443", "connection_error"),
    ):
        output = convert_call(
            _raw("WebFetch", {"url": "u"}, _result(block)), CONVERTER
        ).output
        assert output is not None
        assert (
            output.execution_status,
            output.harness_result_format,
            output.tool_output_text,
        ) == (S.FINISHED, MatchedFormat(name), "")
    output = convert_call(
        _raw(
            "WebFetch",
            {"url": "u"},
            _result("<tool_use_error>Invalid URL</tool_use_error>", is_error=True),
        ),
        CONVERTER,
    ).output
    assert output is not None and output.execution_status is S.NOT_RUN


def test_other_tools_have_skipped_format():
    output = convert_call(
        _raw("Agent", {"prompt": "p"}, _result("Async agent launched")), CONVERTER
    ).output
    assert output is not None
    assert (
        output.execution_status,
        output.harness_result_format,
        output.tool_output_text,
    ) == (
        S.UNKNOWN,
        UnmatchedFormat.SKIPPED,
        "Async agent launched",
    )


def test_task_stop_wrapped_as_persisted_output_is_still_a_kill():
    block = (
        "<persisted-output>\nOutput too large (3.1KB). Full output saved to: /tmp/p.txt\n\nPreview (first 2KB):\n"
        '{"message":"Successfully stopped task: t9 (python3 server.py)","task_id":"t9"'
    )
    output = convert_call(
        _raw("TaskStop", {"task_id": "t9"}, _result(block)), CONVERTER
    ).output
    assert output is not None
    assert (
        output.execution_status,
        output.tool_output_text,
        output.output_path,
        output.is_truncated,
    ) == (S.KILLED, "", "/tmp/p.txt", True)
    assert output.handles == (ExecutionHandle(ExecutionHandleKind.COMMAND, "t9"),)


def test_web_search_wrapped_as_persisted_output_loses_its_inner_header():
    block = (
        "<persisted-output>\nOutput too large (5.0KB). Full output saved to: /tmp/w.txt\n\nPreview (first 2KB):\n"
        'Web search results for query: "q"\n\nLinks: []\n\nsummary\n</persisted-output>'
    )
    output = convert_call(
        _raw("WebSearch", {"query": "q"}, _result(block)), CONVERTER
    ).output
    assert output is not None
    assert (
        output.harness_result_format,
        output.tool_output_text,
        output.is_truncated,
    ) == (
        MatchedFormat("persisted_results"),
        "Links: []\n\nsummary",
        True,
    )


def test_bash_background_notice_that_warns_about_the_final_response_is_running():
    block = (
        "Command running in background with ID: b1a2c3d4e. Output is being written to: /tmp/b1a2c3d4e.output."
        " If it exits while you are still working you will be notified, but it is terminated when you give"
        " your final response.\nSession cwd remains /app; directory changes do not apply."
    )
    output = _bash(block)
    assert output is not None
    assert output.harness_result_format == MatchedFormat("background_v3")
    assert (output.execution_status, output.output_path, output.tool_output_text) == (
        S.RUNNING,
        "/tmp/b1a2c3d4e.output",
        "",
    )
    assert output.handles == (
        ExecutionHandle(ExecutionHandleKind.COMMAND, "b1a2c3d4e"),
    )


def test_web_fetch_without_a_model_response_has_no_text_even_with_a_saved_binary():
    saved = "\n\n[Binary content (application/pdf, 1.2 MB) also saved to /tmp/page.pdf]"
    for block in ("No response from model", "No response from model" + saved):
        output = convert_call(
            _raw("WebFetch", {"url": "u"}, _result(block)), CONVERTER
        ).output
        assert output is not None
        assert (output.tool_output_text, output.execution_status) == ("", S.FINISHED)
