"""Collect a `Trial` for each trial folder from the texts of its detail and status files."""

from collections.abc import Iterable

from tb_internet_use.trial.model import Trial, TrialFileTexts
from tb_internet_use.trial.parse_trial_detail import parse_trial_detail
from tb_internet_use.trial.parse_trial_status import parse_trial_status


def collect_trials(trial_file_texts: Iterable[TrialFileTexts]) -> tuple[Trial, ...]:
    """Collect one `Trial` for each trial, in the order the file texts come.

    Every trial gets one, so that a trial without requests still counts in the share of trials of its task that have one.
    """
    return tuple(
        collect_one_trial(one_trial_file_texts)
        for one_trial_file_texts in trial_file_texts
    )


def collect_one_trial(trial_file_texts: TrialFileTexts) -> Trial:
    """Collect the `Trial` of one trial from what its detail and status files write."""
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
    )
