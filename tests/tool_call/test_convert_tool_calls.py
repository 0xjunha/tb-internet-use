"""Tests for the common tool call conversion flow."""

from collections import Counter
from dataclasses import replace
from typing import Any

import pytest

from tb_internet_use.knowledge.catalog import KnowledgeUses
from tb_internet_use.knowledge.tool_call_knowledge import (
    HarnessToolLabel,
    ToolCallKnowledge,
)
from tb_internet_use.tool_call import convert_tool_calls
from tb_internet_use.tool_call._convert_tool_calls import convert_one_tool_call
from tb_internet_use.tool_call.harnesses import converter_for
from tb_internet_use.tool_call.harnesses.harness_tool_call_converter import (
    HarnessToolCallConverter,
)
from tb_internet_use.tool_call.model import (
    DeleteFileAction,
    ExecutionHandle,
    ExecutionHandleKind,
    HarnessTool,
    HarnessToolCall,
    ListFilesAction,
    PollAction,
    ReadFileAction,
    RunCommandAction,
    RunToolScriptAction,
    SearchFilesAction,
    StartSubagentAction,
    ToolCallAction,
    ToolCallKey,
    ToolCallResult,
    UnknownAction,
    WebSearchAction,
    WriteFileAction,
    strings_from_values,
)

_SUBAGENT = ExecutionHandle(ExecutionHandleKind.SUBAGENT, "a1")
# (harness, tool, arguments of a call, action of the call), one case per tool that reads, searches, lists or deletes files or that starts or polls a subagent.
_FILE_AND_SUBAGENT_TOOL_CASES = [
    ("codex", "view_image", {"path": "/app/plot.png"}, ReadFileAction("/app/plot.png")),
    (
        "cursor-cli",
        "grepToolCall",
        {"pattern": "x", "path": "/app/run.log"},
        SearchFilesAction(("/app/run.log",)),
    ),
    ("devin", "grep", {"pattern": "x", "path": "/app"}, SearchFilesAction(("/app",))),
    (
        "grok-build",
        "grep",
        {"pattern": "x", "path": "/app"},
        SearchFilesAction(("/app",)),
    ),
    # A search that names no path keeps its type.
    ("grok-build", "grep", {"pattern": "x"}, SearchFilesAction()),
    (
        "muse-code",
        "search",
        {"pattern": "x", "paths": ["/app/a", "/app/b"]},
        SearchFilesAction(("/app/a", "/app/b")),
    ),
    (
        "cursor-cli",
        "globToolCall",
        {"globPattern": "*.log", "targetDirectory": "/app"},
        ListFilesAction("/app"),
    ),
    (
        "devin",
        "find_file_by_name",
        {"pattern": "*.log", "path": "/app"},
        ListFilesAction("/app"),
    ),
    ("grok-build", "list_dir", {"target_directory": "/app"}, ListFilesAction("/app")),
    (
        "cursor-cli",
        "deleteToolCall",
        {"path": "/app/a.txt"},
        DeleteFileAction("/app/a.txt"),
    ),
    ("claude-code", "Agent", {"prompt": "p"}, StartSubagentAction()),
    ("cursor-cli", "taskToolCall", {"prompt": "p"}, StartSubagentAction()),
    ("devin", "run_subagent", {"task": "p"}, StartSubagentAction()),
    ("muse-code", "subagent_spawn", {"objective": "p"}, StartSubagentAction()),
    ("muse-code", "workflow", {"script": "s"}, StartSubagentAction()),
    # `recipient` names the same subagent as `to`, and the message text fills no field.
    (
        "claude-code",
        "SendMessage",
        {
            "to": "a1",
            "recipient": "a1",
            "message": "go on with the build",
            "content": "go on…",
            "summary": "s",
        },
        PollAction((_SUBAGENT,)),
    ),
    ("devin", "read_subagent", {"agent_id": "a1"}, PollAction((_SUBAGENT,))),
    ("codex", "wait_agent", {"timeout_ms": 1000}, PollAction()),
    (
        "codex",
        "interrupt_agent",
        {"target": "a1"},
        PollAction((_SUBAGENT,), None, True),
    ),
    ("muse-code", "subagent_status", {"subagent_id": "a1"}, PollAction((_SUBAGENT,))),
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
    assert _converted(harness_tool_call).action == RunCommandAction("ls")


def test_parses_output_when_the_trajectory_has_a_result():
    harness_tool_call = _harness_tool_call(
        "claude-code", "Bash", result={"content": "ok"}
    )
    assert _converted(harness_tool_call).result == ToolCallResult(tool_output_text="ok")


def test_output_is_none_without_a_result():
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


def test_non_integer_offset_is_dropped():
    harness_tool_call = _harness_tool_call(
        "claude-code", "Read", {"file_path": "/a", "offset": "bad", "limit": 3}
    )
    assert _converted(harness_tool_call).action == ReadFileAction("/a", None, 3)


@pytest.mark.parametrize(
    ("harness", "tool", "args", "action"), _FILE_AND_SUBAGENT_TOOL_CASES
)
def test_file_or_subagent_tool_gets_the_action_of_its_catalog_rows(
    harness, tool, args, action
):
    harness_tool_call = _harness_tool_call(harness, tool, args)
    assert _converted(harness_tool_call, converter_for(harness)).action == action


def test_two_arguments_of_one_field_join_their_values_or_make_the_call_unknown():
    # `handles` holds several values, so it takes the targets of both arguments.
    harness_tool_call = _harness_tool_call(
        "claude-code", "SendMessage", {"to": "a1", "recipient": "a2"}
    )
    action = _converted(harness_tool_call).action
    assert isinstance(action, PollAction)
    assert [handle.id for handle in action.handles] == ["a1", "a2"]
    # `path` holds one value, so two arguments must agree on it.
    harness_tool_call = _harness_tool_call(
        "claude-code", "Write", {"file_path": "/a", "path": "/a"}
    )
    assert _converted(harness_tool_call).action == WriteFileAction("/a")
    harness_tool_call = _harness_tool_call(
        "claude-code", "Write", {"file_path": "/a", "path": "/b"}
    )
    assert _converted(harness_tool_call).action == UnknownAction()


def test_refine_action_gets_the_action_the_output_and_the_label():
    harness_tool_call = _harness_tool_call(
        "claude-code", "TaskStop", {"task_id": "task-1"}, {"content": "done"}
    )
    handle = ExecutionHandle(ExecutionHandleKind.UNKNOWN, "task-1")
    action = _converted(harness_tool_call, _RefiningConverter()).action
    assert action == PollAction((handle,), "done", True)


def test_deferred_tool_uses_deferred_action_with_the_output():
    harness_tool_call = _harness_tool_call(
        "codex", "exec", {"input": "code"}, {"content": "done"}
    )
    action = _converted(harness_tool_call, _ScriptConverter()).action
    assert action == RunToolScriptAction("code", (RunCommandAction("done"),))


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
    assert first.action == RunCommandAction("ls")
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


def test_converter_for_an_unknown_harness_raises():
    with pytest.raises(ValueError, match="nope"):
        converter_for("nope")


def test_convert_tool_calls_counts_each_judgment_rule_that_a_converter_applies():
    use_counts: Counter[str] = Counter()
    # A Devin format that reads -1 as an exit code, so that only the rule makes it killed.
    killed = {"content": "foo\nExit code: -1"}
    exited = {"content": "foo\nExit code: 0"}
    raws = [
        _harness_tool_call("devin", "get_output", {"shell_id": "s1"}, killed),
        _harness_tool_call("devin", "get_output", {"shell_id": "s1"}, exited),
        _harness_tool_call("devin", "get_output", {"shell_id": "s1"}, killed),
    ]
    convert_tool_calls(
        raws, knowledge=ToolCallKnowledge(), judgment_rule_use_counts=use_counts
    )
    assert use_counts == Counter({"treat_negative_exit_code_as_killed": 2})
