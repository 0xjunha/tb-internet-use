"""Test the conversion of Cursor CLI tool calls by the Cursor CLI converter, with made-up results shaped as in the trajectories."""

import json
from collections import Counter
from typing import Any

import pytest

from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge
from tb_internet_use.tool_call import convert_tool_calls
from tb_internet_use.tool_call._convert_tool_calls import convert_one_tool_call
from tb_internet_use.tool_call.harnesses.cursor_cli import CursorCliConverter
from tb_internet_use.tool_call.model import (
    DeleteFileAction,
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
    UnknownAction,
    UnmatchedFormat,
    WebFetchAction,
    WebSearchAction,
)
from tb_internet_use.tool_call.parse_shell_text import parse_shell_text

S = ExecutionStatus
CONVERTER = CursorCliConverter()


def _format(name: str) -> MatchedFormat:
    return MatchedFormat(name)


def _command_handles(handle_id: str) -> tuple[ExecutionHandle, ...]:
    return (ExecutionHandle(ExecutionHandleKind.COMMAND, handle_id),)


# One made-up result per declared result format of Cursor CLI, built from the format, and the `ToolCallResult` it converts to.
# (tool, result object of the JSON text in the trajectory, expected result)
RESULT_FORMAT_CASES: list[tuple[str, dict[str, Any], ToolCallResult]] = [
    (
        "shellToolCall",
        {"spawnError": {"command": "", "error": "nothing to run"}},
        ToolCallResult("", S.NOT_RUN, harness_result_format=_format("not_spawned")),
    ),
    (
        "shellToolCall",
        {
            "isBackground": False,
            "success": {
                "exitCode": 0,
                "shellId": 3,
                "backgroundReason": "TIMEOUT",
                "interleavedOutput": "partial",
            },
        },
        ToolCallResult(
            "partial",
            S.RUNNING,
            handles=_command_handles("3"),
            harness_result_format=_format("background"),
        ),
    ),
    (
        "shellToolCall",
        {"isBackground": True, "success": {"exitCode": 0, "shellId": 5, "stdout": "s"}},
        ToolCallResult(
            "s",
            S.RUNNING,
            handles=_command_handles("5"),
            harness_result_format=_format("background_requested"),
        ),
    ),
    (
        "shellToolCall",
        {
            "success": {
                "exitCode": 0,
                "interleavedOutput": "big",
                "outputLocation": {"filePath": "/o.txt"},
            }
        },
        ToolCallResult(
            "big",
            S.FINISHED,
            0,
            output_path="/o.txt",
            harness_result_format=_format("exited_saved"),
        ),
    ),
    (
        "shellToolCall",
        {
            "isBackground": False,
            "success": {
                "exitCode": 0,
                "stdout": "a",
                "stderr": "b",
                "interleavedOutput": "a\nb",
            },
        },
        ToolCallResult("a\nb", S.FINISHED, 0, harness_result_format=_format("exited")),
    ),
    (
        "shellToolCall",
        {
            "failure": {
                "exitCode": 1,
                "interleavedOutput": "bad",
                "outputLocation": {"filePath": "/e.txt"},
            }
        },
        ToolCallResult(
            "bad",
            S.FINISHED,
            1,
            output_path="/e.txt",
            harness_result_format=_format("failed_saved"),
        ),
    ),
    (
        "shellToolCall",
        {
            "isBackground": False,
            "failure": {"aborted": False, "exitCode": 2, "interleavedOutput": "bad"},
        },
        ToolCallResult("bad", S.FINISHED, 2, harness_result_format=_format("failed")),
    ),
    (
        "awaitToolCall",
        {
            "success": {
                "complete": {
                    "taskId": "",
                    "outputFilePath": "/t.out",
                    "outputLength": 0,
                }
            }
        },
        ToolCallResult("", S.UNKNOWN, harness_result_format=_format("no_task")),
    ),
    # Without a match the poll holds no text of the output, which stays in the output file.
    (
        "awaitToolCall",
        {
            "success": {
                "complete": {
                    "exitCode": 0,
                    "taskId": "9",
                    "outputFilePath": "/t.out",
                }
            }
        },
        ToolCallResult(
            None,
            S.FINISHED,
            0,
            handles=_command_handles("9"),
            output_path="/t.out",
            harness_result_format=_format("complete_without_match"),
        ),
    ),
    (
        "awaitToolCall",
        {"success": {"stillRunning": {"taskId": "9", "outputFilePath": "/t.out"}}},
        ToolCallResult(
            None,
            S.RUNNING,
            handles=_command_handles("9"),
            output_path="/t.out",
            harness_result_format=_format("still_running_without_match"),
        ),
    ),
    (
        "awaitToolCall",
        {
            "success": {
                "complete": {
                    "exitCode": 0,
                    "taskId": "9",
                    "outputFilePath": "/t.out",
                    "regexMatch": "done",
                }
            }
        },
        ToolCallResult(
            "done",
            S.FINISHED,
            0,
            handles=_command_handles("9"),
            output_path="/t.out",
            harness_result_format=_format("complete"),
        ),
    ),
    (
        "awaitToolCall",
        {
            "success": {
                "stillRunning": {
                    "taskId": "9",
                    "regexMatch": "ready",
                    "outputFilePath": "/t.out",
                }
            }
        },
        ToolCallResult(
            "ready",
            S.RUNNING,
            handles=_command_handles("9"),
            output_path="/t.out",
            harness_result_format=_format("still_running"),
        ),
    ),
    (
        "readToolCall",
        {"success": {"content": "x", "exceededLimit": False}},
        ToolCallResult("x", S.FINISHED, harness_result_format=_format("content")),
    ),
    (
        "readToolCall",
        {"success": {"content": "", "exceededLimit": True}},
        ToolCallResult("", S.NOT_RUN, harness_result_format=_format("too_large")),
    ),
    (
        "readToolCall",
        {"success": {"contentBlobId": "b1"}},
        ToolCallResult(None, S.FINISHED, harness_result_format=_format("blob")),
    ),
    (
        "readToolCall",
        {"error": {"errorMessage": "File not found"}},
        ToolCallResult("", S.NOT_RUN, harness_result_format=_format("error")),
    ),
    (
        "editToolCall",
        {"success": {"path": "/f", "linesAdded": 1}},
        ToolCallResult("", S.FINISHED, harness_result_format=_format("edited")),
    ),
    (
        "editToolCall",
        {"error": {"errorMessage": "String not found"}},
        ToolCallResult("", S.NOT_RUN, harness_result_format=_format("error")),
    ),
    (
        "webFetchToolCall",
        {"success": {"markdown": "# Page", "outputLocation": {"filePath": "/p.md"}}},
        ToolCallResult(
            "# Page",
            S.FINISHED,
            output_path="/p.md",
            harness_result_format=_format("page_saved"),
        ),
    ),
    (
        "webFetchToolCall",
        {"success": {"markdown": "# Page"}},
        ToolCallResult("# Page", S.FINISHED, harness_result_format=_format("page")),
    ),
    (
        "webFetchToolCall",
        {"error": {"error": "Cannot fetch from localhost", "url": "u"}},
        ToolCallResult(
            "", S.NOT_RUN, harness_result_format=_format("refused_localhost")
        ),
    ),
    # A fetch that got an error status from the server ended on its own.
    (
        "webFetchToolCall",
        {"error": {"error": "Error fetching URL, status code: 404", "url": "u"}},
        ToolCallResult("", S.FINISHED, harness_result_format=_format("error")),
    ),
    (
        "webSearchToolCall",
        {"success": {"references": [{"title": "t", "url": "u"}]}},
        ToolCallResult(
            '[{"title": "t", "url": "u"}]',
            S.FINISHED,
            harness_result_format=_format("results"),
        ),
    ),
    (
        "mcpToolCall",
        {"success": {"content": [{"type": "text", "text": "ok"}], "isError": False}},
        ToolCallResult("ok", S.FINISHED, harness_result_format=_format("content")),
    ),
]


# A made-up call of each tool with argument rows in the harness tool catalog, or whose action is a poll, and the `ToolCallAction` it converts to without a result.
# Every argument row has a case, and every `PollAction` states its `terminate`.
# (tool, arguments in the trajectory, expected action)
ACTION_CASES: list[tuple[str, dict[str, Any], ToolCallAction]] = [
    (
        "shellToolCall",
        {"command": "ls /app"},
        RunCommandAction(
            "ls /app", parse_shell_text("ls /app", judgment_rule_use_counts=Counter())
        ),
    ),
    (
        "readToolCall",
        {"path": "/app/a.py", "offset": 10, "limit": 20},
        ReadFileAction("/app/a.py", 10, 20),
    ),
    (
        "editToolCall",
        {"path": "/app/a.py", "streamContent": "x = 2\n"},
        EditFileAction("/app/a.py", None, "x = 2\n"),
    ),
    ("deleteToolCall", {"path": "/app/a.txt"}, DeleteFileAction("/app/a.txt")),
    (
        "grepToolCall",
        {"pattern": "error", "path": "/app/run.log"},
        SearchFilesAction(("/app/run.log",)),
    ),
    (
        "globToolCall",
        {"globPattern": "*.log", "targetDirectory": "/app"},
        ListFilesAction("/app"),
    ),
    (
        "webFetchToolCall",
        {"url": "https://example.org/a"},
        WebFetchAction(("https://example.org/a",)),
    ),
    (
        "webSearchToolCall",
        {"searchTerm": "pytest fixtures"},
        WebSearchAction(("pytest fixtures",)),
    ),
    ("taskToolCall", {"prompt": "find the bug"}, StartSubagentAction()),
    (
        "awaitToolCall",
        {"taskId": "3"},
        PollAction(
            (ExecutionHandle(ExecutionHandleKind.COMMAND, "3"),), terminate=False
        ),
    ),
    # Only the Cursor CLI converter reads the page that a wrapped `browser_navigate` opens.
    (
        "mcpToolCall",
        {"toolName": "browser_navigate", "args": {"url": "https://example.org/b"}},
        WebFetchAction(("https://example.org/b",)),
    ),
]


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


def _action_of_call_without_result(tool: str, args: dict[str, Any]) -> ToolCallAction:
    """Convert one call of Cursor CLI without a result through `convert_tool_calls`, which picks the converter of the harness, and give its action."""
    [tool_call] = convert_tool_calls(
        [
            HarnessToolCall(
                ToolCallKey("t", "main", 1, 0),
                HarnessTool("cursor-cli", tool),
                "id",
                args,
                None,
            )
        ],
        knowledge=ToolCallKnowledge(),
        judgment_rule_use_counts=Counter(),
    )
    return tool_call.action


def _shell(result: dict[str, Any]):
    return _converted(
        _harness_tool_call("shellToolCall", {"command": "x"}, result)
    ).result


def test_shell_result_of_an_unexpected_shape_is_unknown_format():
    tool_call_result = _shell({"success": {"interleavedOutput": "x"}})
    assert tool_call_result is not None
    assert tool_call_result.harness_result_format == UnmatchedFormat.UNKNOWN


@pytest.mark.parametrize(("tool", "args", "expected"), ACTION_CASES)
def test_a_call_of_each_tool_converts_to_the_action_of_its_arguments(
    tool: str, args: dict[str, Any], expected: ToolCallAction
):
    assert _action_of_call_without_result(tool, args) == expected


@pytest.mark.parametrize(("tool", "result", "expected"), RESULT_FORMAT_CASES)
def test_a_result_of_each_declared_format_converts_to_its_fields(
    tool: str, result: dict[str, Any], expected: ToolCallResult
):
    assert _converted(_harness_tool_call(tool, {}, result)).result == expected


def test_await_polls_the_task_its_result_names():
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
    tool_call = _converted(_harness_tool_call("awaitToolCall", {"taskId": "9"}, result))
    assert tool_call.action == PollAction(_command_handles("9"))


def test_mcp_tool_call_action_follows_the_wrapped_tool():
    result = {
        "success": {"content": [{"type": "text", "text": "ok"}], "isError": False}
    }
    tool_call = _converted(
        _harness_tool_call(
            "mcpToolCall", {"toolName": "browser_click", "args": {}}, result
        )
    )
    # A wrapped tool that the converter does not know is unknown, not a default.
    assert tool_call.action == UnknownAction()
    tool_call = _converted(
        _harness_tool_call(
            "mcpToolCall", {"toolName": "browser_navigate", "args": {}}, result
        )
    )
    assert tool_call.action == WebFetchAction(())
    # A navigation without `args` names no URL either.
    tool_call = _converted(
        _harness_tool_call("mcpToolCall", {"toolName": "browser_navigate"}, result)
    )
    assert tool_call.action == WebFetchAction(())


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
