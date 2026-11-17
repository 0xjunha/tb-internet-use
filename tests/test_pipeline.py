"""Tests for pipeline.py, with made-up trial folders."""

import json
from pathlib import Path

from tb_internet_use.pipeline import read_trajectory
from tb_internet_use.tool_call.model import ToolCallKey
from tb_internet_use.trial.model import UnreadableTrajectory, UnreadableTrajectoryReason


def _trial_dir(tmp_path: Path, trajectory_bytes: bytes | None) -> Path:
    """Make a trial folder named `trial-1`, with a trajectory file when it gets bytes."""
    trial_dir = tmp_path / "trial-1"
    trial_dir.mkdir()
    if trajectory_bytes is not None:
        (trial_dir / "trajectory.json").write_bytes(trajectory_bytes)
    return trial_dir


def test_reads_the_calls_of_the_trajectory_file_with_the_folder_name_as_trial_id(
    tmp_path,
):
    trajectory_tool_call = {
        "tool_call_id": "a",
        "function_name": "bash",
        "arguments": {},
    }
    trajectory = {
        "schema_version": "ATIF-v1.7",
        "agent": {"name": "codex"},
        "steps": [{"step_id": 3, "tool_calls": [trajectory_tool_call]}],
    }

    harness_tool_calls = read_trajectory(
        _trial_dir(tmp_path, json.dumps(trajectory).encode())
    )

    assert not isinstance(harness_tool_calls, UnreadableTrajectory)
    assert [harness_tool_call.key for harness_tool_call in harness_tool_calls] == [
        ToolCallKey("trial-1", "main", 3, 0)
    ]


def test_folder_without_a_trajectory_file_is_unreadable_as_missing(tmp_path):
    assert read_trajectory(_trial_dir(tmp_path, None)) == UnreadableTrajectory(
        UnreadableTrajectoryReason.MISSING
    )


def test_trajectory_file_that_is_not_utf8_is_unreadable_as_invalid_json(tmp_path):
    trial_dir = _trial_dir(tmp_path, b'{"steps": "\xff"}')

    assert read_trajectory(trial_dir) == UnreadableTrajectory(
        UnreadableTrajectoryReason.INVALID_JSON
    )
