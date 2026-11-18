"""Tests for the checks that the types of export/model.py make when they are built."""

import itertools
from collections.abc import Callable

import pytest

from tb_internet_use.export.model import (
    MeasureBound,
    NetworkRequestCategory,
    NetworkRequestResultView,
    NetworkRequestRow,
    NetworkRequestSender,
    NetworkRequestSourceKind,
    TrialCategoryMeasureRow,
    TrialRow,
    UnknownPackageRegistry,
)
from tb_internet_use.network_request.model import NetworkRequestCertainty
from tb_internet_use.network_request_result.model import (
    NetworkRequestResultCertainty,
    NetworkRequestResultLevel,
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


def build_network_request_row(
    request_measure_bound: MeasureBound, received_measure_bound: MeasureBound
) -> NetworkRequestRow:
    return NetworkRequestRow(
        trial_id="t1",
        trajectory_id="main",
        step_id=1,
        call_index=0,
        request_index=0,
        source_kind=NetworkRequestSourceKind.WEB_TOOL,
        source="web tool",
        made_by="WebFetch",
        target="https://a.org/x",
        unknown_target_reason=None,
        target_kind=None,
        host_names="a.org",
        received_content_destination="shown",
        request_certainty=NetworkRequestCertainty.CONFIRMED,
        request_uncertainty_reason=None,
        level=NetworkRequestResultLevel.RECEIVED,
        stop_reason=None,
        level_certainty=NetworkRequestResultCertainty.CONFIRMED,
        evidence="",
        category=NetworkRequestCategory.PAGE_READ,
        host_scope="public",
        host_service="unknown",
        package_registry="",
        is_internet_use=True,
        sender=NetworkRequestSender.UNKNOWN,
        result_view=NetworkRequestResultView.RECEIVED,
        request_measure_bound=request_measure_bound,
        received_measure_bound=received_measure_bound,
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
    [build_network_request_row, build_trial_row, build_trial_category_measure_row],
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
