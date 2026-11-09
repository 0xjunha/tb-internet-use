"""Codex converter tests, with made-up results shaped as in the trajectories."""

from typing import Any

from tb_internet_use.toolcall.convert import convert_call
from tb_internet_use.toolcall.harnesses.codex import CodexConverter
from tb_internet_use.toolcall.model import (
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    MatchedFormat,
    PollAction,
    RawToolCall,
    ToolCallKey,
    UnknownAction,
    UnmatchedFormat,
    WebFetchAction,
    WebFindAction,
    WebSearchAction,
)

S = ExecutionStatus
CONVERTER = CodexConverter()
HEAD = "Chunk ID: ab12\nWall time: 0.5 seconds\n"


def _raw(tool: str, args: dict[str, Any], content: str | None) -> RawToolCall:
    return RawToolCall(
        ToolCallKey("t", "main", 1, 0),
        HarnessTool("codex", tool),
        "id",
        args,
        {"content": content},
    )


def test_exec_command_exited():
    content = (
        HEAD + "Process exited with code 1\nOriginal token count: 3\nOutput:\nerr\n"
    )
    output = convert_call(_raw("exec_command", {"cmd": "x"}, content), CONVERTER).output
    assert output is not None
    assert (output.execution_status, output.exit_code, output.tool_output_text) == (
        S.FINISHED,
        1,
        "err\n",
    )


def test_exec_command_running_gives_the_session_handle():
    content = (
        HEAD + "Process running with session ID 7\nOriginal token count: 0\nOutput:\n"
    )
    output = convert_call(_raw("exec_command", {"cmd": "x"}, content), CONVERTER).output
    assert output is not None
    assert output.execution_status is S.RUNNING
    assert output.handles == (ExecutionHandle(ExecutionHandleKind.COMMAND, "7"),)


def test_truncation_warning_after_output_header_sets_is_truncated():
    content = (
        HEAD + "Process exited with code 0\nOriginal token count: 99\nOutput:\n"
        "Warning: truncated output (original token count: 99)\nTotal output lines: 500\n\nbody"
    )
    output = convert_call(_raw("exec_command", {"cmd": "x"}, content), CONVERTER).output
    assert output is not None
    assert (output.is_truncated, output.tool_output_text) == (True, "body")


def test_rejected_commands_are_not_run():
    output = convert_call(
        _raw("exec_command", {"cmd": "x"}, "exec_command failed: nope"), CONVERTER
    ).output
    assert output is not None and output.execution_status is S.NOT_RUN
    output = convert_call(
        _raw(
            "write_stdin",
            {"session_id": 7, "chars": "y"},
            "write_stdin failed: Unknown process id 7",
        ),
        CONVERTER,
    ).output
    assert output is not None and output.execution_status is S.NOT_RUN


def test_poll_handles_from_arguments_get_the_tool_kind():
    exited = HEAD + "Process exited with code 0\nOriginal token count: 0\nOutput:\n"
    call = convert_call(
        _raw("write_stdin", {"session_id": 7, "chars": ""}, exited), CONVERTER
    )
    assert call.output is not None and call.output.handles == ()
    assert call.action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "7"),)
    )
    call = convert_call(_raw("wait", {"cell_id": "3"}, "Script completed"), CONVERTER)
    assert call.action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.SCRIPT, "3"),)
    )


def test_ctrl_c_through_write_stdin_is_a_terminate_and_exit_130_is_killed():
    exited = HEAD + "Process exited with code 130\nOriginal token count: 0\nOutput:\n"
    call = convert_call(
        _raw("write_stdin", {"session_id": 7, "chars": "\x03"}, exited), CONVERTER
    )
    assert call.output is not None
    assert (call.output.execution_status, call.output.exit_code) == (S.KILLED, None)
    assert call.action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "7"),), "\x03", True
    )
    other = exited.replace("code 130", "code 0")
    call = convert_call(
        _raw("write_stdin", {"session_id": 7, "chars": "\x03"}, other), CONVERTER
    )
    assert call.output is not None
    assert (call.output.execution_status, call.output.exit_code) == (S.FINISHED, 0)
    call = convert_call(
        _raw("write_stdin", {"session_id": 7, "chars": "y"}, exited), CONVERTER
    )
    assert call.output is not None
    assert (call.output.execution_status, call.output.exit_code) == (S.FINISHED, 130)
    assert isinstance(call.action, PollAction) and not call.action.terminate


def test_web_search_call_with_content_keeps_it_as_text():
    output = convert_call(
        _raw("web_search_call", {"action_type": "search"}, "some text"), CONVERTER
    ).output
    assert output is not None
    assert (output.harness_result_format, output.tool_output_text) == (
        UnmatchedFormat.SKIPPED,
        "some text",
    )


def test_web_search_keeps_every_query():
    args = {"action_type": "search", "query": "a", "queries": ["a", "b", "a"]}
    call = convert_call(_raw("web_search_call", args, None), CONVERTER)
    assert call.action == WebSearchAction(("a", "b"))
    call = convert_call(
        _raw("web_search_call", {"action_type": "search"}, None), CONVERTER
    )
    assert call.action == WebSearchAction(())


def test_web_search_call_without_content_is_finished_and_typed_by_action_type():
    call = convert_call(
        _raw("web_search_call", {"action_type": "search", "query": "q"}, None),
        CONVERTER,
    )
    assert call.output is not None
    assert (call.output.execution_status, call.output.tool_output_text) == (
        S.FINISHED,
        None,
    )
    assert call.action == WebSearchAction(("q",))
    assert convert_call(
        _raw("web_search_call", {"action_type": "open_page", "url": "u"}, None),
        CONVERTER,
    ).action == WebFetchAction(("u",))
    assert convert_call(
        _raw("web_search_call", {"action_type": "find_in_page", "url": "u"}, None),
        CONVERTER,
    ).action == WebFindAction(("u",))
    assert (
        convert_call(
            _raw("web_search_call", {"action_type": ""}, None), CONVERTER
        ).action
        == UnknownAction()
    )


def test_exec_is_left_unconverted_for_now():
    call = convert_call(
        _raw("exec", {"input": "tools.exec_command('ls')"}, "Script completed"),
        CONVERTER,
    )
    assert call.action == UnknownAction()
    assert (
        call.output is not None
        and call.output.harness_result_format == UnmatchedFormat.SKIPPED
    )


def test_exec_command_truncation_warning_without_a_line_count_is_cut_from_the_text():
    content = (
        HEAD
        + "Process exited with code 0\nOriginal token count: 9000\nOutput:\n"
        + "Warning: truncated output (original token count: 9000)\nbody\n"
    )
    output = convert_call(_raw("exec_command", {"cmd": "x"}, content), CONVERTER).output
    assert output is not None
    assert (
        output.harness_result_format,
        output.is_truncated,
        output.tool_output_text,
    ) == (MatchedFormat("exited_truncated_no_line_count"), True, "body\n")
