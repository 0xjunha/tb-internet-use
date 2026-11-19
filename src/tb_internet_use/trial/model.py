"""Record types for the trials of a collection, giving each trial the task, harness and reward that the rows of its network requests are grouped by.

A trial without requests still counts in the share of trials of a task that have one, so every trial has a `Trial`, also when its trajectory could not be read.
"""

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class Trial:
    """Record of one trial of a leaderboard run, made by `collect_trials` and read by `export_rows` to write its `TrialRow`."""

    # The name of the trial folder. The keys of the trial's tool calls carry the same id.
    trial_id: str
    # The benchmark version of the leaderboard that the trial belongs to, as the status file writes it, e.g. `4-0-0`.
    # A task is named by this and `task_name` together, since one task name occurs in two benchmark versions.
    benchmark_version: str
    # The task name as the detail file writes it, e.g. `terminal-bench/<name>`.
    task_name: str
    # The leaderboard row that the trial belongs to. One row is one run of a harness with one model and its settings over every task.
    leaderboard_row_id: str
    # The agent name of the detail file, e.g. `claude-code`.
    harness: str
    # The agent version of the detail file. The check that one leaderboard row ran every task with one harness version reads it.
    harness_version: str
    model_name: str
    # None when the detail file has no verifier result.
    reward: float | None
    # None when the trajectory file could be read, also when it holds no tool call.
    # A trial that has one has no requests in the output, which does not mean that it made none.
    unreadable_trajectory: UnreadableTrajectory | None


@dataclass(frozen=True, slots=True)
class TrialFileTexts:
    """Texts of the two files of one trial folder as `pipeline.py` read them, taken by `collect_trials` since a step takes text and never a path."""

    # The name of the trial folder.
    trial_id: str
    detail_text: str | bytes
    status_text: str | bytes


@dataclass(frozen=True, slots=True)
class TrialDetail:
    """Values of one trial's detail file that a `Trial` holds, returned by `parse_trial_detail`."""

    task_name: str
    harness: str
    harness_version: str
    model_name: str
    reward: float | None  # None when the file has no verifier result


@dataclass(frozen=True, slots=True)
class TrialLeaderboardMembership:
    """Leaderboard row that one trial belongs to, returned by `parse_trial_status`."""

    benchmark_version: str
    leaderboard_row_id: str


@dataclass(frozen=True, slots=True)
class UnreadableTrajectory:
    """Result of reading a trial whose trajectory file could not be read, returned in place of its tool calls so that the trial is not taken for one without calls.

    It sits here and not beside `parse_trajectory`, which returns it, since a `Trial` holds it and a step never imports from a later step.
    """

    reason: UnreadableTrajectoryReason


class UnreadableTrajectoryReason(StrEnum):
    """Reason a trial's trajectory could not be read."""

    MISSING = "missing"  # the trial folder has no trajectory file
    INVALID_JSON = "invalid_json"  # the file holds broken JSON or broken UTF-8
