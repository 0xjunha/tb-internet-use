"""Export the main measure rows of one trial, saying for each category and sender in which bounds the trial has a request and has received something.

The main measure of a task is the share of its trials with at least one request of a category and the share with at least one received. One row per category and sender of a trial is what a spreadsheet counts for those shares, e.g. a trial with three `pip install` requests counts once for `package`.
"""

from collections.abc import Sequence

from tb_internet_use.export._export_trial_row import (
    check_network_request_rows_of_trial,
)
from tb_internet_use.export.model import (
    MeasureBound,
    NetworkRequestCategory,
    NetworkRequestRow,
    NetworkRequestSender,
    TrialCategoryMeasureRow,
    strongest_measure_bound_of,
    trial_received_measure_bound_of,
)
from tb_internet_use.trial.model import Trial


def export_trial_category_measure_rows(
    trial: Trial, network_request_rows: Sequence[NetworkRequestRow]
) -> tuple[TrialCategoryMeasureRow, ...]:
    """Export a `TrialCategoryMeasureRow` for each category and sender of the request rows of one trial.

    The two bounds of a row are the strongest among the request rows of its category and sender, in the order of `MEASURE_BOUNDS_FROM_STRONGEST`, since one request is enough for the trial to count.
    The received bound of a request row is `trial_received_measure_bound_of` it, so the trial is in the lower bound of received also when a row is among success line owners one of which received, e.g. `apt-get install -y a b` under one `Fetched 10 kB in 1s` that both own, where each row alone is only in the upper bound.
    A read trial without request rows gets no row, since it counts in no bound of any category.
    A trial whose trajectory could not be read gets a row for every category and every sender but `UNKNOWN`, all `UPPER_ONLY`, since its requests are not known. `UNKNOWN` marks a request whose sender is one of the three that no fact names, so it is no place of its own.
    Rows come in the order of `NetworkRequestCategory` and then of `NetworkRequestSender`.
    Request rows of another trial raise `ValueError`, and so do request rows of a trial whose trajectory could not be read.
    """
    check_network_request_rows_of_trial(trial, network_request_rows)
    if trial.unreadable_trajectory is not None:
        if network_request_rows:
            raise ValueError(
                f"trial {trial.trial_id} has an unreadable trajectory and {len(network_request_rows)} request rows"
            )
        return tuple(
            TrialCategoryMeasureRow(
                trial_id=trial.trial_id,
                category=category,
                sender=sender,
                request_measure_bound=MeasureBound.UPPER_ONLY,
                received_measure_bound=MeasureBound.UPPER_ONLY,
            )
            for category in NetworkRequestCategory
            for sender in NetworkRequestSender
            if sender != NetworkRequestSender.UNKNOWN
        )
    return tuple(
        TrialCategoryMeasureRow(
            trial_id=trial.trial_id,
            category=category,
            sender=sender,
            request_measure_bound=strongest_measure_bound_of(
                [row.request_measure_bound for row in rows_of_category_and_sender]
            ),
            received_measure_bound=strongest_measure_bound_of(
                [
                    trial_received_measure_bound_of(row)
                    for row in rows_of_category_and_sender
                ]
            ),
        )
        for category in NetworkRequestCategory
        for sender in NetworkRequestSender
        if (
            rows_of_category_and_sender := [
                row
                for row in network_request_rows
                if (row.category, row.sender) == (category, sender)
            ]
        )
    )
