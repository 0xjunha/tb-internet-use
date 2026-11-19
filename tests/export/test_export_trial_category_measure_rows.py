"""Tests for _export_trial_category_measure_rows.py."""

import dataclasses
import itertools

import pytest
from made_up_network_request_rows import build_network_request_row

from tb_internet_use.export._export_trial_category_measure_rows import (
    export_trial_category_measure_rows,
)
from tb_internet_use.export.model import (
    MeasureBound,
    NetworkRequestCategory,
    NetworkRequestRow,
    NetworkRequestSender,
    TrialCategoryMeasureRow,
)
from tb_internet_use.trial.model import (
    Trial,
    UnreadableTrajectory,
    UnreadableTrajectoryReason,
)

LOWER_AND_UPPER = MeasureBound.LOWER_AND_UPPER
UPPER_ONLY = MeasureBound.UPPER_ONLY
NEITHER = MeasureBound.NEITHER
PACKAGE = NetworkRequestCategory.PACKAGE
FETCHED_FILE = NetworkRequestCategory.FETCHED_FILE
SEARCH = NetworkRequestCategory.SEARCH
PAGE_READ = NetworkRequestCategory.PAGE_READ
TASK_ENVIRONMENT = NetworkRequestSender.TASK_ENVIRONMENT
HARNESS_PROCESS = NetworkRequestSender.HARNESS_PROCESS
PROVIDER_SERVER = NetworkRequestSender.PROVIDER_SERVER
UNKNOWN_SENDER = NetworkRequestSender.UNKNOWN
READ_TRIAL = Trial(
    "t1",
    "4-0-0",
    "terminal-bench/fix-git",
    "row-1",
    "claude-code",
    "2.1.0",
    "model-a",
    1.0,
    None,
)
UNREADABLE_TRIAL = dataclasses.replace(
    READ_TRIAL,
    unreadable_trajectory=UnreadableTrajectory(UnreadableTrajectoryReason.MISSING),
)
# The pairs of request bound and received bound that a request row can hold, since a received bound is never stronger than the request bound.
ROW_MEASURE_BOUND_PAIRS = (
    (LOWER_AND_UPPER, LOWER_AND_UPPER),
    (LOWER_AND_UPPER, UPPER_ONLY),
    (LOWER_AND_UPPER, NEITHER),
    (UPPER_ONLY, UPPER_ONLY),
    (UPPER_ONLY, NEITHER),
    (NEITHER, NEITHER),
)


def measure_row(
    category: NetworkRequestCategory,
    sender: NetworkRequestSender,
    request_measure_bound: MeasureBound,
    received_measure_bound: MeasureBound,
) -> TrialCategoryMeasureRow:
    return TrialCategoryMeasureRow(
        trial_id="t1",
        category=category,
        sender=sender,
        request_measure_bound=request_measure_bound,
        received_measure_bound=received_measure_bound,
    )


# Request rows of the made-up results, e.g. a confirmed receipt of a file, a received package whose internet use is not known, and a `pip install` whose `pip: command not found` confirms that it did not receive.
FETCHED_FILE_ROW_RECEIVED = build_network_request_row(
    FETCHED_FILE, TASK_ENVIRONMENT, LOWER_AND_UPPER, LOWER_AND_UPPER
)
PACKAGE_ROW_WITH_UNKNOWN_INTERNET_USE = build_network_request_row(
    PACKAGE, TASK_ENVIRONMENT, UPPER_ONLY, UPPER_ONLY
)
SEARCH_ROW_FROM_PROVIDER_SERVER = build_network_request_row(
    SEARCH, PROVIDER_SERVER, LOWER_AND_UPPER, LOWER_AND_UPPER
)
PACKAGE_ROW_FAILED_TO_RUN = build_network_request_row(
    PACKAGE, TASK_ENVIRONMENT, LOWER_AND_UPPER, NEITHER
)
PACKAGE_ROW_UNCERTAIN = build_network_request_row(
    PACKAGE, TASK_ENVIRONMENT, UPPER_ONLY, UPPER_ONLY
)
PACKAGE_ROW_NOT_INTERNET_USE = build_network_request_row(
    PACKAGE, TASK_ENVIRONMENT, NEITHER, NEITHER
)


def test_a_read_trial_without_request_rows_gets_no_row():
    assert export_trial_category_measure_rows(READ_TRIAL, ()) == ()


@pytest.mark.parametrize("reason", list(UnreadableTrajectoryReason))
def test_an_unreadable_trial_gets_an_upper_only_row_for_every_category_and_every_known_sender(
    reason: UnreadableTrajectoryReason,
):
    trial = dataclasses.replace(
        READ_TRIAL, unreadable_trajectory=UnreadableTrajectory(reason)
    )

    # 24 rows, by category first and then by sender.
    assert export_trial_category_measure_rows(trial, ()) == tuple(
        measure_row(category, sender, UPPER_ONLY, UPPER_ONLY)
        for category in NetworkRequestCategory
        for sender in (TASK_ENVIRONMENT, HARNESS_PROCESS, PROVIDER_SERVER)
    )


def test_rows_come_one_per_category_and_sender_in_the_order_of_the_enums():
    # A page read by the task environment comes after the search of the provider server, since rows go by category first.
    page_read_row = build_network_request_row(
        PAGE_READ, TASK_ENVIRONMENT, UPPER_ONLY, NEITHER
    )

    assert export_trial_category_measure_rows(
        READ_TRIAL,
        (
            FETCHED_FILE_ROW_RECEIVED,
            page_read_row,
            PACKAGE_ROW_WITH_UNKNOWN_INTERNET_USE,
            SEARCH_ROW_FROM_PROVIDER_SERVER,
        ),
    ) == (
        measure_row(PACKAGE, TASK_ENVIRONMENT, UPPER_ONLY, UPPER_ONLY),
        measure_row(FETCHED_FILE, TASK_ENVIRONMENT, LOWER_AND_UPPER, LOWER_AND_UPPER),
        measure_row(SEARCH, PROVIDER_SERVER, LOWER_AND_UPPER, LOWER_AND_UPPER),
        measure_row(PAGE_READ, TASK_ENVIRONMENT, UPPER_ONLY, NEITHER),
    )


@pytest.mark.parametrize(
    ("network_request_rows", "request_measure_bound", "received_measure_bound"),
    [
        # A confirmed request that did not receive and a request that is no internet use.
        (
            (PACKAGE_ROW_FAILED_TO_RUN, PACKAGE_ROW_NOT_INTERNET_USE),
            LOWER_AND_UPPER,
            NEITHER,
        ),
        # An uncertain request and a request that is no internet use.
        ((PACKAGE_ROW_UNCERTAIN, PACKAGE_ROW_NOT_INTERNET_USE), UPPER_ONLY, UPPER_ONLY),
        # An upper-only request before a confirmed one, whose receipt is assumed.
        (
            (
                PACKAGE_ROW_UNCERTAIN,
                build_network_request_row(
                    PACKAGE, TASK_ENVIRONMENT, LOWER_AND_UPPER, UPPER_ONLY
                ),
            ),
            LOWER_AND_UPPER,
            UPPER_ONLY,
        ),
        # A confirmed request that did not receive before an uncertain one that may have, so each bound comes from another row.
        (
            (PACKAGE_ROW_FAILED_TO_RUN, PACKAGE_ROW_UNCERTAIN),
            LOWER_AND_UPPER,
            UPPER_ONLY,
        ),
    ],
)
def test_the_row_of_a_category_and_sender_takes_the_strongest_bounds_of_its_request_rows(
    network_request_rows: tuple[NetworkRequestRow, ...],
    request_measure_bound: MeasureBound,
    received_measure_bound: MeasureBound,
):
    assert export_trial_category_measure_rows(READ_TRIAL, network_request_rows) == (
        measure_row(
            PACKAGE, TASK_ENVIRONMENT, request_measure_bound, received_measure_bound
        ),
    )


def test_a_sender_that_is_not_known_gets_its_own_row_with_the_bounds_of_its_requests():
    assert export_trial_category_measure_rows(
        READ_TRIAL,
        (
            build_network_request_row(
                PAGE_READ, UNKNOWN_SENDER, LOWER_AND_UPPER, LOWER_AND_UPPER
            ),
            build_network_request_row(PAGE_READ, TASK_ENVIRONMENT, NEITHER, NEITHER),
        ),
    ) == (
        measure_row(PAGE_READ, TASK_ENVIRONMENT, NEITHER, NEITHER),
        measure_row(PAGE_READ, UNKNOWN_SENDER, LOWER_AND_UPPER, LOWER_AND_UPPER),
    )


@pytest.mark.parametrize(
    "measure_bound_pairs",
    [
        pairs
        for row_count in (1, 2, 3)
        for pairs in itertools.combinations_with_replacement(
            ROW_MEASURE_BOUND_PAIRS, row_count
        )
    ],
)
def test_bounds_follow_the_rows_and_received_never_passes_the_request(
    measure_bound_pairs: tuple[tuple[MeasureBound, MeasureBound], ...],
):
    (trial_category_measure_row,) = export_trial_category_measure_rows(
        READ_TRIAL,
        [
            build_network_request_row(PACKAGE, TASK_ENVIRONMENT, request, received)
            for request, received in measure_bound_pairs
        ],
    )

    # The trial counts in a bound when at least one row counts in it, so a single upper-only row gives an upper-only row and a single row in neither bound still gives a row in neither.
    request_bounds = {request for request, _ in measure_bound_pairs}
    received_bounds = {received for _, received in measure_bound_pairs}
    is_request_lower = LOWER_AND_UPPER in request_bounds
    is_request_upper = bool(request_bounds & {LOWER_AND_UPPER, UPPER_ONLY})
    is_received_lower = LOWER_AND_UPPER in received_bounds
    is_received_upper = bool(received_bounds & {LOWER_AND_UPPER, UPPER_ONLY})
    request_measure_bound = trial_category_measure_row.request_measure_bound
    received_measure_bound = trial_category_measure_row.received_measure_bound
    assert (request_measure_bound == LOWER_AND_UPPER) == is_request_lower
    assert (request_measure_bound != NEITHER) == is_request_upper
    assert (received_measure_bound == LOWER_AND_UPPER) == is_received_lower
    assert (received_measure_bound != NEITHER) == is_received_upper
    assert not (
        received_measure_bound == LOWER_AND_UPPER
        and request_measure_bound != LOWER_AND_UPPER
    )
    assert not (received_measure_bound != NEITHER and request_measure_bound == NEITHER)


@pytest.mark.parametrize(
    ("trial", "network_request_rows"),
    [
        (
            READ_TRIAL,
            (
                FETCHED_FILE_ROW_RECEIVED,
                dataclasses.replace(FETCHED_FILE_ROW_RECEIVED, trial_id="t2"),
            ),
        ),
        (UNREADABLE_TRIAL, (FETCHED_FILE_ROW_RECEIVED,)),
    ],
)
def test_request_rows_of_another_trial_or_of_an_unreadable_trial_raise(
    trial: Trial, network_request_rows: tuple[NetworkRequestRow, ...]
):
    with pytest.raises(ValueError):
        export_trial_category_measure_rows(trial, network_request_rows)


@pytest.mark.parametrize("sender", [TASK_ENVIRONMENT, PROVIDER_SERVER, UNKNOWN_SENDER])
def test_a_row_received_by_one_of_its_line_owners_puts_its_own_category_and_sender_in_the_lower_bound_of_received(
    sender: NetworkRequestSender,
):
    marked_row = build_network_request_row(
        PACKAGE,
        sender,
        LOWER_AND_UPPER,
        UPPER_ONLY,
        is_among_success_line_owners_one_of_which_received=True,
    )
    unmarked_row = build_network_request_row(
        FETCHED_FILE, sender, LOWER_AND_UPPER, UPPER_ONLY
    )

    assert export_trial_category_measure_rows(
        READ_TRIAL, [marked_row, unmarked_row]
    ) == (
        measure_row(PACKAGE, sender, LOWER_AND_UPPER, LOWER_AND_UPPER),
        measure_row(FETCHED_FILE, sender, LOWER_AND_UPPER, UPPER_ONLY),
    )
