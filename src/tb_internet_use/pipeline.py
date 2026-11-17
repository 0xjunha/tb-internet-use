"""Open the files of one trial for the steps of the pipeline, which take text and types and never a path."""

from pathlib import Path

from tb_internet_use.tool_call.model import HarnessToolCall
from tb_internet_use.tool_call.parse_trajectory import parse_trajectory
from tb_internet_use.trial.model import (
    TrialFileTexts,
    UnreadableTrajectory,
    UnreadableTrajectoryReason,
)

_TRAJECTORY_FILE_NAME = "trajectory.json"
_DETAIL_FILE_NAME = "detail.json"
_STATUS_FILE_NAME = "status.json"


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


def read_trial_file_texts(trial_dir: Path) -> TrialFileTexts:
    """Read the detail file and the status file of one trial folder as bytes, for `collect_trials`.

    The name of the folder is the trial id. The bytes go to `collect_trials` as they are, so that its reading functions report broken UTF-8 or JSON with the trial id. A missing file raises `FileNotFoundError`.
    """
    return TrialFileTexts(
        trial_id=trial_dir.name,
        detail_text=(trial_dir / _DETAIL_FILE_NAME).read_bytes(),
        status_text=(trial_dir / _STATUS_FILE_NAME).read_bytes(),
    )
