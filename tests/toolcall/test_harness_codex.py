"""Codex converter tests, with made-up results shaped as in the trajectories."""

from typing import Any

import pytest

from tb_internet_use.toolcall.convert import convert_call
from tb_internet_use.toolcall.harnesses.codex import CodexConverter
from tb_internet_use.toolcall.model import (
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    MatchedFormat,
    OtherAction,
    PollAction,
    RawToolCall,
    RunCommandAction,
    RunToolScriptAction,
    ToolCallKey,
    UnknownAction,
    UnmatchedFormat,
    WebFetchAction,
    WebFindAction,
    WebSearchAction,
    WriteFileAction,
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


SCRIPT_HEAD = "\nWall time 0.1 seconds\nOutput:\n"


def _script_result(state: str, *printed: dict[str, str]) -> str:
    """An exec or wait result as Codex writes it, a Python list of content items."""
    return repr([{"type": "input_text", "text": state + SCRIPT_HEAD}, *printed])


def _printed(text: str) -> dict[str, str]:
    return {"type": "input_text", "text": text}


def _script_output(tool: str, content: str):
    return convert_call(_raw(tool, {"input": "x"}, content), CONVERTER).output


def test_exec_result_is_what_the_script_printed():
    output = _script_output(
        "exec", _script_result("Script completed", _printed("a"), _printed("b"))
    )
    assert output is not None
    assert (
        output.execution_status,
        output.tool_output_text,
        output.harness_result_format,
    ) == (S.FINISHED, "a\nb", MatchedFormat("completed"))


WARNING = "Warning: truncated output (original token count: 9)\n"
LINES = "Total output lines: 3\n\n"


@pytest.mark.parametrize(
    ("tool", "content", "name", "status", "truncated", "handle_kind"),
    [
        (
            "exec",
            "Script completed" + SCRIPT_HEAD + WARNING + LINES + "x",
            "completed_truncated",
            S.FINISHED,
            True,
            None,
        ),
        (
            "wait",
            "Script completed" + SCRIPT_HEAD + WARNING + LINES + "x",
            "completed_truncated",
            S.FINISHED,
            True,
            None,
        ),
        (
            "exec",
            "Script completed" + SCRIPT_HEAD + WARNING + "... 5 bytes omitted ...\n\nx",
            "completed_truncated_bytes",
            S.FINISHED,
            True,
            None,
        ),
        (
            "wait",
            "Script completed" + SCRIPT_HEAD + "x",
            "completed",
            S.FINISHED,
            None,
            None,
        ),
        (
            "wait",
            "Script failed" + SCRIPT_HEAD + "Script error:\nboom",
            "failed",
            S.FINISHED,
            None,
            None,
        ),
        (
            "wait",
            "Script failed" + SCRIPT_HEAD + "Script error:\nexec cell 9 not found",
            "cell_not_found",
            S.NOT_RUN,
            None,
            None,
        ),
        (
            "exec",
            "Script running with cell ID c1" + SCRIPT_HEAD + WARNING + LINES + "x",
            "running_truncated",
            S.RUNNING,
            True,
            ExecutionHandleKind.SCRIPT,
        ),
        (
            "wait",
            "Script running with cell ID c1" + SCRIPT_HEAD + WARNING + LINES + "x",
            "running_truncated",
            S.RUNNING,
            True,
            ExecutionHandleKind.SCRIPT,
        ),
        (
            "wait",
            "Script running with cell ID c1" + SCRIPT_HEAD,
            "running",
            S.RUNNING,
            None,
            ExecutionHandleKind.SCRIPT,
        ),
        ("wait", "Script terminated" + SCRIPT_HEAD, "terminated", S.KILLED, None, None),
        (
            "wait",
            "failed to parse function arguments: invalid type",
            "rejected_arguments",
            S.NOT_RUN,
            None,
            None,
        ),
        (
            "exec",
            "code-mode host exited with status signal: 9 (SIGKILL)",
            "host_killed",
            S.KILLED,
            None,
            None,
        ),
        (
            "exec",
            "code-mode host exited with status exit status: 1",
            "host_exited",
            S.UNKNOWN,
            None,
            None,
        ),
    ],
)
def test_script_result_formats(
    tool: str,
    content: str,
    name: str,
    status: ExecutionStatus,
    truncated: bool | None,
    handle_kind: ExecutionHandleKind | None,
):
    output = _script_output(tool, content)
    assert output is not None
    assert (
        output.harness_result_format,
        output.execution_status,
        output.is_truncated,
        [h.kind for h in output.handles],
    ) == (MatchedFormat(name), status, truncated, [handle_kind] if handle_kind else [])


def test_running_script_names_its_cell_as_a_script_handle():
    output = _script_output("exec", "Script running with cell ID g1:2" + SCRIPT_HEAD)
    assert output is not None
    assert (output.execution_status, output.handles) == (
        S.RUNNING,
        (ExecutionHandle(ExecutionHandleKind.SCRIPT, "g1:2"),),
    )


def test_failed_script_keeps_its_error_unless_it_never_ran():
    error = "Script error:\nexec_command failed for `x`: boom"
    output = _script_output("exec", _script_result("Script failed", _printed(error)))
    assert output is not None
    assert (output.execution_status, output.tool_output_text) == (S.FINISHED, error)
    syntax = "Script error:\nSyntaxError: Unexpected token"
    output = _script_output("exec", _script_result("Script failed", _printed(syntax)))
    assert output is not None
    assert (output.execution_status, output.tool_output_text) == (S.NOT_RUN, "")


def test_script_that_printed_only_an_image_has_no_text():
    image = {"type": "input_image", "image_url": "data:image/png;base64,AAAA"}
    for printed in ((image,), (image, _printed(""))):
        output = _script_output("exec", _script_result("Script completed", *printed))
        assert output is not None
        assert (output.execution_status, output.tool_output_text) == (S.FINISHED, None)
    for content in (
        _script_result("Script completed"),
        "Script completed" + SCRIPT_HEAD,
    ):
        output = _script_output("exec", content)
        assert output is not None and output.tool_output_text == ""


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


def _script_action(code: str | None):
    args = {} if code is None else {"input": code}
    return convert_call(
        _raw("exec", args, "Script completed" + SCRIPT_HEAD), CONVERTER
    ).action


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
            RunCommandAction("curl -O https://a.org/f"),
            PollAction(
                (ExecutionHandle(ExecutionHandleKind.COMMAND, "7"),), "\x03", True
            ),
            WriteFileAction("a.sh", "curl x\n"),
            WebSearchAction(("x",)),
            OtherAction(),
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
        output = _script_output("exec", content)
        assert output is not None and output.tool_output_text == content
