"""Cursor CLI converter tests, with made-up results shaped as in the trajectories."""

import json
from collections import Counter
from typing import Any

from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge
from tb_internet_use.tool_call._convert_tool_calls import convert_one_tool_call
from tb_internet_use.tool_call.harnesses.cursor_cli import CursorCliConverter
from tb_internet_use.tool_call.model import (
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    MatchedFormat,
    PollAction,
    ToolCallKey,
    UnknownAction,
    UnmatchedFormat,
    WebFetchAction,
)

S = ExecutionStatus
CONVERTER = CursorCliConverter()


def _harness_tool_call(tool: str, args: dict[str, Any], result: Any) -> HarnessToolCall:
    return HarnessToolCall(
        ToolCallKey("t", "main", 1, 0),
        HarnessTool("cursor-cli", tool),
        "id",
        args,
        {"content": json.dumps(result)},
    )


def _converted(harness_tool_call: HarnessToolCall):
    return convert_one_tool_call(
        harness_tool_call,
        CONVERTER,
        knowledge=ToolCallKnowledge(),
        judgment_rule_use_counts=Counter(),
    )


def _shell(result: dict[str, Any]):
    return _converted(
        _harness_tool_call("shellToolCall", {"command": "x"}, result)
    ).result


def test_shell_exited_takes_the_interleaved_output():
    tool_call_result = _shell(
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
    assert tool_call_result is not None
    assert (
        tool_call_result.execution_status,
        tool_call_result.exit_code,
        tool_call_result.tool_output_text,
    ) == (
        S.FINISHED,
        0,
        "a\nb",
    )


def test_shell_moved_to_background_is_running_with_the_shell_handle():
    tool_call_result = _shell(
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
    assert tool_call_result is not None
    assert (tool_call_result.execution_status, tool_call_result.tool_output_text) == (
        S.RUNNING,
        "partial",
    )
    assert tool_call_result.handles == (
        ExecutionHandle(ExecutionHandleKind.COMMAND, "3"),
    )
    tool_call_result = _shell(
        {"isBackground": True, "success": {"shellId": 5, "stdout": "s"}}
    )
    assert tool_call_result is not None
    assert (
        tool_call_result.execution_status,
        tool_call_result.tool_output_text,
        tool_call_result.handles,
    ) == (
        S.RUNNING,
        "s",
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "5"),),
    )


def test_shell_result_of_an_unexpected_shape_is_unknown_format():
    tool_call_result = _shell({"success": {"interleavedOutput": "x"}})
    assert tool_call_result is not None
    assert tool_call_result.harness_result_format == UnmatchedFormat.UNKNOWN


def test_shell_failure_and_saved_output():
    tool_call_result = _shell(
        {
            "isBackground": False,
            "failure": {"aborted": False, "exitCode": 2, "interleavedOutput": "bad"},
        }
    )
    assert tool_call_result is not None and (
        tool_call_result.execution_status,
        tool_call_result.exit_code,
    ) == (
        S.FINISHED,
        2,
    )
    tool_call_result = _shell(
        {
            "isBackground": False,
            "success": {
                "exitCode": 0,
                "interleavedOutput": "big",
                "outputLocation": {"filePath": "/o.txt"},
            },
        }
    )
    assert tool_call_result is not None and (
        tool_call_result.output_path,
        tool_call_result.is_truncated,
    ) == (
        "/o.txt",
        True,
    )
    tool_call_result = _shell(
        {"spawnError": {"command": "", "error": "nothing to run"}}
    )
    assert (
        tool_call_result is not None and tool_call_result.execution_status is S.NOT_RUN
    )


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
    call = _converted(_harness_tool_call("awaitToolCall", {"taskId": "9"}, result))
    assert call.result is not None
    assert (
        call.result.execution_status,
        call.result.output_path,
        call.result.tool_output_text,
    ) == (S.FINISHED, "/t.out", "done")
    assert call.action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "9"),)
    )
    tool_call_result = _converted(
        _harness_tool_call(
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
        )
    ).result
    assert tool_call_result is not None
    assert (
        tool_call_result.execution_status,
        tool_call_result.tool_output_text,
        tool_call_result.handles,
        tool_call_result.output_path,
    ) == (
        S.RUNNING,
        "ready",
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "9"),),
        "/t.out",
    )


def test_read_content_and_errors():
    tool_call_result = _converted(
        _harness_tool_call(
            "readToolCall",
            {"path": "/f"},
            {"success": {"content": "x", "exceededLimit": False}},
        )
    ).result
    assert tool_call_result is not None
    assert (
        tool_call_result.execution_status,
        tool_call_result.tool_output_text,
        tool_call_result.is_truncated,
    ) == (
        S.FINISHED,
        "x",
        None,
    )
    tool_call_result = _converted(
        _harness_tool_call(
            "readToolCall", {"path": "/f"}, {"success": {"contentBlobId": "b1"}}
        )
    ).result
    assert tool_call_result is not None and tool_call_result.tool_output_text is None
    tool_call_result = _converted(
        _harness_tool_call(
            "readToolCall",
            {"path": "/f"},
            {"success": {"content": "", "exceededLimit": True}},
        )
    ).result
    assert tool_call_result is not None
    assert (
        tool_call_result.execution_status,
        tool_call_result.tool_output_text,
        tool_call_result.is_truncated,
    ) == (
        S.NOT_RUN,
        "",
        None,
    )
    tool_call_result = _converted(
        _harness_tool_call(
            "readToolCall",
            {"path": "/f"},
            {"error": {"errorMessage": "File not found"}},
        )
    ).result
    assert (
        tool_call_result is not None and tool_call_result.execution_status is S.NOT_RUN
    )


def test_web_fetch_errors_that_reached_out_are_finished_but_localhost_refusals_are_not_run():
    tool_call_result = _converted(
        _harness_tool_call(
            "webFetchToolCall",
            {"url": "u"},
            {"error": {"error": "Error fetching URL, status code: 404", "url": "u"}},
        )
    ).result
    assert (
        tool_call_result is not None and tool_call_result.execution_status is S.FINISHED
    )
    tool_call_result = _converted(
        _harness_tool_call(
            "webFetchToolCall",
            {"url": "u"},
            {"error": {"error": "Cannot fetch from localhost", "url": "u"}},
        )
    ).result
    assert (
        tool_call_result is not None and tool_call_result.execution_status is S.NOT_RUN
    )


def test_mcp_tool_call_action_follows_the_wrapped_tool():
    result = {
        "success": {"content": [{"type": "text", "text": "ok"}], "isError": False}
    }
    call = _converted(
        _harness_tool_call(
            "mcpToolCall",
            {"toolName": "browser_navigate", "args": {"url": "http://x"}},
            result,
        )
    )
    assert call.action == WebFetchAction(("http://x",))
    assert call.result is not None and call.result.execution_status is S.FINISHED
    call = _converted(
        _harness_tool_call(
            "mcpToolCall", {"toolName": "browser_click", "args": {}}, result
        )
    )
    # A wrapped tool that the converter does not know is unknown, not a default.
    assert call.action == UnknownAction()
    call = _converted(
        _harness_tool_call(
            "mcpToolCall", {"toolName": "browser_navigate", "args": {}}, result
        )
    )
    assert call.action == WebFetchAction(())
    # A navigation without `args` names no URL either.
    call = _converted(
        _harness_tool_call("mcpToolCall", {"toolName": "browser_navigate"}, result)
    )
    assert call.action == WebFetchAction(())


def test_web_search_results_are_kept_as_json_text():
    tool_call_result = _converted(
        _harness_tool_call(
            "webSearchToolCall",
            {"query": "q"},
            {"success": {"references": [{"title": "t", "url": "u"}]}},
        )
    ).result
    assert tool_call_result is not None
    assert (tool_call_result.execution_status, tool_call_result.tool_output_text) == (
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
    tool_call_result = _converted(
        _harness_tool_call("awaitToolCall", {}, result)
    ).result
    assert tool_call_result is not None
    assert (
        tool_call_result.harness_result_format,
        tool_call_result.execution_status,
        tool_call_result.handles,
    ) == (
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
    tool_call_result = _converted(
        _harness_tool_call(
            "mcpToolCall",
            {"toolName": "browser_navigate", "args": {"url": "http://x"}},
            result,
        )
    ).result
    assert (
        tool_call_result is not None and tool_call_result.tool_output_text == "page one"
    )
    result = {
        "success": {"content": [{"type": "image", "data": "AAAA"}], "isError": False}
    }
    tool_call_result = _converted(
        _harness_tool_call(
            "mcpToolCall",
            {"toolName": "browser_navigate", "args": {"url": "http://x"}},
            result,
        )
    ).result
    assert tool_call_result is not None and tool_call_result.tool_output_text is None


def test_mcp_error_result_has_no_format_yet():
    result = {"success": {"content": [{"type": "text", "text": "x"}], "isError": True}}
    tool_call_result = _converted(
        _harness_tool_call(
            "mcpToolCall", {"toolName": "browser_click", "args": {}}, result
        )
    ).result
    assert tool_call_result is not None
    assert tool_call_result.harness_result_format == UnmatchedFormat.UNKNOWN


def test_mcp_items_nested_one_level_deeper_still_give_their_text():
    result = {
        "success": {
            "content": [{"text": {"text": "- heading [ref=e1]"}}],
            "isError": False,
        }
    }
    tool_call_result = _converted(
        _harness_tool_call(
            "mcpToolCall",
            {"toolName": "browser_navigate", "args": {"url": "http://x"}},
            result,
        )
    ).result
    assert (
        tool_call_result is not None
        and tool_call_result.tool_output_text == "- heading [ref=e1]"
    )
