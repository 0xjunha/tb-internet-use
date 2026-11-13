"""Cursor CLI converter tests, with made-up results shaped as in the trajectories."""

import json
from typing import Any

from tb_internet_use.parse.toolcall.convert import convert_call
from tb_internet_use.parse.toolcall.harnesses.cursor_cli import CursorCliConverter
from tb_internet_use.parse.toolcall.model import (
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    MatchedFormat,
    OtherAction,
    PollAction,
    RawToolCall,
    ToolCallKey,
    UnmatchedFormat,
    WebFetchAction,
)

S = ExecutionStatus
CONVERTER = CursorCliConverter()


def _raw(tool: str, args: dict[str, Any], result: Any) -> RawToolCall:
    return RawToolCall(
        ToolCallKey("t", "main", 1, 0),
        HarnessTool("cursor-cli", tool),
        "id",
        args,
        {"content": json.dumps(result)},
    )


def _shell(result: dict[str, Any]):
    return convert_call(
        _raw("shellToolCall", {"command": "x"}, result), CONVERTER
    ).output


def test_shell_exited_takes_the_interleaved_output():
    output = _shell(
        {
            "isBackground": False,
            "success": {
                "exitCode": 0,
                "stdout": "a",
                "stderr": "b",
                "interleavedOutput": "a\nb",
            },
        }
    )
    assert output is not None
    assert (output.execution_status, output.exit_code, output.tool_output_text) == (
        S.FINISHED,
        0,
        "a\nb",
    )


def test_shell_moved_to_background_is_running_with_the_shell_handle():
    output = _shell(
        {
            "isBackground": False,
            "success": {
                "exitCode": 0,
                "shellId": 3,
                "backgroundReason": "TIMEOUT",
                "interleavedOutput": "partial",
            },
        }
    )
    assert output is not None
    assert (output.execution_status, output.tool_output_text) == (S.RUNNING, "partial")
    assert output.handles == (ExecutionHandle(ExecutionHandleKind.COMMAND, "3"),)
    output = _shell({"isBackground": True, "success": {"shellId": 5, "stdout": "s"}})
    assert output is not None
    assert (output.execution_status, output.tool_output_text, output.handles) == (
        S.RUNNING,
        "s",
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "5"),),
    )


def test_shell_result_of_an_unexpected_shape_is_unknown_format():
    output = _shell({"success": {"interleavedOutput": "x"}})
    assert output is not None
    assert output.harness_result_format == UnmatchedFormat.UNKNOWN


def test_shell_failure_and_saved_output():
    output = _shell(
        {
            "isBackground": False,
            "failure": {"aborted": False, "exitCode": 2, "interleavedOutput": "bad"},
        }
    )
    assert output is not None and (output.execution_status, output.exit_code) == (
        S.FINISHED,
        2,
    )
    output = _shell(
        {
            "isBackground": False,
            "success": {
                "exitCode": 0,
                "interleavedOutput": "big",
                "outputLocation": {"filePath": "/o.txt"},
            },
        }
    )
    assert output is not None and (output.output_path, output.is_truncated) == (
        "/o.txt",
        True,
    )
    output = _shell({"spawnError": {"command": "", "error": "nothing to run"}})
    assert output is not None and output.execution_status is S.NOT_RUN


def test_await_links_to_the_task_and_its_output_file():
    result = {
        "success": {
            "complete": {
                "exitCode": 0,
                "taskId": "9",
                "outputFilePath": "/t.out",
                "regexMatch": "done",
            }
        }
    }
    call = convert_call(_raw("awaitToolCall", {"taskId": "9"}, result), CONVERTER)
    assert call.output is not None
    assert (
        call.output.execution_status,
        call.output.output_path,
        call.output.tool_output_text,
    ) == (S.FINISHED, "/t.out", "done")
    assert call.action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "9"),)
    )
    output = convert_call(
        _raw(
            "awaitToolCall",
            {"taskId": "9"},
            {
                "success": {
                    "stillRunning": {
                        "taskId": "9",
                        "regexMatch": "ready",
                        "outputFilePath": "/t.out",
                    }
                }
            },
        ),
        CONVERTER,
    ).output
    assert output is not None
    assert (
        output.execution_status,
        output.tool_output_text,
        output.handles,
        output.output_path,
    ) == (
        S.RUNNING,
        "ready",
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "9"),),
        "/t.out",
    )


def test_read_content_and_errors():
    output = convert_call(
        _raw(
            "readToolCall",
            {"path": "/f"},
            {"success": {"content": "x", "exceededLimit": False}},
        ),
        CONVERTER,
    ).output
    assert output is not None
    assert (output.execution_status, output.tool_output_text, output.is_truncated) == (
        S.FINISHED,
        "x",
        None,
    )
    output = convert_call(
        _raw("readToolCall", {"path": "/f"}, {"success": {"contentBlobId": "b1"}}),
        CONVERTER,
    ).output
    assert output is not None and output.tool_output_text is None
    output = convert_call(
        _raw(
            "readToolCall",
            {"path": "/f"},
            {"success": {"content": "", "exceededLimit": True}},
        ),
        CONVERTER,
    ).output
    assert output is not None
    assert (output.execution_status, output.tool_output_text, output.is_truncated) == (
        S.NOT_RUN,
        "",
        None,
    )
    output = convert_call(
        _raw(
            "readToolCall",
            {"path": "/f"},
            {"error": {"errorMessage": "File not found"}},
        ),
        CONVERTER,
    ).output
    assert output is not None and output.execution_status is S.NOT_RUN


def test_web_fetch_errors_that_reached_out_are_finished_but_localhost_refusals_are_not_run():
    output = convert_call(
        _raw(
            "webFetchToolCall",
            {"url": "u"},
            {"error": {"error": "Error fetching URL, status code: 404", "url": "u"}},
        ),
        CONVERTER,
    ).output
    assert output is not None and output.execution_status is S.FINISHED
    output = convert_call(
        _raw(
            "webFetchToolCall",
            {"url": "u"},
            {"error": {"error": "Cannot fetch from localhost", "url": "u"}},
        ),
        CONVERTER,
    ).output
    assert output is not None and output.execution_status is S.NOT_RUN


def test_mcp_tool_call_action_follows_the_wrapped_tool():
    result = {
        "success": {"content": [{"type": "text", "text": "ok"}], "isError": False}
    }
    call = convert_call(
        _raw(
            "mcpToolCall",
            {"toolName": "browser_navigate", "args": {"url": "http://x"}},
            result,
        ),
        CONVERTER,
    )
    assert call.action == WebFetchAction(("http://x",))
    assert call.output is not None and call.output.execution_status is S.FINISHED
    call = convert_call(
        _raw("mcpToolCall", {"toolName": "browser_click", "args": {}}, result),
        CONVERTER,
    )
    assert call.action == OtherAction()
    call = convert_call(
        _raw("mcpToolCall", {"toolName": "browser_navigate", "args": {}}, result),
        CONVERTER,
    )
    assert call.action == WebFetchAction(())


def test_web_search_results_are_kept_as_json_text():
    output = convert_call(
        _raw(
            "webSearchToolCall",
            {"query": "q"},
            {"success": {"references": [{"title": "t", "url": "u"}]}},
        ),
        CONVERTER,
    ).output
    assert output is not None
    assert (output.execution_status, output.tool_output_text) == (
        S.FINISHED,
        '[{"title": "t", "url": "u"}]',
    )


def test_await_without_a_task_that_only_timed_out_is_unknown():
    result = {
        "success": {
            "complete": {
                "taskId": "",
                "outputFilePath": "/t.out",
                "outputLength": 0,
                "runtimeMs": "60001",
            }
        }
    }
    output = convert_call(_raw("awaitToolCall", {}, result), CONVERTER).output
    assert output is not None
    assert (output.harness_result_format, output.execution_status, output.handles) == (
        MatchedFormat("no_task"),
        S.UNKNOWN,
        (),
    )


def test_mcp_content_items_give_their_text_only():
    result = {
        "success": {
            "content": [
                {"type": "text", "text": " page one "},
                {"type": "image", "data": "AAAA"},
            ],
            "isError": False,
        }
    }
    output = convert_call(
        _raw(
            "mcpToolCall",
            {"toolName": "browser_navigate", "args": {"url": "http://x"}},
            result,
        ),
        CONVERTER,
    ).output
    assert output is not None and output.tool_output_text == "page one"
    result = {
        "success": {"content": [{"type": "image", "data": "AAAA"}], "isError": False}
    }
    output = convert_call(
        _raw(
            "mcpToolCall",
            {"toolName": "browser_navigate", "args": {"url": "http://x"}},
            result,
        ),
        CONVERTER,
    ).output
    assert output is not None and output.tool_output_text is None


def test_mcp_error_result_has_no_format_yet():
    result = {"success": {"content": [{"type": "text", "text": "x"}], "isError": True}}
    output = convert_call(
        _raw("mcpToolCall", {"toolName": "browser_click", "args": {}}, result),
        CONVERTER,
    ).output
    assert output is not None
    assert output.harness_result_format == UnmatchedFormat.UNKNOWN


def test_mcp_items_nested_one_level_deeper_still_give_their_text():
    result = {
        "success": {
            "content": [{"text": {"text": "- heading [ref=e1]"}}],
            "isError": False,
        }
    }
    output = convert_call(
        _raw(
            "mcpToolCall",
            {"toolName": "browser_navigate", "args": {"url": "http://x"}},
            result,
        ),
        CONVERTER,
    ).output
    assert output is not None and output.tool_output_text == "- heading [ref=e1]"
