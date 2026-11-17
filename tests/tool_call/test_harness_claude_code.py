"""Claude Code converter tests, with made-up results shaped as in the trajectories."""

import json
from collections import Counter
from typing import Any

from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge
from tb_internet_use.tool_call._convert_tool_calls import convert_one_tool_call
from tb_internet_use.tool_call.harnesses.claude_code import (
    ClaudeCodeConverter,
    _join_content_items,
)
from tb_internet_use.tool_call.model import (
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    MatchedFormat,
    PollAction,
    ToolCallKey,
    ToolCallResult,
    UnmatchedFormat,
)

S = ExecutionStatus
CONVERTER = ClaudeCodeConverter()


def _harness_tool_call(
    tool: str, args: dict[str, Any], result: dict[str, Any]
) -> HarnessToolCall:
    return HarnessToolCall(
        ToolCallKey("t", "main", 1, 0),
        HarnessTool("claude-code", tool),
        "id",
        args,
        result,
    )


def _converted(harness_tool_call: HarnessToolCall):
    return convert_one_tool_call(
        harness_tool_call,
        CONVERTER,
        knowledge=ToolCallKnowledge(),
        judgment_rule_use_counts=Counter(),
    )


def _result(
    block: Any, structured: dict[str, Any] | None = None, is_error: bool | None = None
) -> dict[str, Any]:
    """A result as Harbor writes it in the trajectory, with the original block kept in the metadata and blocks appended to content."""
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
    return _converted(
        _harness_tool_call(
            "Bash", {"command": "x"}, _result(block, structured, is_error)
        )
    ).result


IMAGE = {"type": "image", "source": {}}
# A Bash background notice, with a made-up id and path.
BACKGROUND_NOTICE = "Command running in background with ID: b1. Output is being written to: /tmp/b1.output. You will be notified when it completes. To check interim output, use Read on that file path."


def _converted_result(
    tool: str, args: dict[str, Any], result: dict[str, Any]
) -> ToolCallResult:
    tool_call_result = _converted(_harness_tool_call(tool, args, result)).result
    assert tool_call_result is not None
    return tool_call_result


def _bash_format_and_text(result: dict[str, Any]) -> tuple[object, str | None]:
    tool_call_result = _converted_result("Bash", {"command": "x"}, result)
    return tool_call_result.harness_result_format, tool_call_result.tool_output_text


def test_bash_body_without_header_is_exit_zero_and_structured_stdout_wins():
    structured = {"stdout": "full stdout\n", "stderr": "", "interrupted": False}
    tool_call_result = _bash("shown", structured)
    assert tool_call_result is not None
    assert (
        tool_call_result.execution_status,
        tool_call_result.tool_output_text,
        tool_call_result.exit_code,
    ) == (
        S.FINISHED,
        "full stdout\n",
        0,
    )
    assert tool_call_result.harness_result_format == MatchedFormat("bare_output")


def test_bash_exit_code_without_header_needs_the_structured_result():
    no_match = {"stdout": "", "interrupted": False}
    tool_call_result = _bash(
        "(Bash completed with no output)",
        {**no_match, "returnCodeInterpretation": "No matches found"},
    )
    assert tool_call_result is not None and (
        tool_call_result.exit_code,
        tool_call_result.tool_output_text,
    ) == (1, "")
    tool_call_result = _bash("shown")  # no structured result, so 0 and 1 look the same
    assert tool_call_result is not None and (
        tool_call_result.execution_status,
        tool_call_result.exit_code,
    ) == (
        S.FINISHED,
        None,
    )
    tool_call_result = _bash("shown", {"stdout": "shown", "interrupted": True})
    assert tool_call_result is not None and tool_call_result.exit_code is None


def test_bash_background_notice_names_the_task_and_its_output_file():
    block = (
        "Command running in background with ID: b1a2c3d4e. Output is being written to: /tmp/b1a2c3d4e.output."
        " You will be notified when it completes. To check interim output, use Read on that file path."
    )
    tool_call_result = _bash(block)
    assert tool_call_result is not None
    assert tool_call_result.execution_status is S.RUNNING
    assert tool_call_result.handles == (
        ExecutionHandle(ExecutionHandleKind.COMMAND, "b1a2c3d4e"),
    )
    assert tool_call_result.output_path == "/tmp/b1a2c3d4e.output"
    assert tool_call_result.tool_output_text == ""


def test_bash_structured_result_gives_the_task_and_the_saved_output():
    block = (
        "Command running in background with ID: b1. Output is being written to: /tmp/b1.output."
        " You will be notified when it completes. To check interim output, use Read on that file path."
    )
    tool_call_result = _bash(
        block, {"stdout": "", "backgroundTaskId": "b2", "interrupted": False}
    )
    assert tool_call_result is not None
    assert (tool_call_result.handles, tool_call_result.exit_code) == (
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "b2"),),
        None,  # still running, so no exit code
    )
    tool_call_result = _bash(
        "big",
        {"stdout": "big", "persistedOutputPath": "/tmp/p.txt", "interrupted": False},
    )
    assert tool_call_result is not None
    assert (tool_call_result.output_path, tool_call_result.is_truncated) == (
        "/tmp/p.txt",
        True,
    )


def test_bash_structured_result_does_not_touch_an_unmatched_result():
    tool_call_result = _bash(
        "something else went wrong", {"stdout": "x"}, is_error=True
    )
    assert tool_call_result is not None
    assert (
        tool_call_result.harness_result_format,
        tool_call_result.tool_output_text,
    ) == (
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
        tool_call_result = _bash(block)
        assert (
            tool_call_result is not None and tool_call_result.tool_output_text == "out"
        ), block
    for block in ("Shell cwd was reset to /app", "[This command modified 1 file]"):
        tool_call_result = _bash(block)
        assert (
            tool_call_result is not None and tool_call_result.tool_output_text == ""
        ), block
    tool_call_result = _converted(
        _harness_tool_call(
            "Write",
            {"file_path": "/a"},
            _result(
                "File created successfully at: /a\n\n"
                "Note: Write's parameters are named file_path and content."
            ),
        )
    ).result
    assert tool_call_result is not None
    assert tool_call_result.harness_result_format == MatchedFormat("created")


def test_bash_background_notice_after_partial_output_is_recognized():
    block = (
        "early line\n"
        "Command running in background with ID: abc123xyz."
        " Output is being written to: /tmp/abc123xyz.output."
        " You will be notified when it completes. To check interim output, use Read on that file path."
    )
    tool_call_result = _bash(block)
    assert tool_call_result is not None
    assert tool_call_result.execution_status is S.RUNNING
    assert tool_call_result.handles[0].id == "abc123xyz"
    assert tool_call_result.tool_output_text == "early line"


def test_bash_error_output_cut_by_claude_code_is_truncated_and_keeps_the_marker():
    text = "head\n... [120 characters truncated] ...\ntail"
    tool_call_result = _bash("Exit code 1\n" + text, is_error=True)
    assert tool_call_result is not None
    assert (tool_call_result.is_truncated, tool_call_result.tool_output_text) == (
        True,
        text,
    )
    tool_call_result = _bash("Exit code 1\nwhole", is_error=True)
    assert tool_call_result is not None and tool_call_result.is_truncated is None


def test_bash_timeout_with_cut_output_has_no_exit_code_and_is_truncated():
    tool_call_result = _bash(
        "Exit code 143\nCommand timed out after 2m\nhead\n... [9 characters truncated] ...\ntail",
        is_error=True,
    )
    assert tool_call_result is not None
    assert (
        tool_call_result.execution_status,
        tool_call_result.exit_code,
        tool_call_result.is_truncated,
    ) == (
        S.TIMED_OUT,
        None,
        True,
    )


def test_structured_result_that_is_not_an_object_is_ignored():
    tool_call_result = _bash("shown", "not an object")  # type: ignore[arg-type]
    assert tool_call_result is not None and tool_call_result.tool_output_text == "shown"


def test_bash_exit_header_and_timeout():
    tool_call_result = _bash("Exit code 2\nboom", is_error=True)
    assert tool_call_result is not None
    assert (
        tool_call_result.execution_status,
        tool_call_result.exit_code,
        tool_call_result.tool_output_text,
    ) == (
        S.FINISHED,
        2,
        "boom",
    )
    tool_call_result = _bash(
        "Exit code 143\nCommand timed out after 2m 0.0s", is_error=True
    )
    assert tool_call_result is not None
    assert (
        tool_call_result.execution_status,
        tool_call_result.exit_code,
        tool_call_result.tool_output_text,
    ) == (
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
        tool_call_result = _bash(block, is_error=True)
        assert (
            tool_call_result is not None
            and tool_call_result.execution_status is S.NOT_RUN
        ), block
    # The classifier stopped a call that was running and may have completed.
    tool_call_result = _bash(
        "Interrupted: the response that made this tool call was stopped by a safety classifier.",
        is_error=True,
    )
    assert (
        tool_call_result is not None and tool_call_result.execution_status is S.UNKNOWN
    )
    tool_call_result = _bash("something else went wrong", is_error=True)
    assert tool_call_result is not None
    assert (
        tool_call_result.execution_status,
        tool_call_result.harness_result_format,
    ) == (
        S.UNKNOWN,
        UnmatchedFormat.UNKNOWN,
    )


def test_read_listing_without_structured_result_loses_line_numbers():
    tool_call_result = _converted(
        _harness_tool_call("Read", {"file_path": "/a"}, _result("1\ta\n2\tb\n3"))
    ).result
    assert tool_call_result is not None
    assert (
        tool_call_result.tool_output_text,
        tool_call_result.execution_status,
        tool_call_result.harness_result_format,
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
    tool_call_result = _converted(
        _harness_tool_call(
            "Read", {"file_path": "/a"}, _result("1\ta\n2\tb\n3", structured)
        )
    ).result
    assert (
        tool_call_result is not None and tool_call_result.tool_output_text == "a\r\nb\n"
    )


def test_read_cut_at_the_token_cap_is_truncated():
    structured = {
        "type": "text",
        "file": {"filePath": "/a", "content": "a\n", "truncatedByTokenCap": True},
    }
    tool_call_result = _converted(
        _harness_tool_call("Read", {"file_path": "/a"}, _result("1\ta\n", structured))
    ).result
    assert tool_call_result is not None and tool_call_result.is_truncated is True


def test_read_image_items_give_no_text_and_finished():
    block = [{"type": "image", "source": {"type": "base64", "data": "AAAA"}}]
    tool_call_result = _converted(
        _harness_tool_call("Read", {"file_path": "/i.png"}, _result(block))
    ).result
    assert tool_call_result is not None
    assert (
        tool_call_result.tool_output_text,
        tool_call_result.execution_status,
        tool_call_result.harness_result_format,
    ) == (
        None,
        S.FINISHED,
        MatchedFormat("image"),
    )


def test_read_pdf_has_no_text_and_an_unchanged_file_is_not_read():
    def read(block: str):
        return _converted(
            _harness_tool_call("Read", {"file_path": "/d.pdf"}, _result(block))
        ).result

    tool_call_result = read("PDF file read: /d.pdf (102.8KB)")
    assert tool_call_result is not None and (
        tool_call_result.tool_output_text,
        tool_call_result.execution_status,
    ) == (
        None,
        S.FINISHED,
    )
    tool_call_result = read(
        "Wasted call — file unchanged since your last Read. Refer to that earlier tool_result instead."
    )
    assert tool_call_result is not None and (
        tool_call_result.tool_output_text,
        tool_call_result.execution_status,
    ) == (
        "",
        S.NOT_RUN,
    )


def test_harbor_json_items_without_a_metadata_block_are_decoded():
    content = '{"type": "text", "text": "File created successfully at: /f.py"}'
    tool_call_result = _converted(
        _harness_tool_call("Write", {"file_path": "/f.py"}, {"content": content})
    ).result
    assert tool_call_result is not None
    assert (
        tool_call_result.execution_status,
        tool_call_result.harness_result_format,
    ) == (
        S.FINISHED,
        MatchedFormat("created"),
    )


def test_failed_file_tool_is_not_run():
    block = "<tool_use_error>File has not been read yet. Read it first before writing to it.</tool_use_error>"
    tool_call_result = _converted(
        _harness_tool_call("Edit", {"file_path": "/f"}, _result(block, is_error=True))
    ).result
    assert (
        tool_call_result is not None and tool_call_result.execution_status is S.NOT_RUN
    )


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
    call = _converted(
        _harness_tool_call(
            "TaskOutput",
            {"task_id": "t1"},
            _result("<retrieval_status>success</retrieval_status>", structured),
        )
    )
    assert call.result is not None
    assert (
        call.result.execution_status,
        call.result.tool_output_text,
        call.result.exit_code,
    ) == (
        S.FINISHED,
        "all good",
        0,
    )
    assert call.result.handles == (ExecutionHandle(ExecutionHandleKind.SUBAGENT, "t1"),)
    assert call.action == PollAction(call.result.handles)


def test_task_stop_is_a_terminate_whose_target_is_killed():
    call = _converted(
        _harness_tool_call(
            "TaskStop",
            {"task_id": "t1"},
            _result(
                '{"message":"Successfully stopped task: t1 (sleep 99)","task_id":"t1",'
                '"task_type":"local_bash","command":"sleep 99"}'
            ),
        )
    )
    assert call.result is not None and call.result.execution_status is S.KILLED
    assert call.action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "t1"),), None, True
    )


def test_web_tools_that_reached_the_server_are_finished_even_on_errors():
    for block, name, http_status in (
        (
            "The server returned HTTP 404 Not Found\n\nThe response body was not retrieved. Try another URL.",
            "http_error_body_not_retrieved",
            404,
        ),
        ("connect ECONNREFUSED 1.2.3.4:443", "connection_error", None),
    ):
        tool_call_result = _converted(
            _harness_tool_call("WebFetch", {"url": "u"}, _result(block))
        ).result
        assert tool_call_result is not None
        assert (
            tool_call_result.execution_status,
            tool_call_result.harness_result_format,
            tool_call_result.tool_output_text,
            tool_call_result.http_status,
        ) == (S.FINISHED, MatchedFormat(name), "", http_status)
    tool_call_result = _converted(
        _harness_tool_call(
            "WebFetch",
            {"url": "u"},
            _result("<tool_use_error>Invalid URL</tool_use_error>", is_error=True),
        )
    ).result
    assert (
        tool_call_result is not None and tool_call_result.execution_status is S.NOT_RUN
    )


def test_other_tools_have_skipped_format():
    tool_call_result = _converted(
        _harness_tool_call("Agent", {"prompt": "p"}, _result("Async agent launched"))
    ).result
    assert tool_call_result is not None
    assert (
        tool_call_result.execution_status,
        tool_call_result.harness_result_format,
        tool_call_result.tool_output_text,
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
    tool_call_result = _converted(
        _harness_tool_call("TaskStop", {"task_id": "t9"}, _result(block))
    ).result
    assert tool_call_result is not None
    assert (
        tool_call_result.execution_status,
        tool_call_result.tool_output_text,
        tool_call_result.output_path,
        tool_call_result.is_truncated,
    ) == (S.KILLED, "", "/tmp/p.txt", True)
    assert tool_call_result.handles == (
        ExecutionHandle(ExecutionHandleKind.COMMAND, "t9"),
    )


def test_web_search_wrapped_as_persisted_output_loses_its_inner_header():
    block = (
        "<persisted-output>\nOutput too large (5.0KB). Full output saved to: /tmp/w.txt\n\nPreview (first 2KB):\n"
        'Web search results for query: "q"\n\nLinks: []\n\nsummary\n</persisted-output>'
    )
    tool_call_result = _converted(
        _harness_tool_call("WebSearch", {"query": "q"}, _result(block))
    ).result
    assert tool_call_result is not None
    assert (
        tool_call_result.harness_result_format,
        tool_call_result.tool_output_text,
        tool_call_result.is_truncated,
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
    tool_call_result = _bash(block)
    assert tool_call_result is not None
    assert tool_call_result.harness_result_format == MatchedFormat("background_v3")
    assert (
        tool_call_result.execution_status,
        tool_call_result.output_path,
        tool_call_result.tool_output_text,
    ) == (
        S.RUNNING,
        "/tmp/b1a2c3d4e.output",
        "",
    )
    assert tool_call_result.handles == (
        ExecutionHandle(ExecutionHandleKind.COMMAND, "b1a2c3d4e"),
    )


def test_web_fetch_takes_the_http_status_from_the_structured_result():
    structured = {
        "bytes": 10,
        "code": 200,
        "codeText": "OK",
        "result": "No response from model",
    }
    tool_call_result = _converted(
        _harness_tool_call(
            "WebFetch", {"url": "u"}, _result("No response from model", structured)
        )
    ).result
    assert tool_call_result is not None
    assert (tool_call_result.tool_output_text, tool_call_result.http_status) == (
        "",
        200,
    )


def test_web_fetch_without_a_model_response_has_no_text_even_with_a_saved_binary():
    saved = "\n\n[Binary content (application/pdf, 1.2 MB) also saved to /tmp/page.pdf]"
    for block in ("No response from model", "No response from model" + saved):
        tool_call_result = _converted(
            _harness_tool_call("WebFetch", {"url": "u"}, _result(block))
        ).result
        assert tool_call_result is not None
        assert (
            tool_call_result.tool_output_text,
            tool_call_result.execution_status,
        ) == ("", S.FINISHED)


def test_content_items_join_their_texts_with_a_blank_line():
    items = [
        {"type": "text", "text": "a\n"},
        {"type": "image", "source": {}},
        {"type": "text", "text": "b"},
    ]
    assert _join_content_items(items) == "a\n\nb"
    assert _join_content_items([{"type": "image"}]) is None
    # Only items that are objects of type text add their text, and a text item without text adds nothing.
    assert _join_content_items([{"type": "document", "text": "x"}]) is None
    assert _join_content_items(["x", {"type": "text", "text": "a"}]) == "a"
    items = [{"type": "text", "text": None}, {"type": "text", "text": "a"}]
    assert _join_content_items(items) == "a"


def test_task_output_without_a_structured_result_has_no_json_object():
    harness_tool_call = _harness_tool_call("TaskOutput", {"task_id": "t1"}, {})
    assert CONVERTER.tool_result_json_of(harness_tool_call, _result("text")) is None


def test_only_a_read_without_text_and_with_an_image_is_an_image_read():
    image_of_bash = _converted_result("Bash", {"command": "x"}, _result([IMAGE]))
    assert image_of_bash.harness_result_format == UnmatchedFormat.UNKNOWN
    read_without_items = _converted_result("Read", {"file_path": "/a"}, _result([]))
    assert read_without_items.harness_result_format == UnmatchedFormat.UNKNOWN
    text_item = {"type": "text", "text": "1\ta\n"}
    read_with_text = _converted_result(
        "Read", {"file_path": "/a"}, _result([IMAGE, text_item])
    )
    assert read_with_text.harness_result_format == MatchedFormat("listing")


def test_harbor_image_item_without_a_metadata_block_is_an_image_read():
    result = {"content": json.dumps(IMAGE)}
    tool_call_result = _converted_result("Read", {"file_path": "/i.png"}, result)
    assert (
        tool_call_result.harness_result_format,
        tool_call_result.execution_status,
    ) == (MatchedFormat("image"), S.FINISHED)


def test_a_result_without_a_text_has_no_text_and_an_unknown_format():
    # A `raw_tool_result` without content, one with blank text, and content that is no string without a metadata block.
    for result in (_result(None), _result("  "), {"content": None}):
        assert _bash_format_and_text(result) == (UnmatchedFormat.UNKNOWN, None), result


def test_raw_tool_result_text_loses_its_edge_whitespace():
    harness_tool_call = _harness_tool_call("Bash", {"command": "x"}, {})
    raw_text = CONVERTER.tool_result_raw_text_of(harness_tool_call, _result("  out\n"))
    assert raw_text == "out"
    assert _bash_format_and_text(_result("  out\n"))[1] == "out"


def test_raw_tool_result_that_is_no_object_falls_back_to_content():
    metadata = {"raw_tool_result": "text"}
    result = {"content": "shown", "extra": {"tool_result_metadata": metadata}}
    assert _bash_format_and_text(result)[1] == "shown"


def test_content_that_is_not_all_harbor_items_stays_text_as_it_is():
    # A plain paragraph after an item, a JSON object of another type and JSON that is no object.
    for content in (
        '{"type": "text", "text": "a"}\n\nplain',
        '{"type": "module"}',
        "42",
    ):
        assert _bash_format_and_text({"content": content})[1] == content


def test_text_exit_code_output_path_handle_and_truncation_stay_beside_the_structured_result():
    exited = _bash("Exit code 2\nboom", {"stdout": "boom", "interrupted": False}, True)
    assert exited is not None and exited.exit_code == 2
    background = _bash(BACKGROUND_NOTICE, {"stdout": "", "interrupted": False})
    assert background is not None
    assert background.output_path == "/tmp/b1.output"
    assert background.handles == (ExecutionHandle(ExecutionHandleKind.COMMAND, "b1"),)
    cut = "head\n... [120 characters truncated] ...\ntail"
    truncated = _bash(
        "Exit code 1\n" + cut, {"stdout": cut, "interrupted": False}, True
    )
    assert truncated is not None and truncated.is_truncated is True


def test_structured_result_without_stdout_gives_empty_text():
    tool_call_result = _bash("shown", {"interrupted": False})
    assert tool_call_result is not None and tool_call_result.tool_output_text == ""


def test_structured_file_content_that_is_no_string_is_ignored():
    structured = {"type": "text", "file": {"filePath": "/a", "content": ["a"]}}
    result = _result("1\ta\n2\tb", structured)
    tool_call_result = _converted_result("Read", {"file_path": "/a"}, result)
    assert tool_call_result.tool_output_text == "a\nb"


def test_web_fetch_code_that_is_no_whole_number_is_no_http_status():
    for code in (True, "200"):
        result = _result("No response from model", {"code": code})
        tool_call_result = _converted_result("WebFetch", {"url": "u"}, result)
        assert tool_call_result.http_status is None, code
