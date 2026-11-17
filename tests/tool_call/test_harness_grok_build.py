"""Grok Build converter tests, with made-up results shaped as in the trajectories."""

from collections import Counter
from typing import Any

from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge
from tb_internet_use.tool_call._convert_tool_calls import convert_one_tool_call
from tb_internet_use.tool_call.harnesses.grok_build import GrokBuildConverter
from tb_internet_use.tool_call.model import (
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    MatchedFormat,
    PollAction,
    ToolCallKey,
    UnmatchedFormat,
)

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


def _run(content: str):
    return _converted(
        _harness_tool_call("run_terminal_command", {"command": "x"}, content)
    ).result


def test_exit_header_then_output():
    tool_call_result = _run("exit: 0\nok\n")
    assert tool_call_result is not None and (
        tool_call_result.execution_status,
        tool_call_result.exit_code,
        tool_call_result.tool_output_text,
    ) == (S.FINISHED, 0, "ok\n")
    tool_call_result = _run("exit: killed (signal 9)\n")
    assert tool_call_result is not None and (
        tool_call_result.execution_status,
        tool_call_result.tool_output_text,
    ) == (
        S.KILLED,
        "",
    )


def test_truncated_output_names_the_full_output_file():
    tool_call_result = _run(
        "exit: 1 [truncated: showing first/last 8.0 KB of 20.0 KB - full output at: /tmp/full.log]\nhead"
    )
    assert tool_call_result is not None and (
        tool_call_result.output_path,
        tool_call_result.is_truncated,
        tool_call_result.exit_code,
    ) == ("/tmp/full.log", True, 1)


def test_background_start_gives_the_task_handle_and_output_file():
    content = (
        "<task-id>call1</task-id>\n<task-type>bash</task-type>\n<output-file>/tmp/call1.log</output-file>\n"
        '<status>running</status>\n<summary>Command "sleep 99" exceeded the default timeout and was automatically '
        'moved to background. Process is still running.</summary>\nUse get_command_or_subagent_output with task_ids=["call1"] when you need the output.'
    )
    tool_call_result = _run(content)
    assert tool_call_result is not None
    assert (tool_call_result.execution_status, tool_call_result.output_path) == (
        S.RUNNING,
        "/tmp/call1.log",
    )
    assert tool_call_result.handles == (
        ExecutionHandle(ExecutionHandleKind.COMMAND, "call1"),
    )


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


def test_poll_single_task_states():
    done = (
        TASK
        + "Status: completed\nDuration: 1.0s\nExit Code: 0\nOutput File: /t.log\n\n=== Output ===\nhi\n"
    )
    call = _converted(
        _harness_tool_call(
            "get_command_or_subagent_output", {"task_ids": ["call1"]}, done
        )
    )
    assert call.result is not None
    assert (
        call.result.execution_status,
        call.result.exit_code,
        call.result.tool_output_text,
        call.result.output_path,
    ) == (S.FINISHED, 0, "hi\n", "/t.log")
    assert call.action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "call1"),)
    )
    running = (
        TASK
        + "Status: running\nDuration: 1.0s\nOutput File: /t.log\n\n=== Output ===\npartial\n\nWaited the requested 5s; the task is still running."
    )
    tool_call_result = _converted(
        _harness_tool_call(
            "get_command_or_subagent_output", {"task_ids": ["call1"]}, running
        )
    ).result
    assert tool_call_result is not None and (
        tool_call_result.execution_status,
        tool_call_result.tool_output_text,
    ) == (
        S.RUNNING,
        "partial",
    )


def test_unknown_task_id_has_unknown_kind():
    call = _converted(
        _harness_tool_call(
            "kill_command_or_subagent",
            {"task_id": "x9"},
            "Task or subagent x9 not found. It may have finished.",
        )
    )
    assert call.result is not None and call.result.execution_status is S.NOT_RUN
    assert call.action == PollAction(
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


def test_read_file_errors_are_not_run_not_listings():
    for text in (
        "Error: /d is a directory, not a file.",
        "Cannot read binary file: /b",
    ):
        tool_call_result = _converted(
            _harness_tool_call("read_file", {"path": "/f"}, text)
        ).result
        assert (
            tool_call_result is not None
            and tool_call_result.execution_status is S.NOT_RUN
        )
    # A listing starts with a numbered line, so another error is no listing.
    tool_call_result = _converted(
        _harness_tool_call("read_file", {"path": "/f"}, "Error: new")
    ).result
    assert tool_call_result is not None
    assert tool_call_result.harness_result_format == UnmatchedFormat.UNKNOWN


def test_multi_wait_takes_the_shared_state_and_every_task_id():
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


def test_kill_is_a_terminate_whose_target_is_killed():
    call = _converted(
        _harness_tool_call(
            "kill_command_or_subagent",
            {"task_id": "call1"},
            "killed: Task was terminated successfully",
        )
    )
    assert call.result is not None and call.result.execution_status is S.KILLED
    assert isinstance(call.action, PollAction) and call.action.terminate


def test_read_file_listing_loses_line_numbers():
    tool_call_result = _converted(
        _harness_tool_call("read_file", {"path": "/f"}, "1→a\n2→b\n")
    ).result
    assert (
        tool_call_result is not None and tool_call_result.tool_output_text == "a\nb\n"
    )


def test_search_replace_with_the_same_strings_is_not_run():
    tool_call_result = _converted(
        _harness_tool_call(
            "search_replace", {"path": "/f"}, "Old string and new string are the same"
        )
    ).result
    assert (
        tool_call_result is not None and tool_call_result.execution_status is S.NOT_RUN
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


def test_empty_output_placeholder_with_truncation_tail():
    raw_text = (
        TASK
        + "Status: failed\nDuration: 1.0s\nExit Code: 1\nOutput File: /t.log\n\n=== Output ===\n(no output)\n[truncated - use read_file on output_file for full content]"
    )
    tool_call_result = _converted(
        _harness_tool_call(
            "get_command_or_subagent_output", {"task_ids": ["call1"]}, raw_text
        )
    ).result
    assert tool_call_result is not None
    assert (
        tool_call_result.harness_result_format,
        tool_call_result.tool_output_text,
        tool_call_result.is_truncated,
    ) == (
        MatchedFormat("failed_empty_truncated"),
        "",
        True,
    )


def test_failed_task_without_exit_code_was_killed_by_a_signal():
    raw_text = (
        TASK
        + "Status: failed\nDuration: 1.0s\nOutput File: /t.log\n\n=== Output ===\npartial\n"
    )
    tool_call_result = _converted(
        _harness_tool_call(
            "get_command_or_subagent_output", {"task_ids": ["call1"]}, raw_text
        )
    ).result
    assert tool_call_result is not None
    assert (
        tool_call_result.harness_result_format,
        tool_call_result.execution_status,
        tool_call_result.exit_code,
        tool_call_result.tool_output_text,
    ) == (MatchedFormat("failed_signaled"), S.KILLED, None, "partial\n")


def test_read_file_past_the_end_has_no_text():
    tool_call_result = _converted(
        _harness_tool_call(
            "read_file",
            {"path": "/f"},
            "(no lines returned: the requested window is past the end of the file; the file has 12 lines)",
        )
    ).result
    assert tool_call_result is not None and (
        tool_call_result.harness_result_format,
        tool_call_result.execution_status,
        tool_call_result.tool_output_text,
    ) == (MatchedFormat("past_end"), S.FINISHED, "")


def test_truncated_task_output_with_a_byte_count_line_leaves_that_line_out():
    raw_text = (
        TASK
        + "Status: completed\nDuration: 1.0s\nExit Code: 0\nOutput File: /t.log\n\n=== Output ===\nhead\n"
        + "\n[Output truncated - 52000 bytes total. Use read_file on /t.log for full content]"
        + "\n[truncated - use read_file on output_file for full content]"
    )
    tool_call_result = _converted(
        _harness_tool_call(
            "get_command_or_subagent_output", {"task_ids": ["call1"]}, raw_text
        )
    ).result
    assert tool_call_result is not None and (
        tool_call_result.harness_result_format,
        tool_call_result.is_truncated,
        tool_call_result.output_path,
        tool_call_result.tool_output_text,
    ) == (MatchedFormat("done_truncated_bytes"), True, "/t.log", "head\n")
