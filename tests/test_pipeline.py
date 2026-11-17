"""Tests for pipeline.py, with made-up trial folders."""

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from tb_internet_use.pipeline import read_trajectory, read_trial_file_texts
from tb_internet_use.tool_call.model import ToolCallKey
from tb_internet_use.trial.model import (
    TrialFileTexts,
    UnreadableTrajectory,
    UnreadableTrajectoryReason,
)

# Made-up detail and status files whose ids differ from the folder name `trial-1`, so that a trial id read from a file instead of the folder name fails.
_DETAIL_BYTES = json.dumps(
    {"id": "detail-id", "task_name": "terminal-bench/a"}
).encode()
_STATUS_BYTES = json.dumps({"trial_id": "status-id", "memberships": []}).encode()


def _trial_dir(tmp_path: Path, bytes_by_file_name: Mapping[str, bytes]) -> Path:
    """Make a trial folder named `trial-1` that holds the given files."""
    trial_dir = tmp_path / "trial-1"
    trial_dir.mkdir()
    for file_name, file_bytes in bytes_by_file_name.items():
        (trial_dir / file_name).write_bytes(file_bytes)
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
        _trial_dir(tmp_path, {"trajectory.json": json.dumps(trajectory).encode()})
    )

    assert not isinstance(harness_tool_calls, UnreadableTrajectory)
    assert [harness_tool_call.key for harness_tool_call in harness_tool_calls] == [
        ToolCallKey("trial-1", "main", 3, 0)
    ]


def test_folder_without_a_trajectory_file_is_unreadable_as_missing(tmp_path):
    assert read_trajectory(_trial_dir(tmp_path, {})) == UnreadableTrajectory(
        UnreadableTrajectoryReason.MISSING
    )


def test_trajectory_file_that_is_not_utf8_is_unreadable_as_invalid_json(tmp_path):
    trial_dir = _trial_dir(tmp_path, {"trajectory.json": b'{"steps": "\xff"}'})

    assert read_trajectory(trial_dir) == UnreadableTrajectory(
        UnreadableTrajectoryReason.INVALID_JSON
    )


def test_reads_the_bytes_of_the_detail_and_status_files_with_the_folder_name_as_trial_id(
    tmp_path,
):
    trial_dir = _trial_dir(
        tmp_path, {"detail.json": _DETAIL_BYTES, "status.json": _STATUS_BYTES}
    )

    assert read_trial_file_texts(trial_dir) == TrialFileTexts(
        "trial-1", _DETAIL_BYTES, _STATUS_BYTES
    )


def test_keeps_bytes_that_are_not_utf8_for_the_reading_functions(tmp_path):
    trial_dir = _trial_dir(
        tmp_path,
        {"detail.json": b'{"task_name": "\xff"}', "status.json": b'{"x": "\xfe"}'},
    )

    trial_file_texts = read_trial_file_texts(trial_dir)

    assert trial_file_texts.detail_text == b'{"task_name": "\xff"}'
    assert trial_file_texts.status_text == b'{"x": "\xfe"}'


@pytest.mark.parametrize("missing_file_name", ["detail.json", "status.json"])
def test_folder_without_the_detail_or_status_file_raises(tmp_path, missing_file_name):
    bytes_by_file_name = {"detail.json": _DETAIL_BYTES, "status.json": _STATUS_BYTES}
    del bytes_by_file_name[missing_file_name]

    with pytest.raises(FileNotFoundError, match=missing_file_name):
        read_trial_file_texts(_trial_dir(tmp_path, bytes_by_file_name))
