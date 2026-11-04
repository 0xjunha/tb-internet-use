"""Tests for the ATIF reader."""

import json
from pathlib import Path
from typing import Any

import pytest

from tb_internet_use.toolcall.atif_reader import (
    TrajectoryStatus,
    _drop_agent_loop_notices,
    _pair_calls_with_results,
    _walk_trajectory,
    read_trial_tool_calls,
)
from tb_internet_use.toolcall.model import ToolCallKey

NOTICE = {"content": "Tool call error:\n\n<error>No tool calls found</error>"}


def _call(tool_call_id: str = "a") -> dict[str, Any]:
    return {"tool_call_id": tool_call_id, "function_name": "bash", "arguments": {}}


def _write_trial(tmp_path: Path, content: str) -> Path:
    trial_dir = tmp_path / "trial-1"
    trial_dir.mkdir()
    (trial_dir / "trajectory.json").write_text(content)
    return trial_dir


def test_drops_notice_for_mini_swe_agent():
    result = {"content": '{"returncode": 0, "output": "ok"}'}
    assert _drop_agent_loop_notices("mini-swe-agent", [result, NOTICE]) == [result]


def test_keeps_notice_text_for_other_harness():
    assert _drop_agent_loop_notices("codex", [NOTICE]) == [NOTICE]


def test_pairs_by_id_in_call_order():
    a, b = _call("a"), _call("b")
    result_a, result_b = {"source_call_id": "a"}, {"source_call_id": "b"}
    assert _pair_calls_with_results([a, b], [result_b, result_a]) == [
        (a, result_a),
        (b, result_b),
    ]


def test_repeated_id_pairs_in_order():
    first, second = _call("a"), _call("a")
    result_1 = {"source_call_id": "a", "content": "1"}
    result_2 = {"source_call_id": "a", "content": "2"}
    assert _pair_calls_with_results([first, second], [result_1, result_2]) == [
        (first, result_1),
        (second, result_2),
    ]


def test_result_without_id_pairs_by_position():
    a, b = _call("a"), _call("b")
    result_1, result_2 = {"content": "1"}, {"content": "2"}
    assert _pair_calls_with_results([a, b], [result_1, result_2]) == [
        (a, result_1),
        (b, result_2),
    ]


def test_call_without_result_gets_none():
    call = _call()
    assert _pair_calls_with_results([call], []) == [(call, None)]


def test_unpairable_results_raise():
    with pytest.raises(ValueError, match="unmatched"):
        _pair_calls_with_results([_call()], [{"content": "1"}, {"content": "2"}])


def test_subagent_calls_are_yielded_once():
    # Several main steps must not walk the subagent again.
    trajectory = {
        "steps": [{"step_id": 1}, {"step_id": 2}],
        "subagent_trajectories": [{"steps": [{"step_id": 1, "tool_calls": [_call()]}]}],
    }
    calls = list(_walk_trajectory(trajectory, "t", "muse-code", "main", False))

    assert [call.key.trajectory_id for call in calls] == ["main/sub0"]
    assert calls[0].is_subagent is True


def test_sidechain_step_is_subagent():
    trajectory = {
        "steps": [
            {"step_id": 1, "tool_calls": [_call()]},
            {"step_id": 2, "tool_calls": [_call()], "extra": {"is_sidechain": True}},
        ]
    }
    calls = list(_walk_trajectory(trajectory, "t", "claude-code", "main", False))

    assert [call.is_subagent for call in calls] == [False, True]


def test_reads_trial(tmp_path):
    step = {
        "step_id": 3,
        "tool_calls": [_call("a")],
        "observation": {"results": [{"source_call_id": "a", "content": "ok"}]},
    }
    trajectory = {
        "schema_version": "ATIF-v1.7",
        "agent": {"name": "codex"},
        "steps": [step],
    }
    trial = read_trial_tool_calls(_write_trial(tmp_path, json.dumps(trajectory)))

    assert trial.trial_id == "trial-1"
    assert trial.trajectory_status is TrajectoryStatus.OK
    call = trial.calls[0]
    assert call.key == ToolCallKey("trial-1", "main", 3, 0)
    assert call.tool.harness == "codex"
    assert call.output.raw_result["content"] == "ok"
    assert call.actions == ()


def test_missing_trajectory(tmp_path):
    trial = read_trial_tool_calls(tmp_path / "trial-1")

    assert trial.trajectory_status is TrajectoryStatus.MISSING
    assert trial.calls == ()


def test_invalid_json(tmp_path):
    trial = read_trial_tool_calls(_write_trial(tmp_path, "{not json"))

    assert trial.trajectory_status is TrajectoryStatus.INVALID_JSON
    assert trial.calls == ()


def test_unknown_schema_raises_with_trial_id(tmp_path):
    trajectory = {"schema_version": "ATIF-v9", "agent": {"name": "codex"}, "steps": []}
    trial_dir = _write_trial(tmp_path, json.dumps(trajectory))

    with pytest.raises(ValueError, match="ATIF-v9") as error:
        read_trial_tool_calls(trial_dir)
    assert "trial_id: trial-1" in error.value.__notes__
