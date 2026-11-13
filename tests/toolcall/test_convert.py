"""Tests for the common tool call conversion flow."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tb_internet_use.toolcall import convert_trial
from tb_internet_use.toolcall.convert import convert_call
from tb_internet_use.toolcall.harnesses import converter_for
from tb_internet_use.toolcall.harnesses.base import HarnessToolCallConverter
from tb_internet_use.toolcall.model import (
    Action,
    ExecutionHandle,
    ExecutionHandleKind,
    HarnessTool,
    PollAction,
    RawToolCall,
    ReadFileAction,
    RunCommandAction,
    RunToolScriptAction,
    ToolCallKey,
    ToolCallOutput,
    UnknownAction,
    WebSearchAction,
    string_tuple,
)


class _Converter(HarnessToolCallConverter):
    def parse_output(self, raw: RawToolCall, result: dict[str, Any]) -> ToolCallOutput:
        return ToolCallOutput(tool_output_text=result["content"])


class _ScriptConverter(_Converter):
    def deferred_action(
        self, raw: RawToolCall, output: ToolCallOutput | None
    ) -> Action:
        assert output is not None
        return RunToolScriptAction(
            raw.args["input"], (RunCommandAction(output.tool_output_text),)
        )


class _RefiningConverter(_Converter):
    def refine_action(
        self, raw: RawToolCall, action: Action, output: ToolCallOutput | None
    ) -> Action:
        assert isinstance(action, PollAction)
        assert output is not None
        return replace(action, input=output.tool_output_text, terminate=True)


def _raw(
    harness: str,
    tool: str,
    args: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
) -> RawToolCall:
    key = ToolCallKey("trial", "main", 1, 0)
    return RawToolCall(key, HarnessTool(harness, tool), "id", args or {}, result)


def test_maps_labeled_args_and_ignores_the_rest():
    raw = _raw("claude-code", "Bash", {"command": "ls", "timeout": 5})
    assert convert_call(raw, _Converter()).action == RunCommandAction("ls")


def test_parses_output_when_the_trajectory_has_a_result():
    raw = _raw("claude-code", "Bash", result={"content": "ok"})
    assert convert_call(raw, _Converter()).output == ToolCallOutput(
        tool_output_text="ok"
    )


def test_output_is_none_without_a_result():
    assert convert_call(_raw("claude-code", "Bash"), _Converter()).output is None


def test_tool_missing_from_catalog_is_unknown():
    raw = _raw("claude-code", "NoSuchTool")
    assert convert_call(raw, _Converter()).action == UnknownAction()


def test_call_with_empty_args_keeps_its_action_type():
    raw = _raw("cursor-cli", "readToolCall")
    assert convert_call(raw, _Converter()).action == ReadFileAction()


def test_single_value_becomes_a_tuple_and_an_empty_one_none():
    raw = _raw("claude-code", "WebSearch", {"query": "a"})
    assert convert_call(raw, _Converter()).action == WebSearchAction(("a",))
    raw = _raw("claude-code", "WebSearch", {"query": ""})
    assert convert_call(raw, _Converter()).action == WebSearchAction(())
    assert string_tuple(["a", "", None, 1, "a"]) == ("a", "1")


def test_handle_id_becomes_a_string_of_unknown_kind():
    raw = _raw("codex", "write_stdin", {"session_id": 7, "chars": "y"})
    handle = ExecutionHandle(ExecutionHandleKind.UNKNOWN, "7")
    assert convert_call(raw, _Converter()).action == PollAction((handle,), "y")


def test_handle_id_list_becomes_several_handles():
    raw = _raw("grok-build", "get_command_or_subagent_output", {"task_ids": ["a", 1]})
    action = convert_call(raw, _Converter()).action
    assert isinstance(action, PollAction)
    assert [handle.id for handle in action.handles] == ["a", "1"]


def test_blank_handle_id_is_dropped():
    raw = _raw("cursor-cli", "awaitToolCall", {"taskId": ""})
    assert convert_call(raw, _Converter()).action == PollAction()


def test_empty_stdin_input_means_the_poll_only_reads():
    raw = _raw("codex", "write_stdin", {"session_id": 7, "chars": ""})
    action = convert_call(raw, _Converter()).action
    assert isinstance(action, PollAction)
    assert action.input is None


def test_non_integer_offset_is_dropped():
    raw = _raw("claude-code", "Read", {"file_path": "/a", "offset": "bad", "limit": 3})
    assert convert_call(raw, _Converter()).action == ReadFileAction("/a", None, 3)


def test_refine_action_gets_the_action_and_output():
    raw = _raw("claude-code", "TaskStop", {"task_id": "task-1"}, {"content": "done"})
    handle = ExecutionHandle(ExecutionHandleKind.UNKNOWN, "task-1")
    action = convert_call(raw, _RefiningConverter()).action
    assert action == PollAction((handle,), "done", True)


def test_deferred_tool_uses_deferred_action_with_the_output():
    raw = _raw("codex", "exec", {"input": "code"}, {"content": "done"})
    action = convert_call(raw, _ScriptConverter()).action
    assert action == RunToolScriptAction("code", (RunCommandAction("done"),))


def test_deferred_tool_without_an_implementation_raises():
    with pytest.raises(NotImplementedError, match="exec"):
        convert_call(_raw("codex", "exec"), _Converter())


def test_convert_trial_reads_and_converts_every_call(tmp_path: Path):
    trial_dir = tmp_path / "trial-1"
    trial_dir.mkdir()
    step = {
        "step_id": 1,
        "tool_calls": [
            {
                "tool_call_id": "a",
                "function_name": "Bash",
                "arguments": {"command": "ls"},
            }
        ],
        "observation": {"results": [{"source_call_id": "a", "content": "out"}]},
    }
    trajectory = {
        "schema_version": "ATIF-v1.7",
        "agent": {"name": "claude-code"},
        "steps": [step],
    }
    (trial_dir / "trajectory.json").write_text(json.dumps(trajectory))
    [call] = convert_trial(trial_dir)
    assert call.action == RunCommandAction("ls")
    assert call.output is not None and call.output.tool_output_text == "out"
    assert convert_trial(tmp_path / "missing") == []


def test_converter_for_an_unknown_harness_raises():
    with pytest.raises(ValueError, match="nope"):
        converter_for("nope")
