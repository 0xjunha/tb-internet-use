"""Tests for the checks that the types of export/model.py make when they are built."""

import functools
import itertools
from collections.abc import Callable

import pytest
from made_up_network_request_rows import build_network_request_row

from tb_internet_use.export.model import (
    MeasureBound,
    NetworkRequestCategory,
    NetworkRequestSender,
    TrialCategoryMeasureRow,
    TrialRow,
    UnknownPackageRegistry,
)
from tb_internet_use.trial.model import UnreadableTrajectoryReason

LOWER_AND_UPPER = MeasureBound.LOWER_AND_UPPER
UPPER_ONLY = MeasureBound.UPPER_ONLY
NEITHER = MeasureBound.NEITHER
# The pairs of request bound and received bound in which the received bound is the stronger one, written out by hand.
RECEIVED_STRONGER_PAIRS = {
    (UPPER_ONLY, LOWER_AND_UPPER),
    (NEITHER, LOWER_AND_UPPER),
    (NEITHER, UPPER_ONLY),
}
BOUND_PAIRS = list(itertools.product(MeasureBound, MeasureBound))
build_package_row = functools.partial(
    build_network_request_row,
    NetworkRequestCategory.PACKAGE,
    NetworkRequestSender.TASK_ENVIRONMENT,
)


def build_trial_row(
    request_measure_bound: MeasureBound,
    received_measure_bound: MeasureBound,
    *,
    unreadable_trajectory_reason: UnreadableTrajectoryReason | None = None,
) -> TrialRow:
    return TrialRow(
        trial_id="t1",
        benchmark_version="4-0-0",
        task_name="terminal-bench/fix-git",
        leaderboard_row_id="row-1",
        harness="claude-code",
        harness_version="2.1.0",
        model_name="model-a",
        reward=1.0,
        unreadable_trajectory_reason=unreadable_trajectory_reason,
        any_category_request_measure_bound=request_measure_bound,
        any_category_received_measure_bound=received_measure_bound,
    )


def build_trial_category_measure_row(
    request_measure_bound: MeasureBound, received_measure_bound: MeasureBound
) -> TrialCategoryMeasureRow:
    return TrialCategoryMeasureRow(
        trial_id="t1",
        category=NetworkRequestCategory.PACKAGE,
        sender=NetworkRequestSender.TASK_ENVIRONMENT,
        request_measure_bound=request_measure_bound,
        received_measure_bound=received_measure_bound,
    )


@pytest.mark.parametrize(
    "build_row",
    [build_package_row, build_trial_row, build_trial_category_measure_row],
)
@pytest.mark.parametrize(
    ("request_measure_bound", "received_measure_bound"), BOUND_PAIRS
)
def test_rows_refuse_a_received_bound_stronger_than_the_request_bound(
    build_row: Callable[[MeasureBound, MeasureBound], object],
    request_measure_bound: MeasureBound,
    received_measure_bound: MeasureBound,
):
    if (request_measure_bound, received_measure_bound) in RECEIVED_STRONGER_PAIRS:
        with pytest.raises(ValueError):
            build_row(request_measure_bound, received_measure_bound)
    else:
        build_row(request_measure_bound, received_measure_bound)


@pytest.mark.parametrize(
    ("request_measure_bound", "received_measure_bound"), BOUND_PAIRS
)
def test_trial_row_of_an_unreadable_trajectory_counts_only_in_the_upper_bounds(
    request_measure_bound: MeasureBound, received_measure_bound: MeasureBound
):
    if (request_measure_bound, received_measure_bound) == (UPPER_ONLY, UPPER_ONLY):
        row = build_trial_row(
            request_measure_bound,
            received_measure_bound,
            unreadable_trajectory_reason=UnreadableTrajectoryReason.MISSING,
        )
        assert row.unreadable_trajectory_reason == UnreadableTrajectoryReason.MISSING
    else:
        with pytest.raises(ValueError):
            build_trial_row(
                request_measure_bound,
                received_measure_bound,
                unreadable_trajectory_reason=UnreadableTrajectoryReason.MISSING,
            )


def test_unknown_package_registry_refuses_to_be_read_as_true_or_false():
    # It stands beside None, the answer for a request that the door is not asked about.
    with pytest.raises(TypeError):
        bool(UnknownPackageRegistry())
