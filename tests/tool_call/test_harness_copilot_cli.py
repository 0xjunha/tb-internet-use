"""Test the conversion of Copilot CLI tool calls by the Copilot CLI converter, with made-up results shaped as in the trajectories."""

import json
from collections import Counter
from typing import Any

import pytest

from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge
from tb_internet_use.tool_call import convert_tool_calls
from tb_internet_use.tool_call._convert_tool_calls import convert_one_tool_call
from tb_internet_use.tool_call.harnesses.copilot_cli import CopilotCliConverter
from tb_internet_use.tool_call.model import (
    ChangeFilesAction,
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
    ToolCall,
    ToolCallAction,
    ToolCallKey,
    ToolCallResult,
    UnknownAction,
    UnmatchedFormat,
    WriteFileAction,
)
from tb_internet_use.tool_call.parse_shell_text import parse_shell_text

S = ExecutionStatus
CONVERTER = CopilotCliConverter()
SHELL_4 = (ExecutionHandle(ExecutionHandleKind.COMMAND, "4"),)
SAVED_HEAD = (
    "Output too large to read at once (20.2 KB). Saved to: /tmp/out.txt\n"
    "Consider using tools like rg (for searching), head/tail (for viewing start/end) to examine portions of the output.\n\n"
    "Preview (first 500 chars):\n"
)
STILL_RUNNING = "<command with shellId: 4 is still running after 30 seconds. The command is still running"


def _result(text: str, *, failed: bool = False) -> dict[str, Any]:
    """Build a result as Harbor writes it, the text and then a JSON line, with `success` in `extra`."""
    json_line = json.dumps({"code": "failure"} if failed else {"detailedContent": text})
    return {"content": text + "\n" + json_line, "extra": {"success": not failed}}


def _failed_shell_result(message: str) -> dict[str, Any]:
    """Build the result of a failed shell call, whose text holds its message twice with a JSON line between."""
    json_line = json.dumps(
        {"detailedContent": message, "structuredContent": {"shellId": "4"}}
    )
    return _result(f"{message}\n{json_line}\n{message}", failed=True)


def _harness_tool_call(
    tool: str, args: dict[str, Any], result: dict[str, Any] | None
) -> HarnessToolCall:
    return HarnessToolCall(
        ToolCallKey("t", "main", 1, 0),
        HarnessTool("copilot-cli", tool),
        "id",
        args,
        result,
    )


def _converted(harness_tool_call: HarnessToolCall) -> ToolCall:
    return convert_one_tool_call(
        harness_tool_call,
        CONVERTER,
        knowledge=ToolCallKnowledge(),
        judgment_rule_use_counts=Counter(),
    )


def _action_of_call_without_result(tool: str, args: dict[str, Any]) -> ToolCallAction:
    """Convert one call of Copilot CLI without a result through `convert_tool_calls`, which picks the converter of the harness, and give its action."""
    [tool_call] = convert_tool_calls(
        [_harness_tool_call(tool, args, None)],
        knowledge=ToolCallKnowledge(),
        judgment_rule_use_counts=Counter(),
    )
    return tool_call.action


def _format(name: str) -> MatchedFormat:
    return MatchedFormat(name)


def _shell_result(
    text: str, status: ExecutionStatus, format_name: str, **fields: Any
) -> ToolCallResult:
    """Give the expected result of a shell call that names the shell `4`."""
    return ToolCallResult(
        text,
        status,
        handles=SHELL_4,
        harness_result_format=_format(format_name),
        **fields,
    )


def _subagent_result(
    text: str, status: ExecutionStatus, format_name: str
) -> ToolCallResult:
    """Give the expected result of a call that names the subagent `0f3c2a`."""
    return ToolCallResult(
        text,
        status,
        handles=(ExecutionHandle(ExecutionHandleKind.SUBAGENT, "0f3c2a"),),
        harness_result_format=_format(format_name),
    )


def _not_run_result(format_name: str) -> ToolCallResult:
    return ToolCallResult("", S.NOT_RUN, harness_result_format=_format(format_name))


def _finished_result(format_name: str, text: str = "") -> ToolCallResult:
    return ToolCallResult(text, S.FINISHED, harness_result_format=_format(format_name))


# One made-up result per declared result format of Copilot CLI, built from the format, and the `ToolCallResult` it converts to.
# (tool, result in the trajectory, expected result)
RESULT_FORMAT_CASES: list[tuple[str, dict[str, Any], ToolCallResult]] = [
    (
        "bash",
        _failed_shell_result(
            "Command not executed. The 'pkill' command is not allowed."
        ),
        _not_run_result("not_executed"),
    ),
    (
        "bash",
        _failed_shell_result("Command blocked: contains dangerous shell expansion."),
        _not_run_result("blocked"),
    ),
    (
        "read_bash",
        _failed_shell_result("Invalid delay: 900. Please supply a valid delay."),
        _not_run_result("invalid_delay"),
    ),
    (
        "stop_bash",
        _failed_shell_result(
            "Unknown shell ID. No command was stopped. List active shell sessions."
        ),
        _not_run_result("unknown_shell"),
    ),
    (
        "view",
        _result(
            "Path /tmp/a.png does not exist. Please provide a valid path.\nPath does not exist",
            failed=True,
        ),
        _not_run_result("missing"),
    ),
    (
        "view",
        _result(
            "Invalid view_range: start line (90) is beyond the end of the file.\nview_range out of bounds",
            failed=True,
        ),
        _not_run_result("invalid_range"),
    ),
    (
        "create",
        _result(
            "Path /app/a.py already exists as a file. Use `view` to check contents then edit it.\nPath already exists",
            failed=True,
        ),
        _not_run_result("exists"),
    ),
    (
        "create",
        _result(
            "Parent directory /app/new does not exist. You need to create it before creating the file.\n"
            "Parent directory does not exist",
            failed=True,
        ),
        _not_run_result("parent_missing"),
    ),
    (
        "create",
        _result('Invalid input: "path": Required\n"path": Required', failed=True),
        _not_run_result("invalid_input"),
    ),
    (
        "create",
        _result(
            "The response reached its output token limit while the arguments for the tool call 'create' were still being written, "
            "so they arrived truncated and have been cleared. This tool call was NOT executed and nothing was changed. Split the work.\n"
            "Tool call arguments truncated by the model output token limit",
            failed=True,
        ),
        _not_run_result("arguments_cut"),
    ),
    (
        "edit",
        _result(
            "No match found: old_str not found in /app/a.py; no changes made; try again\nNo match found",
            failed=True,
        ),
        _not_run_result("not_found"),
    ),
    (
        "edit",
        _result(
            "Failed to execute `edit` on /app/a.py due to error: Error: ENOENT\nUnhandled error: Error: ENOENT",
            failed=True,
        ),
        _not_run_result("failed"),
    ),
    (
        "edit",
        _result('Invalid input: "path": Required\n"path": Required', failed=True),
        _not_run_result("invalid_input"),
    ),
    (
        "read_agent",
        _result(
            'Invalid input: "since_turn": Expected number, received string\n"since_turn": Expected number, received string',
            failed=True,
        ),
        _not_run_result("invalid_input"),
    ),
    (
        "bash",
        _result(SAVED_HEAD + "head\n<shellId: 4 completed with exit code 0>"),
        _shell_result(
            "head",
            S.FINISHED,
            "exited_saved",
            exit_code=0,
            output_path="/tmp/out.txt",
            is_truncated=True,
        ),
    ),
    (
        "bash",
        _result(
            "Shell output was automatically compacted. Compacted output below. Original at /tmp/orig.txt; only use if needed.\n\n"
            "[apt progress: omitted 9 lines]\n<shellId: 4 completed with exit code 0>"
        ),
        _shell_result(
            "[apt progress: omitted 9 lines]",
            S.FINISHED,
            "exited_compacted",
            exit_code=0,
            output_path="/tmp/orig.txt",
            is_truncated=True,
        ),
    ),
    (
        "bash",
        _result("hi\n<shellId: 4 completed with exit code 2>"),
        _shell_result("hi", S.FINISHED, "exited", exit_code=2),
    ),
    (
        "bash",
        _result(
            STILL_RUNNING
            + " but hasn't produced output yet. Use read_bash to continue waiting.>"
        ),
        _shell_result("", S.RUNNING, "running_silent"),
    ),
    (
        "bash",
        _result("step 1\n" + STILL_RUNNING + ". Use stop_bash to stop it.>"),
        _shell_result("step 1", S.RUNNING, "running"),
    ),
    (
        "bash",
        _result("<command started in background with shellId: 4>"),
        _shell_result("", S.RUNNING, "background"),
    ),
    (
        "bash",
        _result("<command started in detached background with shellId: 4>"),
        _shell_result("", S.RUNNING, "background_detached"),
    ),
    (
        "read_bash",
        _result(SAVED_HEAD + "head\n<shellId: 4 completed with exit code 143>"),
        _shell_result(
            "head",
            S.FINISHED,
            "exited_saved",
            exit_code=143,
            output_path="/tmp/out.txt",
            is_truncated=True,
        ),
    ),
    (
        "read_bash",
        _result("\n<shellId: 4 completed with exit code 0>"),
        _shell_result("", S.FINISHED, "exited", exit_code=0),
    ),
    (
        "read_bash",
        _result(
            "Output:\nstarted\n<detached command with shellId: 4 completed with exit code 0>"
        ),
        _shell_result("started", S.FINISHED, "detached_exited", exit_code=0),
    ),
    (
        "read_bash",
        _result("<detached command with shellId: 4 completed with exit code 1>"),
        _shell_result("", S.FINISHED, "detached_exited_silent", exit_code=1),
    ),
    (
        "read_bash",
        _result(
            STILL_RUNNING
            + " but hasn't produced output yet. Use read_bash to continue waiting.>"
        ),
        _shell_result("", S.RUNNING, "running_silent"),
    ),
    (
        "read_bash",
        _result(SAVED_HEAD + "head\n" + STILL_RUNNING + ". Use stop_bash to stop it.>"),
        _shell_result(
            "head",
            S.RUNNING,
            "running_saved",
            output_path="/tmp/out.txt",
            is_truncated=True,
        ),
    ),
    (
        "read_bash",
        _result("step 2\n" + STILL_RUNNING + ". Use stop_bash to stop it.>"),
        _shell_result("step 2", S.RUNNING, "running"),
    ),
    (
        "stop_bash",
        _result("<command with id: 4 stopped>"),
        _shell_result("", S.KILLED, "stopped"),
    ),
    (
        "view",
        _result("Viewed image file successfully."),
        ToolCallResult(None, S.FINISHED, harness_result_format=_format("image")),
    ),
    (
        "view",
        _result(
            "File too large to read at once (30.5 KB). Consider using the grep tool to search within the file."
        ),
        _not_run_result("too_large"),
    ),
    (
        "view",
        _result(
            "\ndiff --git a/app b/app\ncreate file mode 100644\nindex 0000000..0000000\n"
            "--- a/dev/null\n+++ b/app\n@@ -1,0 +1,0 @@\n\n"
        ),
        _finished_result("empty_folder"),
    ),
    (
        "view",
        _result(
            "\ndiff --git a/app/a.txt b/app/a.txt\nindex 0000000..0000000 100644\n"
            "--- a/app/a.txt\n+++ b/app/a.txt\n@@ -1,0 +1,0 @@\n\n"
        ),
        _finished_result("empty_file"),
    ),
    (
        "view",
        _result(
            "line 1\nline 2\n\n[Output truncated. Use view_range=[3, ...] to continue reading. File has at least 9 lines.]"
        ),
        ToolCallResult(
            "line 1\nline 2",
            S.FINISHED,
            is_truncated=True,
            harness_result_format=_format("listing_truncated"),
        ),
    ),
    (
        "view",
        _result("line 1\nline 2\n"),
        _finished_result("listing", "line 1\nline 2\n"),
    ),
    (
        "create",
        _result("Created file /app/a.py with 12 characters"),
        _finished_result("created"),
    ),
    (
        "edit",
        _result("File /app/a.py updated with changes."),
        _finished_result("updated"),
    ),
    (
        "edit",
        _result("No changes made: old_str and new_str are the same"),
        _not_run_result("same_strings"),
    ),
    (
        "apply_patch",
        _result("Added 1 file(s): /app/a.py"),
        _finished_result("added"),
    ),
    (
        "apply_patch",
        _result("Modified 2 file(s): /app/a.py, /app/b.py"),
        _finished_result("modified"),
    ),
    (
        "apply_patch",
        _result("Deleted 1 file(s): /app/a.py"),
        _finished_result("deleted"),
    ),
    (
        "apply_patch",
        _result("Added 1 file(s): /app/a.py\nModified 1 file(s): /app/b.py"),
        _finished_result("added_modified"),
    ),
    (
        "apply_patch",
        _result(
            "Added 1 file(s): /app/a.py\nModified 1 file(s): /app/b.py\nDeleted 1 file(s): /app/c.py"
        ),
        _finished_result("added_modified_deleted"),
    ),
    (
        "task",
        _result(
            "Agent started in background with agent_id: 0f3c2a. You'll be notified when it completes."
        ),
        _subagent_result("", S.RUNNING, "background"),
    ),
    (
        "task",
        _result("## Blocking issues\n\nNone found."),
        _finished_result("finished", "## Blocking issues\n\nNone found."),
    ),
    (
        "read_agent",
        _result(
            "Agent is idle (waiting for messages). agent_id: 0f3c2a, agent_type: rubber-duck, status: idle, description: Review the fix, then report\n\n"
            "[Turn 0]\nNo blocking issues."
        ),
        _subagent_result("No blocking issues.", S.UNKNOWN, "idle"),
    ),
    (
        "read_agent",
        _result(
            "Agent is still running after waiting 180s. agent_id: 0f3c2a, agent_type: general-purpose, status: running, description: Prove a lemma"
        ),
        _subagent_result("", S.RUNNING, "running_after_wait"),
    ),
    (
        "read_agent",
        _result(
            "Agent is still running. agent_id: 0f3c2a, agent_type: general-purpose, status: running, description: Prove a lemma"
        ),
        _subagent_result("", S.RUNNING, "running"),
    ),
]


# A made-up call of each tool with argument rows in the harness tool catalog, or whose action is a poll, and the `ToolCallAction` it converts to without a result.
# Every argument row has a case, and every `PollAction` states its `terminate`.
# (tool, arguments in the trajectory, expected action)
ACTION_CASES: list[tuple[str, dict[str, Any], ToolCallAction]] = [
    (
        "bash",
        {"command": "ls /app", "description": "List app"},
        RunCommandAction(
            "ls /app", parse_shell_text("ls /app", judgment_rule_use_counts=Counter())
        ),
    ),
    (
        "create",
        {"path": "/app/a.txt", "file_text": "hi"},
        WriteFileAction("/app/a.txt", "hi"),
    ),
    (
        "edit",
        {"path": "/app/a.py", "old_str": "x = 1", "new_str": "x = 2"},
        EditFileAction("/app/a.py", "x = 1", "x = 2"),
    ),
    (
        "grep",
        {
            "pattern": "error",
            "paths": ["/app/a.log", "/app/b.log"],
            "path": "/app/a.log",
        },
        SearchFilesAction(("/app/a.log", "/app/b.log")),
    ),
    ("rg", {"pattern": "error", "paths": "/app"}, SearchFilesAction(("/app",))),
    (
        "read_bash",
        {"shellId": "4", "delay": 10},
        PollAction(SHELL_4, terminate=False),
    ),
    ("stop_bash", {"shellId": "4"}, PollAction(SHELL_4, terminate=True)),
    (
        "read_agent",
        {"agent_id": "a1", "wait": True},
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


@pytest.mark.parametrize(("tool", "result", "expected"), RESULT_FORMAT_CASES)
def test_a_result_of_each_declared_format_converts_to_its_fields(
    tool: str, result: dict[str, Any], expected: ToolCallResult
):
    assert _converted(_harness_tool_call(tool, {}, result)).result == expected


def test_a_failed_result_is_held_against_the_formats_of_failed_calls():
    # Unmarked, the text would be the content of a file that `listing` shows.
    text = "Path /tmp/a.png does not exist. Please provide a valid path.\nPath does not exist"
    failed = _converted(_harness_tool_call("view", {}, _result(text, failed=True)))
    shown = _converted(_harness_tool_call("view", {}, _result(text)))
    assert failed.result is not None and shown.result is not None
    assert (failed.result.execution_status, shown.result.execution_status) == (
        S.NOT_RUN,
        S.FINISHED,
    )


def test_a_result_without_the_json_line_matches_no_format():
    result = {"content": "hi\n<shellId: 4 completed with exit code 0>"}
    tool_call_result = _converted(_harness_tool_call("bash", {}, result)).result
    assert tool_call_result is not None
    assert tool_call_result.harness_result_format == UnmatchedFormat.UNKNOWN
    assert tool_call_result.execution_status is S.UNKNOWN


def test_a_shell_poll_takes_the_shell_and_its_kind_from_its_result():
    tool_call = _converted(
        _harness_tool_call(
            "read_bash",
            {"shellId": "4", "delay": 0},
            _result("ok\n<shellId: 4 completed with exit code 0>"),
        )
    )
    assert tool_call.action == PollAction(SHELL_4)


def _view_result(view_type: str) -> dict[str, Any]:
    result = _result("a.txt\nb.txt")
    result["extra"]["toolTelemetry"] = {"properties": {"viewType": view_type}}
    return result


@pytest.mark.parametrize(
    ("view_type", "expected"),
    [
        ("directory", ListFilesAction("/app")),
        ("file", ReadFileAction("/app")),
        ("image", ReadFileAction("/app")),
    ],
)
def test_a_view_lists_a_folder_only_when_its_result_says_the_path_was_one(
    view_type: str, expected: ToolCallAction
):
    tool_call = _converted(
        _harness_tool_call("view", {"path": "/app"}, _view_result(view_type))
    )
    assert tool_call.action == expected


@pytest.mark.parametrize(
    ("patch", "expected"),
    [
        (
            "*** Begin Patch\n*** Add File: /app/a.txt\n+hi\n*** End Patch",
            ChangeFilesAction((WriteFileAction("/app/a.txt", "hi\n"),)),
        ),
        (
            "*** Begin Patch\n*** Add File: /app/a.txt\n+hi\n*** Delete File: /app/b.txt\n*** Update File: /app/c.py\n@@\n-x = 1\n+x = 2\n*** End Patch",
            ChangeFilesAction(
                (
                    WriteFileAction("/app/a.txt", "hi\n"),
                    DeleteFileAction("/app/b.txt"),
                    EditFileAction("/app/c.py", "x = 1", "x = 2"),
                )
            ),
        ),
        ("not a patch", UnknownAction()),
    ],
    ids=["one file change", "several file changes", "no file change"],
)
def test_a_patch_gets_the_file_changes_of_its_patch(
    patch: str, expected: ToolCallAction
):
    assert _action_of_call_without_result("apply_patch", {"value": patch}) == expected
