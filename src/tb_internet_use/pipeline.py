"""Open the files of one trial for the steps of the pipeline, which take text and types and never a path."""

from pathlib import Path

from tb_internet_use.tool_call.model import (
    HarnessToolCall,
    UnreadableTrajectory,
    UnreadableTrajectoryReason,
)
from tb_internet_use.tool_call.parse_trajectory import parse_trajectory

_TRAJECTORY_FILE_NAME = "trajectory.json"


def read_trajectory(
    trial_dir: Path,
) -> tuple[HarnessToolCall, ...] | UnreadableTrajectory:
    """Read the tool calls of one trial from the trajectory file in its folder, or an `UnreadableTrajectory` when the file is missing or is not JSON.

    The name of the folder is the trial id of the calls.
    """
    try:
        # The bytes go to `parse_trajectory` as they are, so that it also reports broken UTF-8.
        trajectory_text = (trial_dir / _TRAJECTORY_FILE_NAME).read_bytes()
    except FileNotFoundError:
        return UnreadableTrajectory(UnreadableTrajectoryReason.MISSING)
    return parse_trajectory(trajectory_text, trial_dir.name)
