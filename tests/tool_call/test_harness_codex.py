"""Test the conversion of Codex tool calls by the Codex converter, with made-up results shaped as in the trajectories."""

from collections import Counter
from dataclasses import replace
from typing import Any

import pytest

from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge
from tb_internet_use.tool_call import convert_tool_calls
from tb_internet_use.tool_call._convert_tool_calls import convert_one_tool_call
from tb_internet_use.tool_call.harnesses.codex import CodexConverter, _has_printed_media
from tb_internet_use.tool_call.model import (
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    MatchedFormat,
    OtherAction,
    PollAction,
    ReadFileAction,
    RunCommandAction,
    RunToolScriptAction,
    ToolCallAction,
    ToolCallKey,
    ToolCallResult,
    UnknownAction,
    UnmatchedFormat,
    WebFetchAction,
    WebFindAction,
    WebSearchAction,
    WriteFileAction,
)
from tb_internet_use.tool_call.parse_shell_text import parse_shell_text

S = ExecutionStatus
CONVERTER = CodexConverter()
HEAD = "Chunk ID: ab12\nWall time: 0.5 seconds\n"


def _harness_tool_call(
    tool: str, args: dict[str, Any], content: str | None
) -> HarnessToolCall:
    """Give a call whose result entry holds `content`, or no `content` key for None, as Codex writes a web search."""
    return HarnessToolCall(
        ToolCallKey("t", "main", 1, 0),
        HarnessTool("codex", tool),
        "id",
        args,
        {} if content is None else {"content": content},
    )


def _converted(harness_tool_call: HarnessToolCall):
    return convert_one_tool_call(
        harness_tool_call,
        CONVERTER,
        knowledge=ToolCallKnowledge(),
        judgment_rule_use_counts=Counter(),
    )


def _action_of_call_without_result(tool: str, args: dict[str, Any]) -> ToolCallAction:
    """Convert one call of Codex without a result through `convert_tool_calls`, which picks the converter of the harness, and give its action."""
    [tool_call] = convert_tool_calls(
        [
            HarnessToolCall(
                ToolCallKey("t", "main", 1, 0),
                HarnessTool("codex", tool),
                "id",
                args,
                None,
            )
        ],
        knowledge=ToolCallKnowledge(),
        judgment_rule_use_counts=Counter(),
    )
    return tool_call.action


def _command_result(args: dict[str, Any], content: str | None) -> ToolCallResult:
    tool_call_result = _converted(
        _harness_tool_call("exec_command", args, content)
    ).result
    assert tool_call_result is not None
    return tool_call_result


SCRIPT_HEAD = "\nWall time 0.1 seconds\nOutput:\n"
WARNING = "Warning: truncated output (original token count: 9)\n"
LINES = "Total output lines: 3\n\n"


def _script_result(state: str, *printed: dict[str, str]) -> str:
    """Give an exec or wait result as Codex writes it, a Python list of content items."""
    return repr([{"type": "input_text", "text": state + SCRIPT_HEAD}, *printed])


def _printed(text: str) -> dict[str, str]:
    return {"type": "input_text", "text": text}


def _script_tool_call_result(tool: str, content: str):
    return _converted(_harness_tool_call(tool, {"input": "x"}, content)).result


def _completed_exec_result(*printed: dict[str, Any]) -> ToolCallResult:
    """Convert an `exec` call whose completed script printed the given content items."""
    content = _script_result("Script completed", *printed)
    tool_call_result = _script_tool_call_result("exec", content)
    assert tool_call_result is not None
    return tool_call_result


def _script_action(code: str | None):
    args = {} if code is None else {"input": code}
    return _converted(
        _harness_tool_call("exec", args, "Script completed" + SCRIPT_HEAD)
    ).action


_EXITED = HEAD + "Process exited with code {}\nOriginal token count: 3\nOutput:\n"
_RUNNING = (
    HEAD + "Process running with session ID 7\nOriginal token count: 3\nOutput:\n"
)
_SESSION_7 = (ExecutionHandle(ExecutionHandleKind.COMMAND, "7"),)


def _format(name: str) -> MatchedFormat:
    return MatchedFormat(name)


def _cell(cell_id: str) -> tuple[ExecutionHandle, ...]:
    return (ExecutionHandle(ExecutionHandleKind.SCRIPT, cell_id),)


def _shell_cases(tool: str) -> list[tuple[str, str | None, ToolCallResult]]:
    """List the cases of the formats that `exec_command` and `write_stdin` share."""
    return [
        (
            tool,
            _EXITED.format(0) + WARNING + LINES + "body",
            ToolCallResult(
                "body",
                S.FINISHED,
                0,
                is_truncated=True,
                harness_result_format=_format("exited_truncated"),
            ),
        ),
        (
            tool,
            _EXITED.format(1) + "err\n",
            ToolCallResult(
                "err\n", S.FINISHED, 1, harness_result_format=_format("exited")
            ),
        ),
        (
            tool,
            _RUNNING + WARNING + LINES + "x",
            ToolCallResult(
                "x",
                S.RUNNING,
                handles=_SESSION_7,
                is_truncated=True,
                harness_result_format=_format("running_truncated"),
            ),
        ),
        (
            tool,
            _RUNNING,
            ToolCallResult(
                "",
                S.RUNNING,
                handles=_SESSION_7,
                harness_result_format=_format("running"),
            ),
        ),
    ]


def _script_cases(tool: str) -> list[tuple[str, str | None, ToolCallResult]]:
    """List the cases of the formats that `exec` and `wait` share."""
    return [
        (
            tool,
            _script_result("Script completed", _printed(WARNING + LINES + "x")),
            ToolCallResult(
                "x",
                S.FINISHED,
                is_truncated=True,
                harness_result_format=_format("completed_truncated"),
            ),
        ),
        (
            tool,
            _script_result("Script completed", _printed("a"), _printed("b")),
            ToolCallResult(
                "a\nb", S.FINISHED, harness_result_format=_format("completed")
            ),
        ),
        # A failed script ran until its error, which stays in the tool output.
        (
            tool,
            _script_result("Script failed", _printed("Script error:\nboom")),
            ToolCallResult(
                "Script error:\nboom",
                S.FINISHED,
                harness_result_format=_format("failed"),
            ),
        ),
        (
            tool,
            "Script running with cell ID c1" + SCRIPT_HEAD + WARNING + LINES + "x",
            ToolCallResult(
                "x",
                S.RUNNING,
                handles=_cell("c1"),
                is_truncated=True,
                harness_result_format=_format("running_truncated"),
            ),
        ),
        (
            tool,
            "Script running with cell ID g1:2" + SCRIPT_HEAD,
            ToolCallResult(
                "",
                S.RUNNING,
                handles=_cell("g1:2"),
                harness_result_format=_format("running"),
            ),
        ),
    ]


# One made-up result per declared result format of Codex, built from the format, and the `ToolCallResult` it converts to.
# (tool, content of the result entry in the trajectory or None for an entry without it, expected result)
RESULT_FORMAT_CASES: list[tuple[str, str | None, ToolCallResult]] = [
    *_shell_cases("exec_command"),
    (
        "exec_command",
        _EXITED.format(0)
        + "Warning: truncated output (original token count: 9000)\nbody\n",
        ToolCallResult(
            "body\n",
            S.FINISHED,
            0,
            is_truncated=True,
            harness_result_format=_format("exited_truncated_no_line_count"),
        ),
    ),
    (
        "exec_command",
        "Wall time: 0.5 seconds\nOutput:\nExit code: 0\nWall time: 0.5 seconds\nOutput:\nhi",
        ToolCallResult("hi", S.FINISHED, 0, harness_result_format=_format("v2_exited")),
    ),
    (
        "exec_command",
        "exec_command failed: nope",
        ToolCallResult("", S.NOT_RUN, harness_result_format=_format("rejected")),
    ),
    (
        "exec_command",
        "exec_command failed for `ls /x`: boom",
        ToolCallResult(
            "", S.NOT_RUN, harness_result_format=_format("rejected_command")
        ),
    ),
    (
        "exec_command",
        "apply_patch verification failed: no such file",
        ToolCallResult("", S.NOT_RUN, harness_result_format=_format("rejected_patch")),
    ),
    *_shell_cases("write_stdin"),
    (
        "write_stdin",
        "write_stdin failed: Unknown process id 7",
        ToolCallResult("", S.NOT_RUN, harness_result_format=_format("rejected_stdin")),
    ),
    *_script_cases("exec"),
    (
        "exec",
        "Script completed" + SCRIPT_HEAD + WARNING + "... 5 bytes omitted ...\n\nx",
        ToolCallResult(
            "x",
            S.FINISHED,
            is_truncated=True,
            harness_result_format=_format("completed_truncated_bytes"),
        ),
    ),
    (
        "exec",
        _script_result(
            "Script failed", _printed("Script error:\nSyntaxError: Unexpected token")
        ),
        ToolCallResult("", S.NOT_RUN, harness_result_format=_format("failed_syntax")),
    ),
    (
        "exec",
        "code-mode host exited with status signal: 9 (SIGKILL)",
        ToolCallResult("", S.KILLED, harness_result_format=_format("host_killed")),
    ),
    (
        "exec",
        "code-mode host exited with status exit status: 1",
        ToolCallResult("", S.UNKNOWN, harness_result_format=_format("host_exited")),
    ),
    *_script_cases("wait"),
    (
        "wait",
        "Script failed" + SCRIPT_HEAD + "Script error:\nexec cell 9 not found",
        ToolCallResult("", S.NOT_RUN, harness_result_format=_format("cell_not_found")),
    ),
    (
        "wait",
        "Script terminated" + SCRIPT_HEAD + "bye",
        ToolCallResult("bye", S.KILLED, harness_result_format=_format("terminated")),
    ),
    (
        "wait",
        "failed to parse function arguments: invalid type",
        ToolCallResult(
            "", S.NOT_RUN, harness_result_format=_format("rejected_arguments")
        ),
    ),
    (
        "web_search_call",
        None,
        ToolCallResult(None, S.FINISHED, harness_result_format=_format("no_content")),
    ),
]


# A made-up call of each tool with argument rows in the harness tool catalog, or whose action is a poll, and the `ToolCallAction` it converts to without a result.
# Every argument row has a case, and every `PollAction` states its `terminate`.
# (tool, arguments in the trajectory, expected action)
ACTION_CASES: list[tuple[str, dict[str, Any], ToolCallAction]] = [
    (
        "exec_command",
        {"cmd": "ls /app", "yield_time_ms": 1000},
        RunCommandAction(
            "ls /app", parse_shell_text("ls /app", judgment_rule_use_counts=Counter())
        ),
    ),
    ("view_image", {"path": "/app/plot.png"}, ReadFileAction("/app/plot.png")),
    (
        "write_stdin",
        {"session_id": 7, "chars": "y\n"},
        PollAction(
            (ExecutionHandle(ExecutionHandleKind.COMMAND, "7"),), "y\n", terminate=False
        ),
    ),
    (
        "wait",
        {"cell_id": "c1"},
        PollAction(
            (ExecutionHandle(ExecutionHandleKind.SCRIPT, "c1"),), terminate=False
        ),
    ),
    (
        "wait",
        {"cell_id": "c1", "terminate": True},
        PollAction(
            (ExecutionHandle(ExecutionHandleKind.SCRIPT, "c1"),), terminate=True
        ),
    ),
    ("wait_agent", {"timeout_ms": 1000}, PollAction(terminate=False)),
    (
        "interrupt_agent",
        {"target": "a1"},
        PollAction(
            (ExecutionHandle(ExecutionHandleKind.SUBAGENT, "a1"),), terminate=True
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
    tool: str, content: str | None, expected: ToolCallResult
):
    assert _converted(_harness_tool_call(tool, {}, content)).result == expected


def test_poll_handles_from_arguments_get_the_tool_kind():
    exited = HEAD + "Process exited with code 0\nOriginal token count: 0\nOutput:\n"
    tool_call = _converted(
        _harness_tool_call("write_stdin", {"session_id": 7, "chars": ""}, exited)
    )
    assert tool_call.result is not None and tool_call.result.handles == ()
    assert tool_call.action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "7"),)
    )
    tool_call = _converted(
        _harness_tool_call("wait", {"cell_id": "3"}, "Script completed")
    )
    assert tool_call.action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.SCRIPT, "3"),)
    )


def test_ctrl_c_through_write_stdin_is_a_terminate_and_exit_130_is_killed():
    exited = HEAD + "Process exited with code 130\nOriginal token count: 0\nOutput:\n"
    tool_call = _converted(
        _harness_tool_call("write_stdin", {"session_id": 7, "chars": "\x03"}, exited)
    )
    assert tool_call.result is not None
    assert (tool_call.result.execution_status, tool_call.result.exit_code) == (
        S.KILLED,
        None,
    )
    assert tool_call.action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "7"),), "\x03", True
    )
    other = exited.replace("code 130", "code 0")
    tool_call = _converted(
        _harness_tool_call("write_stdin", {"session_id": 7, "chars": "\x03"}, other)
    )
    assert tool_call.result is not None
    assert (tool_call.result.execution_status, tool_call.result.exit_code) == (
        S.FINISHED,
        0,
    )
    tool_call = _converted(
        _harness_tool_call("write_stdin", {"session_id": 7, "chars": "y"}, exited)
    )
    assert tool_call.result is not None
    assert (tool_call.result.execution_status, tool_call.result.exit_code) == (
        S.FINISHED,
        130,
    )
    assert isinstance(tool_call.action, PollAction) and not tool_call.action.terminate


def test_web_search_call_with_content_has_an_unknown_format_and_keeps_it_as_text():
    tool_call_result = _converted(
        _harness_tool_call("web_search_call", {"action_type": "search"}, "some text")
    ).result
    assert tool_call_result is not None
    assert (
        tool_call_result.harness_result_format,
        tool_call_result.execution_status,
        tool_call_result.tool_output_text,
    ) == (
        UnmatchedFormat.UNKNOWN,
        S.UNKNOWN,
        "some text",
    )


def test_web_search_keeps_every_query():
    args = {"action_type": "search", "query": "a", "queries": ["a", "b", "a"]}
    tool_call = _converted(_harness_tool_call("web_search_call", args, None))
    assert tool_call.action == WebSearchAction(("a", "b"))
    tool_call = _converted(
        _harness_tool_call("web_search_call", {"action_type": "search"}, None)
    )
    assert tool_call.action == WebSearchAction(())


def test_web_search_call_without_content_is_finished_and_typed_by_action_type():
    tool_call = _converted(
        _harness_tool_call(
            "web_search_call", {"action_type": "search", "query": "q"}, None
        )
    )
    assert tool_call.result is not None
    assert (
        tool_call.result.execution_status,
        tool_call.result.tool_output_text,
        tool_call.result.harness_result_format,
    ) == (S.FINISHED, None, MatchedFormat("no_content"))
    assert tool_call.action == WebSearchAction(("q",))
    assert _converted(
        _harness_tool_call(
            "web_search_call", {"action_type": "open_page", "url": "u"}, None
        )
    ).action == WebFetchAction(("u",))
    assert _converted(
        _harness_tool_call(
            "web_search_call", {"action_type": "find_in_page", "url": "u"}, None
        )
    ).action == WebFindAction(("u",))
    assert (
        _converted(
            _harness_tool_call("web_search_call", {"action_type": ""}, None)
        ).action
        == UnknownAction()
    )


def test_finished_script_names_the_sessions_it_left_running():
    started = (
        '{"chunk_id": "a1", "wall_time_seconds": 1.0, "session_id": 7, "output": ""}'
    )
    polled = '{"chunk_id": "a2", "wall_time_seconds": 1.0, "session_id": 7}'
    no_session = '{"chunk_id": "a3", "wall_time_seconds": 1.0, "session_id": null}'
    ended = (
        '{"chunk_id": "b2", "wall_time_seconds": 0.1, "exit_code": 0, "output": "ok"}'
    )
    printed = f"{started}\n{polled}\n{no_session}\n{ended}"
    content = _script_result("Script completed", _printed(printed))
    tool_call_result = _script_tool_call_result("exec", content)
    assert tool_call_result is not None
    assert (tool_call_result.execution_status, tool_call_result.handles) == (
        S.FINISHED,
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "7"),),
    )


def test_wait_polls_its_cell_and_not_the_sessions_its_script_left_running():
    running = (
        '{"chunk_id": "a1", "wall_time_seconds": 1.0, "session_id": 7, "output": ""}'
    )
    cell = ExecutionHandle(ExecutionHandleKind.SCRIPT, "g1:2")
    session = ExecutionHandle(ExecutionHandleKind.COMMAND, "7")
    still_running = "Script running with cell ID g1:2" + SCRIPT_HEAD + running
    ended = _script_result("Script completed", _printed(running))
    for content, handles in ((still_running, (cell, session)), (ended, (session,))):
        tool_call = _converted(_harness_tool_call("wait", {"cell_id": "g1:2"}, content))
        assert tool_call.result is not None and tool_call.result.handles == handles
        assert tool_call.action == PollAction(handles=(cell,))


def test_script_that_printed_only_an_image_has_no_text():
    image = {"type": "input_image", "image_url": "data:image/png;base64,AAAA"}
    for printed in ((image,), (image, _printed(""))):
        tool_call_result = _script_tool_call_result(
            "exec", _script_result("Script completed", *printed)
        )
        assert tool_call_result is not None
        assert (
            tool_call_result.execution_status,
            tool_call_result.tool_output_text,
        ) == (S.FINISHED, None)
    for content in (
        _script_result("Script completed"),
        "Script completed" + SCRIPT_HEAD,
    ):
        tool_call_result = _script_tool_call_result("exec", content)
        assert tool_call_result is not None and tool_call_result.tool_output_text == ""


def test_exec_steps_are_the_actions_of_the_tool_calls_in_its_script():
    code = (
        'await tools.exec_command({cmd: "curl -O https://a.org/f"});\n'
        'await tools.write_stdin({session_id: 7, chars: "\\u0003"});\n'
        'await tools.apply_patch("*** Begin Patch\\n*** Add File: a.sh\\n+curl x\\n*** End Patch");\n'
        'await tools.web__run({search_query: [{q: "x"}]});\n'
        "await tools.view_image({path: '/i.png'}); await tools.clock__curr_time({});\n"
        "await tools.exec({}); await tools.no_such_tool({});"
    )
    assert _script_action(code) == RunToolScriptAction(
        code,
        (
            RunCommandAction(
                "curl -O https://a.org/f",
                parse_shell_text(
                    "curl -O https://a.org/f", judgment_rule_use_counts=Counter()
                ),
            ),
            PollAction(
                (ExecutionHandle(ExecutionHandleKind.COMMAND, "7"),), "\x03", True
            ),
            WriteFileAction("a.sh", "curl x\n"),
            WebSearchAction(("x",)),
            ReadFileAction("/i.png"),
            OtherAction(),
            UnknownAction(),  # code mode has no exec
            UnknownAction(),
        ),
    )


def test_exec_steps_left_unread_are_empty_or_unknown():
    code = (
        "await tools.exec_command({cmd: c}); await tools.exec_command(o);"
        " await tools.apply_patch(p); await tools.web__run(q);"
        ' await tools.wait({cell_id: "1"}); await tools.request_user_input_async({});'
        " await tools.web_search_call({})"
    )
    assert _script_action(code) == RunToolScriptAction(
        code, (RunCommandAction(), RunCommandAction(), *[UnknownAction()] * 5)
    )
    assert _script_action('tools.exec_command({cmd: "x})') == RunToolScriptAction(
        'tools.exec_command({cmd: "x})'
    )
    assert _script_action(None) == RunToolScriptAction()


def test_result_that_only_looks_like_a_python_list_stays_text():
    for content in (
        "[{'type': 'input_text'",
        "[{'type': 'input_text', 'text': 'x'}, 1]",
    ):
        tool_call_result = _script_tool_call_result("exec", content)
        assert (
            tool_call_result is not None
            and tool_call_result.tool_output_text == content
        )


def test_only_exec_and_wait_have_their_python_list_text_read():
    content = "[{'type': 'input_text', 'text': 'x'}]"
    command = _harness_tool_call("exec_command", {"cmd": "x"}, content)
    assert CONVERTER.tool_result_raw_text_of(command, {"content": content}) == content
    script = _harness_tool_call("exec", {"input": "x"}, "[]")
    assert CONVERTER.tool_result_raw_text_of(script, {"content": "[]"}) == "[]"


def test_only_text_items_with_text_add_to_the_text_of_a_script():
    assert (
        _completed_exec_result({"type": "input_image", "text": "zzz"}).tool_output_text
        is None
    )
    printed = (
        {"type": "input_text", "text": None},
        {"type": "input_text", "text": "a"},
    )
    assert _completed_exec_result(*printed).tool_output_text == "a"


def test_only_web_search_call_without_content_is_no_content():
    tool_call_result = _command_result({"cmd": "x"}, None)
    assert tool_call_result.harness_result_format == UnmatchedFormat.UNKNOWN


def test_media_printed_beside_text_or_as_the_first_item_leave_the_text():
    image = {"type": "input_image", "image_url": "data:image/png;base64,AAAA"}
    with_text = _completed_exec_result(image, {"type": "input_text", "text": "a"})
    assert with_text.tool_output_text == "a"
    # The first item is the state of the script, so an image there was not printed.
    only_image = _converted(
        _harness_tool_call("exec", {"input": "x"}, repr([image]))
    ).result
    assert only_image is not None and only_image.tool_output_text == ""


def test_has_printed_media_holds_only_for_a_script_tool():
    content = repr([{"type": "input_text", "text": "x"}, {"type": "input_image"}])
    command = _harness_tool_call("exec_command", {"cmd": "x"}, content)
    assert not _has_printed_media(command, {"content": content})


def test_step_result_line_names_a_session_only_in_a_script_and_without_an_exit_code():
    command_output = (
        HEAD
        + "Process exited with code 0\nOriginal token count: 3\nOutput:\n"
        + '{"chunk_id": "a1", "session_id": 7}\n'
    )
    assert _command_result({"cmd": "x"}, command_output).handles == ()
    for line in (
        '{"chunk_id": "a1", oops}',
        '{"chunk_id": "a1", "wall_time_seconds": 1.0}',
        '{"chunk_id": "a1", "wall_time_seconds": 1.0, "session_id": 7, "exit_code": 0}',
    ):
        assert (
            _completed_exec_result({"type": "input_text", "text": line}).handles == ()
        ), line


def test_poll_other_than_wait_takes_the_session_its_result_names():
    running = (
        HEAD + "Process running with session ID 8\nOriginal token count: 0\nOutput:\n"
    )
    harness_tool_call = _harness_tool_call(
        "write_stdin", {"session_id": 7, "chars": ""}, running
    )
    assert _converted(harness_tool_call).action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "8"),)
    )


def test_ctrl_c_in_a_call_other_than_write_stdin_is_no_kill():
    exited = HEAD + "Process exited with code 130\nOriginal token count: 0\nOutput:\n"
    tool_call_result = _command_result({"cmd": "x", "chars": "\x03"}, exited)
    assert (tool_call_result.execution_status, tool_call_result.exit_code) == (
        S.FINISHED,
        130,
    )


def test_exec_step_of_a_script_asks_for_no_label():
    knowledge = ToolCallKnowledge()
    harness_tool_call = _harness_tool_call(
        "exec", {"input": "await tools.exec({});"}, None
    )
    harness_tool_call = replace(harness_tool_call, result=None)
    convert_one_tool_call(
        harness_tool_call,
        CONVERTER,
        knowledge=knowledge,
        judgment_rule_use_counts=Counter(),
    )
    assert knowledge.uses.row_use_counts[("harness_tools.csv", ("codex", "exec"))] == 1
