"""Export the row of one trial, with the facts of its `Trial` and the bounds of the main measure over all categories of its requests."""

from collections import Counter
from collections.abc import Iterable, Sequence

from tb_internet_use.export.judgment_rules import (
    treat_request_of_unknown_sender_as_possibly_from_task_environment,
)
from tb_internet_use.export.model import (
    MEASURE_BOUNDS_FROM_STRONGEST,
    MeasureBound,
    NetworkRequestRow,
    NetworkRequestSender,
    TrialRow,
)
from tb_internet_use.trial.model import Trial


def export_trial_row(
    trial: Trial,
    network_request_rows: Sequence[NetworkRequestRow],
    *,
    judgment_rule_use_counts: Counter[str],
) -> TrialRow:
    """Export the `TrialRow` of one trial from its `Trial` and its request rows.

    The two bounds are the strongest among the rows that the task environment sent, since the question of the tasks most affected is about turning off the internet of the task environment. They are `NEITHER` when there is no such row.
    A row whose sender is not known, e.g. a web tool without a row of the web tool catalog, counts as `treat_request_of_unknown_sender_as_possibly_from_task_environment` says, which it is asked once for each such row.
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
        task_environment_measure_bounds = [
            _task_environment_measure_bounds_of(
                row, judgment_rule_use_counts=judgment_rule_use_counts
            )
            for row in network_request_rows
        ]
        request_measure_bound = _strongest_measure_bound_of(
            request_measure_bound
            for request_measure_bound, _ in task_environment_measure_bounds
        )
        received_measure_bound = _strongest_measure_bound_of(
            received_measure_bound
            for _, received_measure_bound in task_environment_measure_bounds
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


def _task_environment_measure_bounds_of(
    network_request_row: NetworkRequestRow, *, judgment_rule_use_counts: Counter[str]
) -> tuple[MeasureBound, MeasureBound]:
    """Give the request bound and the received bound in which a row counts for what the task environment sent, which are its own bounds for the task environment and `NEITHER` for the other senders.

    For a sender that is not known, `treat_request_of_unknown_sender_as_possibly_from_task_environment` keeps its bounds with `LOWER_AND_UPPER` lowered to `UPPER_ONLY`, or gives `NEITHER`.
    """
    request_measure_bound = network_request_row.request_measure_bound
    received_measure_bound = network_request_row.received_measure_bound
    match network_request_row.sender:
        case NetworkRequestSender.TASK_ENVIRONMENT:
            return request_measure_bound, received_measure_bound
        case NetworkRequestSender.UNKNOWN:
            if treat_request_of_unknown_sender_as_possibly_from_task_environment(
                network_request_row, use_counts=judgment_rule_use_counts
            ):
                return (
                    _measure_bound_capped_at_upper_only_of(request_measure_bound),
                    _measure_bound_capped_at_upper_only_of(received_measure_bound),
                )
            return MeasureBound.NEITHER, MeasureBound.NEITHER
        case (
            NetworkRequestSender.HARNESS_PROCESS | NetworkRequestSender.PROVIDER_SERVER
        ):
            return MeasureBound.NEITHER, MeasureBound.NEITHER


def _measure_bound_capped_at_upper_only_of(measure_bound: MeasureBound) -> MeasureBound:
    """Give `UPPER_ONLY` for `LOWER_AND_UPPER` and the bound itself otherwise."""
    if measure_bound == MeasureBound.LOWER_AND_UPPER:
        return MeasureBound.UPPER_ONLY
    return measure_bound


def _strongest_measure_bound_of(measure_bounds: Iterable[MeasureBound]) -> MeasureBound:
    """Give the first of the bounds in `MEASURE_BOUNDS_FROM_STRONGEST`, and `NEITHER` for no bound."""
    return min(
        measure_bounds,
        key=MEASURE_BOUNDS_FROM_STRONGEST.index,
        default=MeasureBound.NEITHER,
    )
