"""Collect a `Trial` for each trial folder from the texts of its detail and status files and from whether its trajectory could be read."""

from collections.abc import Iterable, Mapping

from tb_internet_use.trial.model import Trial, TrialFileTexts, UnreadableTrajectory
from tb_internet_use.trial.parse_trial_detail import parse_trial_detail
from tb_internet_use.trial.parse_trial_status import parse_trial_status


def collect_trials(
    trial_file_texts: Iterable[TrialFileTexts],
    unreadable_trajectories: Mapping[str, UnreadableTrajectory],
) -> tuple[Trial, ...]:
    """Collect one `Trial` for each trial, in the order the file texts come.

    Every trial gets one, so that a trial without requests still counts in the share of trials of its task that have one.
    `unreadable_trajectories` holds by trial id the `UnreadableTrajectory` of each trial whose trajectory file could not be read, so a trial missing from it gets `None` in `Trial.unreadable_trajectory`.
    The caller reads the trajectory file of every trial before it calls this, since a trial it did not read would get `None` too.
    """
    return tuple(
        collect_one_trial(
            one_trial_file_texts,
            unreadable_trajectories.get(one_trial_file_texts.trial_id),
        )
        for one_trial_file_texts in trial_file_texts
    )


def collect_one_trial(
    trial_file_texts: TrialFileTexts,
    unreadable_trajectory: UnreadableTrajectory | None,
) -> Trial:
    """Collect the `Trial` of one trial from what its detail and status files write and from why its trajectory could not be read, if it could not."""
    trial_id = trial_file_texts.trial_id
    trial_detail = parse_trial_detail(trial_file_texts.detail_text, trial_id)
    trial_leaderboard_membership = parse_trial_status(
        trial_file_texts.status_text, trial_id
    )
    return Trial(
        trial_id=trial_id,
        benchmark_version=trial_leaderboard_membership.benchmark_version,
        task_name=trial_detail.task_name,
        leaderboard_row_id=trial_leaderboard_membership.leaderboard_row_id,
        harness=trial_detail.harness,
        harness_version=trial_detail.harness_version,
        model_name=trial_detail.model_name,
        reward=trial_detail.reward,
        unreadable_trajectory=unreadable_trajectory,
    )
