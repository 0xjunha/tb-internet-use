"""Export the row of one trial, with the facts of its `Trial` and the bounds of the main measure over all categories of its requests."""

from collections.abc import Iterable, Sequence

from tb_internet_use.export.model import (
    MEASURE_BOUNDS_FROM_STRONGEST,
    MeasureBound,
    NetworkRequestRow,
    NetworkRequestSender,
    TrialRow,
)
from tb_internet_use.trial.model import Trial


def export_trial_row(
    trial: Trial, network_request_rows: Sequence[NetworkRequestRow]
) -> TrialRow:
    """Export the `TrialRow` of one trial from its `Trial` and its request rows.

    The two bounds are the strongest among the rows that the task environment sent, since the question of the tasks most affected is about turning off the internet of the task environment. They are `NEITHER` when there is no such row.
    A row whose sender is not known, e.g. a web tool without a row of the web tool catalog, may have left from the task environment, so it counts at most in the upper bound and never in the lower bound.
    A trial whose trajectory could not be read gets `UPPER_ONLY` for both, since its requests are not known.
    Request rows of another trial raise `ValueError`, since they would give this trial the bounds of that one.
    """
    other_trial_ids = sorted(
        {row.trial_id for row in network_request_rows} - {trial.trial_id}
    )
    if other_trial_ids:
        raise ValueError(
            f"request rows of trials {other_trial_ids} given for trial {trial.trial_id}"
        )
    if trial.unreadable_trajectory is None:
        unreadable_trajectory_reason = None
        request_measure_bound = _strongest_measure_bound_of(
            _task_environment_measure_bound_of(row.sender, row.request_measure_bound)
            for row in network_request_rows
        )
        received_measure_bound = _strongest_measure_bound_of(
            _task_environment_measure_bound_of(row.sender, row.received_measure_bound)
            for row in network_request_rows
        )
    else:
        unreadable_trajectory_reason = trial.unreadable_trajectory.reason
        request_measure_bound = MeasureBound.UPPER_ONLY
        received_measure_bound = MeasureBound.UPPER_ONLY
    return TrialRow(
        trial_id=trial.trial_id,
        benchmark_version=trial.benchmark_version,
        task_name=trial.task_name,
        leaderboard_row_id=trial.leaderboard_row_id,
        harness=trial.harness,
        harness_version=trial.harness_version,
        model_name=trial.model_name,
        reward=trial.reward,
        unreadable_trajectory_reason=unreadable_trajectory_reason,
        any_category_request_measure_bound=request_measure_bound,
        any_category_received_measure_bound=received_measure_bound,
    )


def _task_environment_measure_bound_of(
    sender: NetworkRequestSender, measure_bound: MeasureBound
) -> MeasureBound:
    """Give the bound in which a row counts for what the task environment sent, which is its own bound for the task environment, at most `UPPER_ONLY` for a sender that is not known and `NEITHER` for the other senders."""
    match sender:
        case NetworkRequestSender.TASK_ENVIRONMENT:
            return measure_bound
        case NetworkRequestSender.UNKNOWN:
            if measure_bound == MeasureBound.LOWER_AND_UPPER:
                return MeasureBound.UPPER_ONLY
            return measure_bound
        case (
            NetworkRequestSender.HARNESS_PROCESS | NetworkRequestSender.PROVIDER_SERVER
        ):
            return MeasureBound.NEITHER


def _strongest_measure_bound_of(measure_bounds: Iterable[MeasureBound]) -> MeasureBound:
    """Give the first of the bounds in `MEASURE_BOUNDS_FROM_STRONGEST`, and `NEITHER` for no bound."""
    return min(
        measure_bounds,
        key=MEASURE_BOUNDS_FROM_STRONGEST.index,
        default=MeasureBound.NEITHER,
    )
