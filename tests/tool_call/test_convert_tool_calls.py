"""Tests for the common tool call conversion flow."""

from collections import Counter
from dataclasses import replace
from typing import Any

import pytest

from tb_internet_use.knowledge.catalog import KnowledgeUses
from tb_internet_use.knowledge.tool_call_knowledge import (
    HARNESS_RESULT_FORMATS_DECLARATIONS,
    ToolCallKnowledge,
)
from tb_internet_use.tool_call import convert_tool_calls
from tb_internet_use.tool_call._convert_tool_calls import convert_one_tool_call
from tb_internet_use.tool_call.harnesses import converter_for
from tb_internet_use.tool_call.harnesses.harness_tool_call_converter import (
    HarnessToolCallConverter,
)
from tb_internet_use.tool_call.model import (
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    HarnessToolLabel,
    PollAction,
    ReadFileAction,
    RunCommandAction,
    RunToolScriptAction,
    ToolCallAction,
    ToolCallKey,
    ToolCallResult,
    UnknownAction,
    WebSearchAction,
    WriteFileAction,
    strings_from_values,
)
from tb_internet_use.tool_call.parse_shell_text import parse_shell_text

S = ExecutionStatus


def _claude_code_result(text: str, structured_result: dict[str, Any] | None = None):
    """Give a Claude Code result as Harbor writes it, with the original text and, when given, the structured result in the metadata."""
    metadata: dict[str, Any] = {
        "raw_tool_result": {"type": "tool_result", "content": text}
    }
    if structured_result is not None:
        metadata["tool_use_result"] = structured_result
    return {"content": text, "extra": {"tool_result_metadata": metadata}}


def _codex_script_result(state: str, printed: str) -> dict[str, Any]:
    """Give a Codex `exec` result, a Python list of the state of the script and what it printed."""
    items = [
        {"type": "input_text", "text": state + "\nWall time 0.1 seconds\nOutput:\n"},
        {"type": "input_text", "text": printed},
    ]
    return {"content": repr(items)}


_GROK_FAILED_TASK = (
    "=== Task call1 ===\nCommand: sleep 5\nStatus: failed\nDuration: 1.0s\n"
)
_GROK_TASK_OUTPUT = "Output File: /t.log\n\n=== Output ===\npartial\n"
_DEVIN_DIFF_HEAD = (
    "[Changes since your last read, shown as a unified diff: '+' lines are new, '-' lines were "
    "replaced/removed in place, ' ' lines are unchanged context; '@@' line numbers index into the full output.]\n"
)

# Made-up results whose status or exit code the result text does not state, one or more for each judgment rule that a declared format names and for `treat_bash_output_without_exit_code_line_as_exit_code_0`, and one result that states both and uses no rule.
# (harness, tool, result, expected status and exit code, expected judgment rule uses)
JUDGMENT_RULE_CASES: list[
    tuple[str, str, dict[str, Any], tuple[ExecutionStatus, int | None], dict[str, int]]
] = [
    # A structured result that is neither interrupted nor has a `returnCodeInterpretation` lets the second rule give 0.
    (
        "claude-code",
        "Bash",
        _claude_code_result("hello", {"stdout": "hello", "interrupted": False}),
        (S.FINISHED, 0),
        {
            "treat_bash_output_without_exit_code_line_as_finished": 1,
            "treat_bash_output_without_exit_code_line_as_exit_code_0": 1,
        },
    ),
    # Without a structured result, 0 and the 1 of grep look the same, so no exit code.
    (
        "claude-code",
        "Bash",
        _claude_code_result("hello"),
        (S.FINISHED, None),
        {"treat_bash_output_without_exit_code_line_as_finished": 1},
    ),
    # A result that only says where the too large output was saved has no `Exit code` line either.
    (
        "claude-code",
        "Bash",
        _claude_code_result(
            "<persisted-output>\nOutput too large (3.1KB). Full output saved to: /tmp/p.txt\n\n"
            "Preview (first 2KB):\nhead\n</persisted-output>",
            {"stdout": "head", "interrupted": False},
        ),
        (S.FINISHED, 0),
        {
            "treat_bash_output_without_exit_code_line_as_finished": 1,
            "treat_bash_output_without_exit_code_line_as_exit_code_0": 1,
        },
    ),
    (
        "claude-code",
        "Read",
        _claude_code_result("File does not exist. Current working directory: /app"),
        (S.NOT_RUN, None),
        {"treat_failed_file_tool_call_as_not_run": 1},
    ),
    (
        "claude-code",
        "WebFetch",
        _claude_code_result("A page about tests."),
        (S.FINISHED, None),
        {"treat_web_fetch_text_as_finished": 1},
    ),
    (
        "codex",
        "exec",
        _codex_script_result("Script failed", "Script error:\nSyntaxError: oops"),
        (S.NOT_RUN, None),
        {"treat_script_syntax_error_as_not_run": 1},
    ),
    (
        "codex",
        "web_search_call",
        {"source_call_id": "id"},
        (S.FINISHED, None),
        {"treat_web_search_call_without_content_as_finished": 1},
    ),
    (
        "devin",
        "get_output",
        {"content": "partial output"},
        (S.RUNNING, None),
        {"treat_get_output_without_exit_code_as_running": 1},
    ),
    (
        "devin",
        "exec",
        {"content": "Output from command in shell sh1:\nfoo\nExit code: -1"},
        (S.KILLED, None),
        {"treat_negative_exit_code_as_killed": 1},
    ),
    (
        "devin",
        "write_to_process",
        {"content": "Written 3 bytes to shell sh1"},
        (S.RUNNING, None),
        {"treat_written_input_as_running_target": 1},
    ),
    # An idle subagent ended its turn and waits for a message, which can set it to work again.
    (
        "copilot-cli",
        "read_agent",
        {
            "content": "Agent is idle (waiting for messages). agent_id: a1, agent_type: explore, status: idle, description: Look around\n\n[Turn 0]\nDone.\n{}"
        },
        (S.UNKNOWN, None),
        {"treat_idle_subagent_as_unknown_status": 1},
    ),
    (
        "muse-code",
        "work_stop",
        {"content": '{"status": "accepted", "request_id": "r", "work_id": "w1"}'},
        (S.KILLED, None),
        {"treat_accepted_stop_request_as_killed": 1},
    ),
    (
        "grok-build",
        "get_command_or_subagent_output",
        {"content": _GROK_FAILED_TASK + _GROK_TASK_OUTPUT},
        (S.KILLED, None),
        {"treat_failed_task_without_exit_code_as_killed": 1},
    ),
    # A failed task with an `Exit Code` line states its own status and code.
    (
        "grok-build",
        "get_command_or_subagent_output",
        {"content": _GROK_FAILED_TASK + "Exit Code: 2\n" + _GROK_TASK_OUTPUT},
        (S.FINISHED, 2),
        {},
    ),
    (
        "claude-code",
        "Edit",
        _claude_code_result(
            "<tool_use_error>File has not been read yet.</tool_use_error>"
        ),
        (S.NOT_RUN, None),
        {"treat_tool_failure_message_as_not_run": 1},
    ),
    (
        "codex",
        "exec_command",
        {"content": "exec_command failed: no such shell"},
        (S.NOT_RUN, None),
        {"treat_tool_failure_message_as_not_run": 1},
    ),
    (
        "devin",
        "read",
        {"content": "Tool 'read' validation failed: a required argument is missing"},
        (S.NOT_RUN, None),
        {"treat_tool_failure_message_as_not_run": 1},
    ),
    (
        "devin",
        "get_output",
        {"content": _DEVIN_DIFF_HEAD + "@@ -1 +1,2 @@\n a\n+b\n"},
        (S.RUNNING, None),
        {"treat_get_output_without_exit_code_as_running": 1},
    ),
    # The exit code beside the shell id is not read.
    (
        "cursor-cli",
        "shellToolCall",
        {
            "content": '{"success": {"shellId": "3", "exitCode": 0, "interleavedOutput": "started"}}'
        },
        (S.RUNNING, None),
        {"treat_shell_id_with_exit_code_as_running": 1},
    ),
    (
        "muse-code",
        "work_stop",
        {"content": '{"status": "already_terminal", "work_id": "w1"}'},
        (S.FINISHED, None),
        {"treat_stop_request_for_ended_work_as_finished": 1},
    ),
    (
        "claude-code",
        "WebSearch",
        _claude_code_result(
            "The search was cut off before any results arrived. Try again."
        ),
        (S.FINISHED, None),
        {"treat_cut_off_web_search_as_finished": 1},
    ),
]


class _Converter(HarnessToolCallConverter):
    def convert_result(
        self,
        harness_tool_call: HarnessToolCall,
        tool_result: dict[str, Any],
        *,
        knowledge: ToolCallKnowledge,
        judgment_rule_use_counts: Counter[str],
    ) -> ToolCallResult:
        return ToolCallResult(tool_output_text=tool_result["content"])


class _ScriptConverter(_Converter):
    def action_of_deferred_tool(
        self,
        harness_tool_call: HarnessToolCall,
        tool_call_result: ToolCallResult | None,
        *,
        knowledge: ToolCallKnowledge,
    ) -> ToolCallAction:
        assert tool_call_result is not None
        return RunToolScriptAction(
            harness_tool_call.args["input"],
            (RunCommandAction(tool_call_result.tool_output_text),),
        )


class _RefiningConverter(_Converter):
    def refine_action(
        self,
        harness_tool_call: HarnessToolCall,
        action: ToolCallAction,
        tool_call_result: ToolCallResult | None,
        label: HarnessToolLabel,
    ) -> ToolCallAction:
        assert isinstance(action, PollAction)
        assert tool_call_result is not None
        assert label.action_type == "PollAction"
        return replace(action, input=tool_call_result.tool_output_text, terminate=True)


def _harness_tool_call(
    harness: str,
    tool: str,
    args: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
) -> HarnessToolCall:
    key = ToolCallKey("trial", "main", 1, 0)
    return HarnessToolCall(key, HarnessTool(harness, tool), "id", args or {}, result)


def _converted(
    harness_tool_call: HarnessToolCall,
    converter: HarnessToolCallConverter | None = None,
):
    return convert_one_tool_call(
        harness_tool_call,
        converter or _Converter(),
        knowledge=ToolCallKnowledge(),
        judgment_rule_use_counts=Counter(),
    )


def test_maps_labeled_args_and_ignores_the_rest():
    harness_tool_call = _harness_tool_call(
        "claude-code", "Bash", {"command": "ls", "timeout": 5}
    )
    assert _converted(harness_tool_call).action == RunCommandAction(
        "ls", parse_shell_text("ls", judgment_rule_use_counts=Counter())
    )


def test_converts_the_result_when_the_trajectory_has_one():
    harness_tool_call = _harness_tool_call(
        "claude-code", "Bash", result={"content": "ok"}
    )
    assert _converted(harness_tool_call).result == ToolCallResult(tool_output_text="ok")


def test_result_is_none_without_one_in_the_trajectory():
    assert _converted(_harness_tool_call("claude-code", "Bash")).result is None


def test_call_with_empty_args_keeps_its_action_type():
    harness_tool_call = _harness_tool_call("cursor-cli", "readToolCall")
    assert _converted(harness_tool_call).action == ReadFileAction()


def test_single_value_becomes_a_tuple_and_an_empty_one_none():
    harness_tool_call = _harness_tool_call("claude-code", "WebSearch", {"query": "a"})
    assert _converted(harness_tool_call).action == WebSearchAction(("a",))
    harness_tool_call = _harness_tool_call("claude-code", "WebSearch", {"query": ""})
    assert _converted(harness_tool_call).action == WebSearchAction(())
    assert strings_from_values(["a", "", None, 1, "a"]) == ("a", "1")


def test_handle_id_becomes_a_string_of_the_kind_its_catalog_row_gives():
    harness_tool_call = _harness_tool_call(
        "codex", "write_stdin", {"session_id": 7, "chars": "y"}
    )
    handle = ExecutionHandle(ExecutionHandleKind.COMMAND, "7")
    assert _converted(harness_tool_call).action == PollAction((handle,), "y")
    # A row without a handle kind leaves the kind unknown.
    harness_tool_call = _harness_tool_call("claude-code", "TaskOutput", {"task_id": 7})
    handle = ExecutionHandle(ExecutionHandleKind.UNKNOWN, "7")
    assert _converted(harness_tool_call).action == PollAction((handle,))


def test_handle_id_list_becomes_several_handles():
    harness_tool_call = _harness_tool_call(
        "grok-build", "get_command_or_subagent_output", {"task_ids": ["a", 1]}
    )
    action = _converted(harness_tool_call).action
    assert isinstance(action, PollAction)
    assert [handle.id for handle in action.handles] == ["a", "1"]


def test_blank_handle_id_is_dropped():
    harness_tool_call = _harness_tool_call(
        "cursor-cli", "awaitToolCall", {"taskId": ""}
    )
    assert _converted(harness_tool_call).action == PollAction()


def test_empty_stdin_input_means_the_poll_only_reads():
    harness_tool_call = _harness_tool_call(
        "codex", "write_stdin", {"session_id": 7, "chars": ""}
    )
    action = _converted(harness_tool_call).action
    assert isinstance(action, PollAction)
    assert action.input is None


def test_two_arguments_of_one_field_join_their_values_or_make_the_call_unknown():
    # `handles` holds several values, so it takes the targets of both arguments.
    harness_tool_call = _harness_tool_call(
        "claude-code", "SendMessage", {"to": "a1", "recipient": "a2"}
    )
    action = _converted(harness_tool_call).action
    assert isinstance(action, PollAction)
    assert [handle.id for handle in action.handles] == ["a1", "a2"]
    # Two arguments that name the same target give one handle, as in every such call of the trajectories.
    harness_tool_call = _harness_tool_call(
        "claude-code", "SendMessage", {"to": "a1", "recipient": "a1"}
    )
    action = _converted(harness_tool_call).action
    assert isinstance(action, PollAction)
    assert [handle.id for handle in action.handles] == ["a1"]
    # `path` holds one value, so two arguments must agree on it.
    harness_tool_call = _harness_tool_call(
        "claude-code", "Write", {"file_path": "/a", "path": "/a"}
    )
    assert _converted(harness_tool_call).action == WriteFileAction("/a")
    harness_tool_call = _harness_tool_call(
        "claude-code", "Write", {"file_path": "/a", "path": "/b"}
    )
    assert _converted(harness_tool_call).action == UnknownAction()


def test_refine_action_gets_the_action_the_result_and_the_label():
    harness_tool_call = _harness_tool_call(
        "claude-code", "TaskStop", {"task_id": "task-1"}, {"content": "done"}
    )
    handle = ExecutionHandle(ExecutionHandleKind.UNKNOWN, "task-1")
    action = _converted(harness_tool_call, _RefiningConverter()).action
    assert action == PollAction((handle,), "done", True)


def test_deferred_tool_uses_deferred_action_with_the_result():
    harness_tool_call = _harness_tool_call(
        "codex", "exec", {"input": "code"}, {"content": "done"}
    )
    action = _converted(harness_tool_call, _ScriptConverter()).action
    assert action == RunToolScriptAction(
        "code",
        (
            RunCommandAction(
                "done", parse_shell_text("done", judgment_rule_use_counts=Counter())
            ),
        ),
    )


def test_deferred_tool_without_an_implementation_raises():
    with pytest.raises(NotImplementedError, match="exec"):
        _converted(_harness_tool_call("codex", "exec"))


def test_convert_tool_calls_converts_every_call_of_its_harness_and_counts_lookups():
    knowledge = ToolCallKnowledge()
    result = {"content": '{"returncode": 0, "output": "out"}'}
    raws = [
        _harness_tool_call("mini-swe-agent", "bash", {"command": "ls"}, result),
        _harness_tool_call("mini-swe-agent", "NoSuchTool"),
    ]
    first, second = convert_tool_calls(
        raws, knowledge=knowledge, judgment_rule_use_counts=Counter()
    )
    assert first.action == RunCommandAction(
        "ls", parse_shell_text("ls", judgment_rule_use_counts=Counter())
    )
    assert first.result is not None and first.result.tool_output_text == "out"
    assert second.action == UnknownAction()
    assert knowledge.uses == KnowledgeUses(
        Counter(
            {
                ("harness_tools.csv", ("mini-swe-agent", "bash")): 1,
                (
                    "harness_tool_arguments.csv",
                    ("mini-swe-agent", "bash", "command"),
                ): 1,
                ("harness_result_formats", ("mini-swe-agent", "bash", "exited")): 1,
            }
        ),
        Counter({("harness_tools.csv", ("mini-swe-agent", "NoSuchTool")): 1}),
    )


def test_a_read_image_and_a_web_search_without_content_count_as_uses_of_their_declared_formats():
    knowledge = ToolCallKnowledge()
    image = {"type": "image", "source": {"type": "base64", "data": "AAAA"}}
    image_result = {
        "content": "",
        "extra": {
            "tool_result_metadata": {
                "raw_tool_result": {"type": "tool_result", "content": [image]}
            }
        },
    }
    raws = [
        _harness_tool_call(
            "claude-code", "Read", {"file_path": "/i.png"}, image_result
        ),
        _harness_tool_call("codex", "web_search_call", {"action_type": "search"}, {}),
    ]
    convert_tool_calls(raws, knowledge=knowledge, judgment_rule_use_counts=Counter())
    format_uses = {
        row_key: count
        for (source, row_key), count in knowledge.uses.row_use_counts.items()
        if source == HARNESS_RESULT_FORMATS_DECLARATIONS
    }
    assert format_uses == {
        ("claude-code", "Read", "image"): 1,
        ("codex", "web_search_call", "no_content"): 1,
    }


def test_converter_for_an_unknown_harness_raises():
    with pytest.raises(ValueError, match="nope"):
        converter_for("nope")


def test_convert_tool_calls_counts_each_judgment_rule_that_a_converter_applies():
    use_counts: Counter[str] = Counter()
    head = "Chunk ID: c1\nWall time: 0.1 seconds\nProcess exited with code {}\nOriginal token count: 0\nOutput:\n"
    # A Codex format that reads 130 as an exit code, so that only the rule of the converter makes it killed.
    killed = {"content": head.format(130)}
    exited = {"content": head.format(0)}
    ctrl_c = {"session_id": 7, "chars": "\x03"}
    raws = [
        _harness_tool_call("codex", "write_stdin", ctrl_c, killed),
        _harness_tool_call("codex", "write_stdin", ctrl_c, exited),
        _harness_tool_call("codex", "write_stdin", ctrl_c, killed),
    ]
    convert_tool_calls(
        raws, knowledge=ToolCallKnowledge(), judgment_rule_use_counts=use_counts
    )
    assert use_counts == Counter({"treat_exit_code_130_after_ctrl_c_as_killed": 2})


@pytest.mark.parametrize(
    ("harness", "tool", "result", "status_and_exit_code", "rule_uses"),
    JUDGMENT_RULE_CASES,
)
def test_a_result_whose_text_does_not_state_its_status_gets_it_from_a_counted_judgment_rule(
    harness: str,
    tool: str,
    result: dict[str, Any],
    status_and_exit_code: tuple[ExecutionStatus, int | None],
    rule_uses: dict[str, int],
):
    use_counts: Counter[str] = Counter()
    (tool_call,) = convert_tool_calls(
        [_harness_tool_call(harness, tool, {}, result)],
        knowledge=ToolCallKnowledge(),
        judgment_rule_use_counts=use_counts,
    )
    assert tool_call.result is not None
    assert (
        tool_call.result.execution_status,
        tool_call.result.exit_code,
    ) == status_and_exit_code
    assert use_counts == Counter(rule_uses)
