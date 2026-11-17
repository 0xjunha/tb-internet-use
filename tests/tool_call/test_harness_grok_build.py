"""Test the conversion of Grok Build tool calls by the Grok Build converter, with made-up results shaped as in the trajectories."""

from collections import Counter
from typing import Any

import pytest

from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge
from tb_internet_use.tool_call import convert_tool_calls
from tb_internet_use.tool_call._convert_tool_calls import convert_one_tool_call
from tb_internet_use.tool_call.harnesses.grok_build import GrokBuildConverter
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
    ToolCallAction,
    ToolCallKey,
    ToolCallResult,
    UnmatchedFormat,
    WriteFileAction,
)
from tb_internet_use.tool_call.parse_shell_text import parse_shell_text

S = ExecutionStatus
CONVERTER = GrokBuildConverter()
TASK = "=== Task call1 ===\nCommand: sleep 5\n"


def _harness_tool_call(
    tool: str, args: dict[str, Any], content: str
) -> HarnessToolCall:
    return HarnessToolCall(
        ToolCallKey("t", "main", 1, 0),
        HarnessTool("grok-build", tool),
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
    """Convert one call of Grok Build without a result through `convert_tool_calls`, which picks the converter of the harness, and give its action."""
    [tool_call] = convert_tool_calls(
        [
            HarnessToolCall(
                ToolCallKey("t", "main", 1, 0),
                HarnessTool("grok-build", tool),
                "id",
                args,
                None,
            )
        ],
        knowledge=ToolCallKnowledge(),
        judgment_rule_use_counts=Counter(),
    )
    return tool_call.action


def _run(content: str):
    return _converted(
        _harness_tool_call("run_terminal_command", {"command": "x"}, content)
    ).result


_TRUNCATED_HEAD = (
    " [truncated: showing first/last 8.0 KB of 20.0 KB - full output at: /tmp/full.log]"
)
_BACKGROUND = (
    "<task-id>call1</task-id>\n<task-type>bash</task-type>\n<output-file>/tmp/call1.log</output-file>\n"
    '<status>running</status>\n<summary>Command "sleep 99" exceeded the default timeout and was automatically '
    "moved to background. Process is still running.</summary>\n"
)
_TAIL = "\n[truncated - use read_file on output_file for full content]"
_OUTPUT = "Output File: /t.log\n\n=== Output ===\n"
_DONE = TASK + "Status: completed\nDuration: 1.0s\nExit Code: 0\n" + _OUTPUT
_FAILED = TASK + "Status: failed\nDuration: 1.0s\nExit Code: 1\n" + _OUTPUT
_FAILED_SIGNALED = TASK + "Status: failed\nDuration: 1.0s\n" + _OUTPUT
_RUNNING = TASK + "Status: running\nDuration: 1.0s\n" + _OUTPUT
_STILL_RUNNING = "partial\n\nWaited the requested 5s; the task is still running."
_CALL_1 = (ExecutionHandle(ExecutionHandleKind.COMMAND, "call1"),)
_TASK_X9 = (ExecutionHandle(ExecutionHandleKind.UNKNOWN, "x9"),)


def _format(name: str) -> MatchedFormat:
    return MatchedFormat(name)


def _task_result(
    text: str, status: ExecutionStatus, format_name: str, **fields: Any
) -> ToolCallResult:
    """Give the expected result of a poll on the task `call1`, whose output file is `/t.log`."""
    return ToolCallResult(
        text,
        status,
        handles=_CALL_1,
        output_path="/t.log",
        harness_result_format=_format(format_name),
        **fields,
    )


def _not_run_result(format_name: str) -> ToolCallResult:
    return ToolCallResult("", S.NOT_RUN, harness_result_format=_format(format_name))


# One made-up result per declared result format of Grok Build, built from the format, and the `ToolCallResult` it converts to.
# (tool, result text in the trajectory, expected result)
RESULT_FORMAT_CASES: list[tuple[str, str, ToolCallResult]] = [
    (
        "run_terminal_command",
        "exit: 1" + _TRUNCATED_HEAD + "\nhead",
        ToolCallResult(
            "head",
            S.FINISHED,
            1,
            output_path="/tmp/full.log",
            is_truncated=True,
            harness_result_format=_format("exited_truncated"),
        ),
    ),
    (
        "run_terminal_command",
        "exit: 0\nok\n",
        ToolCallResult("ok\n", S.FINISHED, 0, harness_result_format=_format("exited")),
    ),
    (
        "run_terminal_command",
        "exit: killed (signal 9)" + _TRUNCATED_HEAD + "\nhead",
        ToolCallResult(
            "head",
            S.KILLED,
            output_path="/tmp/full.log",
            is_truncated=True,
            harness_result_format=_format("killed_truncated"),
        ),
    ),
    (
        "run_terminal_command",
        "exit: killed (signal 9)\n",
        ToolCallResult("", S.KILLED, harness_result_format=_format("killed")),
    ),
    (
        "run_terminal_command",
        _BACKGROUND
        + 'Use get_command_or_subagent_output with task_ids=["call1"] when you need the output.',
        ToolCallResult(
            "",
            S.RUNNING,
            handles=_CALL_1,
            output_path="/tmp/call1.log",
            harness_result_format=_format("background"),
        ),
    ),
    (
        "run_terminal_command",
        _BACKGROUND
        + 'Use get_command_or_subagent_output tool with task_ids=["call1"] to retrieve the output.',
        ToolCallResult(
            "",
            S.RUNNING,
            handles=_CALL_1,
            output_path="/tmp/call1.log",
            harness_result_format=_format("background_v2"),
        ),
    ),
    (
        "run_terminal_command",
        "Tool `run_terminal_command` failed: command is empty",
        _not_run_result("rejected"),
    ),
    (
        "run_terminal_command",
        "Failed to parse arguments for tool `run_terminal_command`: missing field",
        _not_run_result("rejected_arguments"),
    ),
    (
        "get_command_or_subagent_output",
        _DONE + "(no output)",
        _task_result("", S.FINISHED, "done_empty", exit_code=0),
    ),
    (
        "get_command_or_subagent_output",
        _DONE + "(no output)" + _TAIL,
        _task_result(
            "", S.FINISHED, "done_empty_truncated", exit_code=0, is_truncated=True
        ),
    ),
    (
        "get_command_or_subagent_output",
        _DONE
        + "head\n\n[Output truncated - 52000 bytes total. Use read_file on /t.log for full content]"
        + _TAIL,
        _task_result(
            "head\n", S.FINISHED, "done_truncated_bytes", exit_code=0, is_truncated=True
        ),
    ),
    (
        "get_command_or_subagent_output",
        _DONE + "head" + _TAIL,
        _task_result(
            "head", S.FINISHED, "done_truncated", exit_code=0, is_truncated=True
        ),
    ),
    (
        "get_command_or_subagent_output",
        _DONE + "hi\n",
        _task_result("hi\n", S.FINISHED, "done", exit_code=0),
    ),
    (
        "get_command_or_subagent_output",
        _FAILED + "(no output)" + _TAIL,
        _task_result(
            "", S.FINISHED, "failed_empty_truncated", exit_code=1, is_truncated=True
        ),
    ),
    (
        "get_command_or_subagent_output",
        _FAILED + "err" + _TAIL,
        _task_result(
            "err", S.FINISHED, "failed_truncated", exit_code=1, is_truncated=True
        ),
    ),
    (
        "get_command_or_subagent_output",
        _FAILED + "err\n",
        _task_result("err\n", S.FINISHED, "failed", exit_code=1),
    ),
    (
        "get_command_or_subagent_output",
        _FAILED_SIGNALED + "(no output)",
        _task_result("", S.KILLED, "failed_signaled_empty"),
    ),
    (
        "get_command_or_subagent_output",
        _FAILED_SIGNALED + "partial\n",
        _task_result("partial\n", S.KILLED, "failed_signaled"),
    ),
    (
        "get_command_or_subagent_output",
        _RUNNING + _STILL_RUNNING + _TAIL,
        _task_result("partial", S.RUNNING, "running_truncated", is_truncated=True),
    ),
    (
        "get_command_or_subagent_output",
        _RUNNING + _STILL_RUNNING,
        _task_result("partial", S.RUNNING, "running"),
    ),
    (
        "get_command_or_subagent_output",
        TASK + "Status: cancelled\nDuration: 1.0s\n" + _OUTPUT + "(no output)",
        _task_result("", S.KILLED, "cancelled_empty"),
    ),
    (
        "get_command_or_subagent_output",
        TASK + "Status: timed_out\nDuration: 1.0s\n" + _OUTPUT + "partial",
        _task_result("partial", S.TIMED_OUT, "timed_out"),
    ),
    (
        "get_command_or_subagent_output",
        "=== Multi-wait (wait_all) ===\n--- Task a1 [completed] ---\nx\n--- Task b2 [completed] ---\ny",
        ToolCallResult(
            "--- Task a1 [completed] ---\nx\n--- Task b2 [completed] ---\ny",
            S.FINISHED,
            handles=(
                ExecutionHandle(ExecutionHandleKind.COMMAND, "a1"),
                ExecutionHandle(ExecutionHandleKind.COMMAND, "b2"),
            ),
            harness_result_format=_format("multi_wait"),
        ),
    ),
    (
        "get_command_or_subagent_output",
        "Tool `get_command_or_subagent_output` failed: task_ids is empty",
        _not_run_result("rejected"),
    ),
    (
        "get_command_or_subagent_output",
        "Task x9 not found. Known task IDs: a1",
        ToolCallResult(
            "",
            S.NOT_RUN,
            handles=_TASK_X9,
            harness_result_format=_format("unknown_task"),
        ),
    ),
    (
        "kill_command_or_subagent",
        "killed: Task was terminated successfully",
        ToolCallResult("", S.KILLED, harness_result_format=_format("killed")),
    ),
    (
        "kill_command_or_subagent",
        "already_exited: Task had already completed",
        ToolCallResult("", S.FINISHED, harness_result_format=_format("already_exited")),
    ),
    (
        "kill_command_or_subagent",
        "Task or subagent x9 not found. It may have finished.",
        ToolCallResult(
            "",
            S.NOT_RUN,
            handles=_TASK_X9,
            harness_result_format=_format("unknown_task"),
        ),
    ),
    (
        "monitor",
        "Monitor started (task m1, timeout 60s).\nYou will be notified of each new line.",
        ToolCallResult(
            "",
            S.RUNNING,
            handles=(ExecutionHandle(ExecutionHandleKind.COMMAND, "m1"),),
            harness_result_format=_format("started"),
        ),
    ),
    (
        "read_file",
        "Read image file: /i.png",
        ToolCallResult(None, S.FINISHED, harness_result_format=_format("image")),
    ),
    (
        "read_file",
        "Read PDF file: /d.pdf (2 pages rendered, 2 total)",
        ToolCallResult(None, S.FINISHED, harness_result_format=_format("pdf")),
    ),
    (
        "read_file",
        "File is empty.",
        ToolCallResult("", S.FINISHED, harness_result_format=_format("empty")),
    ),
    (
        "read_file",
        "(no lines returned: the requested window is past the end of the file; the file has 12 lines)",
        ToolCallResult("", S.FINISHED, harness_result_format=_format("past_end")),
    ),
    ("read_file", "Error: /m does not exist.", _not_run_result("missing")),
    (
        "read_file",
        "Error: /d is a directory, not a file.",
        _not_run_result("directory"),
    ),
    ("read_file", "Cannot read binary file: /b", _not_run_result("binary")),
    (
        "read_file",
        "File content (30000 tokens) exceeds maximum allowed tokens (25000). Read it in parts.",
        _not_run_result("too_large"),
    ),
    (
        "read_file",
        "The requested line range (1-9000) contains too many tokens.",
        _not_run_result("range_too_large"),
    ),
    (
        "read_file",
        "1→a\n2→b\n",
        ToolCallResult("a\nb\n", S.FINISHED, harness_result_format=_format("listing")),
    ),
    (
        "write",
        "Wrote file successfully to /f",
        ToolCallResult("", S.FINISHED, harness_result_format=_format("written")),
    ),
    (
        "write",
        "The file /f has been created.",
        ToolCallResult("", S.FINISHED, harness_result_format=_format("created")),
    ),
    (
        "search_replace",
        "The file /f has been updated successfully.",
        ToolCallResult("", S.FINISHED, harness_result_format=_format("updated")),
    ),
    (
        "search_replace",
        "The file /f has been created successfully.",
        ToolCallResult("", S.FINISHED, harness_result_format=_format("created")),
    ),
    (
        "search_replace",
        "The file /f has been updated. All occurrences were successfully replaced.",
        ToolCallResult("", S.FINISHED, harness_result_format=_format("replaced_all")),
    ),
    (
        "search_replace",
        "The string to replace was not found in the file, check the whitespace.",
        _not_run_result("not_found"),
    ),
    (
        "search_replace",
        "The string to replace was found multiple times in the file. Add more context.",
        _not_run_result("not_unique"),
    ),
    (
        "search_replace",
        "Old string and new string are the same",
        _not_run_result("same_strings"),
    ),
    ("search_replace", "Error: /m does not exist.", _not_run_result("missing")),
    (
        "search_replace",
        "Failed to parse arguments for tool `search_replace`: missing field",
        _not_run_result("rejected_arguments"),
    ),
]


# A made-up call of each tool with argument rows in the harness tool catalog, or whose action is a poll, and the `ToolCallAction` it converts to without a result.
# Every argument row has a case, and every `PollAction` states its `terminate`.
# (tool, arguments in the trajectory, expected action)
ACTION_CASES: list[tuple[str, dict[str, Any], ToolCallAction]] = [
    (
        "run_terminal_command",
        {"command": "ls /app"},
        RunCommandAction(
            "ls /app", parse_shell_text("ls /app", judgment_rule_use_counts=Counter())
        ),
    ),
    (
        "monitor",
        {"command": "tail -f /app/run.log"},
        RunCommandAction(
            "tail -f /app/run.log",
            parse_shell_text(
                "tail -f /app/run.log", judgment_rule_use_counts=Counter()
            ),
        ),
    ),
    (
        "read_file",
        {"target_file": "/app/a.py", "offset": 10, "limit": 20},
        ReadFileAction("/app/a.py", 10, 20),
    ),
    (
        "write",
        {"file_path": "/app/a.txt", "content": "hi"},
        WriteFileAction("/app/a.txt", "hi"),
    ),
    (
        "search_replace",
        {"file_path": "/app/a.py", "old_string": "x = 1", "new_string": "x = 2"},
        EditFileAction("/app/a.py", "x = 1", "x = 2"),
    ),
    ("grep", {"pattern": "error", "path": "/app"}, SearchFilesAction(("/app",))),
    ("list_dir", {"target_directory": "/app"}, ListFilesAction("/app")),
    # The rows give no handle kind, so the kind stays unknown until a result names it.
    (
        "get_command_or_subagent_output",
        {"task_ids": ["t1", "t2"]},
        PollAction(
            (
                ExecutionHandle(ExecutionHandleKind.UNKNOWN, "t1"),
                ExecutionHandle(ExecutionHandleKind.UNKNOWN, "t2"),
            ),
            terminate=False,
        ),
    ),
    (
        "kill_command_or_subagent",
        {"task_id": "t1"},
        PollAction(
            (ExecutionHandle(ExecutionHandleKind.UNKNOWN, "t1"),), terminate=True
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


def test_notification_inside_a_result_is_cut_out_of_text():
    content = 'exit: 0\nok\n\n<system-reminder>\nBackground task "call9" completed (exit code: 0).\n</system-reminder>'
    tool_call_result = _run(content)
    assert tool_call_result is not None and (
        tool_call_result.tool_output_text,
        tool_call_result.harness_result_format,
    ) == (
        "ok",
        MatchedFormat("exited"),
    )


def test_a_poll_of_one_task_takes_the_task_and_its_kind_from_its_result():
    done = (
        TASK
        + "Status: completed\nDuration: 1.0s\nExit Code: 0\nOutput File: /t.log\n\n=== Output ===\nhi\n"
    )
    tool_call = _converted(
        _harness_tool_call(
            "get_command_or_subagent_output", {"task_ids": ["call1"]}, done
        )
    )
    assert tool_call.action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "call1"),)
    )


def test_unknown_task_id_has_unknown_kind():
    tool_call = _converted(
        _harness_tool_call(
            "kill_command_or_subagent",
            {"task_id": "x9"},
            "Task or subagent x9 not found. It may have finished.",
        )
    )
    assert (
        tool_call.result is not None and tool_call.result.execution_status is S.NOT_RUN
    )
    assert tool_call.action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.UNKNOWN, "x9"),), None, True
    )
    tool_call_result = _converted(
        _harness_tool_call(
            "get_command_or_subagent_output",
            {"task_ids": ["x9"]},
            "Task x9 not found. Known task IDs: a1",
        )
    ).result
    assert tool_call_result is not None
    assert tool_call_result.handles == (
        ExecutionHandle(ExecutionHandleKind.UNKNOWN, "x9"),
    )


def test_a_read_file_error_of_no_declared_format_is_no_listing():
    # A listing starts with a numbered line, so an error without a format of its own is no listing.
    tool_call_result = _converted(
        _harness_tool_call("read_file", {"path": "/f"}, "Error: new")
    ).result
    assert tool_call_result is not None
    assert tool_call_result.harness_result_format == UnmatchedFormat.UNKNOWN


def test_a_wait_on_several_tasks_takes_their_shared_state_and_every_task_id():
    raw_text = "=== Multi-wait (wait_all) ===\n--- Task a1 [completed] ---\nx\n--- Task b2 [completed] ---\ny\n2/2 tasks completed (wait_all)"
    tool_call_result = _converted(
        _harness_tool_call(
            "get_command_or_subagent_output", {"task_ids": ["a1", "b2"]}, raw_text
        )
    ).result
    assert tool_call_result is not None
    assert tool_call_result.execution_status is S.FINISHED
    assert [h.id for h in tool_call_result.handles] == ["a1", "b2"]
    failed = raw_text.replace("[completed]", "[failed]")
    tool_call_result = _converted(
        _harness_tool_call(
            "get_command_or_subagent_output", {"task_ids": ["a1", "b2"]}, failed
        )
    ).result
    assert (
        tool_call_result is not None and tool_call_result.execution_status is S.FINISHED
    )
    mixed = raw_text.replace("Task b2 [completed]", "Task b2 [running]")
    tool_call_result = _converted(
        _harness_tool_call(
            "get_command_or_subagent_output", {"task_ids": ["a1", "b2"]}, mixed
        )
    ).result
    assert (
        tool_call_result is not None and tool_call_result.execution_status is S.UNKNOWN
    )
    running = raw_text.replace("[completed]", "[running]")
    tool_call_result = _converted(
        _harness_tool_call(
            "get_command_or_subagent_output", {"task_ids": ["a1", "b2"]}, running
        )
    ).result
    assert (
        tool_call_result is not None and tool_call_result.execution_status is S.RUNNING
    )


def test_notification_at_the_very_end_is_cut_whatever_its_spacing():
    notice = '<system-reminder>\nBackground task "call9" completed (exit code: 0).</system-reminder>'
    for content in ("exit: 0\nok\n" + notice, "exit: 0\nok" + notice):
        tool_call_result = _run(content)
        assert tool_call_result is not None and (
            tool_call_result.tool_output_text,
            tool_call_result.harness_result_format,
        ) == (
            "ok",
            MatchedFormat("exited"),
        )
