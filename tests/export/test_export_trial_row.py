"""Tests for _export_trial_row.py."""

import dataclasses
from collections import Counter

import pytest

from tb_internet_use.export import _export_trial_row
from tb_internet_use.export._export_trial_row import export_trial_row
from tb_internet_use.export.judgment_rules import (
    treat_request_of_unknown_sender_as_possibly_from_task_environment,
)
from tb_internet_use.export.model import (
    MeasureBound,
    NetworkRequestCategory,
    NetworkRequestResultView,
    NetworkRequestRow,
    NetworkRequestSender,
    NetworkRequestSourceKind,
    TrialRow,
)
from tb_internet_use.network_request.model import NetworkRequestCertainty
from tb_internet_use.network_request_result.model import (
    NetworkRequestResultCertainty,
    NetworkRequestResultLevel,
)
from tb_internet_use.trial.model import (
    Trial,
    UnreadableTrajectory,
    UnreadableTrajectoryReason,
)

LOWER_AND_UPPER = MeasureBound.LOWER_AND_UPPER
UPPER_ONLY = MeasureBound.UPPER_ONLY
NEITHER = MeasureBound.NEITHER
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
TRIAL_ROW_OF_READ_TRIAL_WITHOUT_REQUESTS = TrialRow(
    trial_id="t1",
    benchmark_version="4-0-0",
    task_name="terminal-bench/fix-git",
    leaderboard_row_id="row-1",
    harness="claude-code",
    harness_version="2.1.0",
    model_name="model-a",
    reward=1.0,
    unreadable_trajectory_reason=None,
    any_category_request_measure_bound=NEITHER,
    any_category_received_measure_bound=NEITHER,
)


def build_network_request_row(
    category: NetworkRequestCategory,
    sender: NetworkRequestSender,
    request_measure_bound: MeasureBound,
    received_measure_bound: MeasureBound,
) -> NetworkRequestRow:
    return NetworkRequestRow(
        trial_id="t1",
        trajectory_id="main",
        step_id=1,
        call_index=0,
        request_index=0,
        source_kind=NetworkRequestSourceKind.COMMAND,
        source="command 0",
        made_by="curl",
        target="https://a.org/x",
        unknown_target_reason=None,
        target_kind=None,
        host_names="a.org",
        received_content_destination="saved",
        request_certainty=NetworkRequestCertainty.CONFIRMED,
        request_uncertainty_reason=None,
        level=NetworkRequestResultLevel.RECEIVED,
        stop_reason=None,
        level_certainty=NetworkRequestResultCertainty.CONFIRMED,
        evidence="",
        category=category,
        host_scope="public",
        host_service="unknown",
        package_registry="",
        is_internet_use=True,
        sender=sender,
        result_view=NetworkRequestResultView.RECEIVED,
        request_measure_bound=request_measure_bound,
        received_measure_bound=received_measure_bound,
    )


# Request rows of one trial, i.e. a confirmed receipt of a file, a receipt whose internet use is not known, a search sent from the provider server, a page read by a fetch tool of the harness and a page read by a web tool whose sender is not known.
FETCHED_FILE_ROW = build_network_request_row(
    NetworkRequestCategory.FETCHED_FILE,
    TASK_ENVIRONMENT,
    LOWER_AND_UPPER,
    LOWER_AND_UPPER,
)
PACKAGE_ROW_WITH_UNKNOWN_INTERNET_USE = build_network_request_row(
    NetworkRequestCategory.PACKAGE, TASK_ENVIRONMENT, UPPER_ONLY, UPPER_ONLY
)
SEARCH_ROW_FROM_PROVIDER_SERVER = build_network_request_row(
    NetworkRequestCategory.SEARCH, PROVIDER_SERVER, LOWER_AND_UPPER, LOWER_AND_UPPER
)
PAGE_READ_ROW_FROM_HARNESS_PROCESS = build_network_request_row(
    NetworkRequestCategory.PAGE_READ, HARNESS_PROCESS, LOWER_AND_UPPER, LOWER_AND_UPPER
)
PAGE_READ_ROW_FROM_UNKNOWN_SENDER = build_network_request_row(
    NetworkRequestCategory.PAGE_READ, UNKNOWN_SENDER, LOWER_AND_UPPER, LOWER_AND_UPPER
)


def test_trial_row_of_a_read_trial_without_requests_copies_the_trial_and_counts_in_no_bound():
    assert (
        export_trial_row(READ_TRIAL, (), judgment_rule_use_counts=Counter())
        == TRIAL_ROW_OF_READ_TRIAL_WITHOUT_REQUESTS
    )


def test_trial_row_keeps_a_missing_reward():
    trial = dataclasses.replace(READ_TRIAL, reward=None)

    assert (
        export_trial_row(trial, (), judgment_rule_use_counts=Counter()).reward is None
    )


@pytest.mark.parametrize("reason", list(UnreadableTrajectoryReason))
def test_trial_row_of_an_unreadable_trajectory_keeps_the_reason_and_counts_only_in_the_upper_bounds(
    reason: UnreadableTrajectoryReason,
):
    trial = dataclasses.replace(
        READ_TRIAL, unreadable_trajectory=UnreadableTrajectory(reason)
    )

    assert export_trial_row(
        trial, (), judgment_rule_use_counts=Counter()
    ) == dataclasses.replace(
        TRIAL_ROW_OF_READ_TRIAL_WITHOUT_REQUESTS,
        unreadable_trajectory_reason=reason,
        any_category_request_measure_bound=UPPER_ONLY,
        any_category_received_measure_bound=UPPER_ONLY,
    )


@pytest.mark.parametrize(
    ("network_request_rows", "request_measure_bound", "received_measure_bound"),
    [
        # The strongest row of the task environment gives both bounds.
        (
            (
                PACKAGE_ROW_WITH_UNKNOWN_INTERNET_USE,
                FETCHED_FILE_ROW,
                SEARCH_ROW_FROM_PROVIDER_SERVER,
            ),
            LOWER_AND_UPPER,
            LOWER_AND_UPPER,
        ),
        # A row from the provider server counts in no bound of the trial row, however strong it is.
        (
            (PACKAGE_ROW_WITH_UNKNOWN_INTERNET_USE, SEARCH_ROW_FROM_PROVIDER_SERVER),
            UPPER_ONLY,
            UPPER_ONLY,
        ),
        ((SEARCH_ROW_FROM_PROVIDER_SERVER,), NEITHER, NEITHER),
        ((PAGE_READ_ROW_FROM_HARNESS_PROCESS,), NEITHER, NEITHER),
        # A row whose sender is not known may have left from the task environment, so it counts in the upper bounds and never in the lower bounds.
        ((PAGE_READ_ROW_FROM_UNKNOWN_SENDER,), UPPER_ONLY, UPPER_ONLY),
        (
            (
                build_network_request_row(
                    NetworkRequestCategory.PAGE_READ, UNKNOWN_SENDER, NEITHER, NEITHER
                ),
            ),
            NEITHER,
            NEITHER,
        ),
        (
            (
                build_network_request_row(
                    NetworkRequestCategory.PAGE_READ,
                    UNKNOWN_SENDER,
                    LOWER_AND_UPPER,
                    UPPER_ONLY,
                ),
            ),
            UPPER_ONLY,
            UPPER_ONLY,
        ),
        # The strongest row of the task environment wins wherever it stands.
        (
            (
                PAGE_READ_ROW_FROM_UNKNOWN_SENDER,
                PACKAGE_ROW_WITH_UNKNOWN_INTERNET_USE,
                FETCHED_FILE_ROW,
            ),
            LOWER_AND_UPPER,
            LOWER_AND_UPPER,
        ),
        # The two bounds are taken apart, e.g. a confirmed request whose receipt is not known.
        (
            (
                build_network_request_row(
                    NetworkRequestCategory.FETCHED_FILE,
                    TASK_ENVIRONMENT,
                    LOWER_AND_UPPER,
                    UPPER_ONLY,
                ),
                build_network_request_row(
                    NetworkRequestCategory.PACKAGE, TASK_ENVIRONMENT, NEITHER, NEITHER
                ),
            ),
            LOWER_AND_UPPER,
            UPPER_ONLY,
        ),
    ],
)
def test_trial_row_takes_the_strongest_bounds_among_the_rows_of_the_task_environment(
    network_request_rows: tuple[NetworkRequestRow, ...],
    request_measure_bound: MeasureBound,
    received_measure_bound: MeasureBound,
):
    trial_row = export_trial_row(
        READ_TRIAL, network_request_rows, judgment_rule_use_counts=Counter()
    )

    assert (
        trial_row.any_category_request_measure_bound,
        trial_row.any_category_received_measure_bound,
    ) == (request_measure_bound, received_measure_bound)


def test_trial_row_refuses_request_rows_of_another_trial():
    row_of_another_trial = dataclasses.replace(FETCHED_FILE_ROW, trial_id="t2")

    with pytest.raises(ValueError):
        export_trial_row(
            READ_TRIAL,
            (FETCHED_FILE_ROW, row_of_another_trial),
            judgment_rule_use_counts=Counter(),
        )


UNKNOWN_SENDER_RULE = (
    treat_request_of_unknown_sender_as_possibly_from_task_environment.__name__
)


def test_trial_row_asks_the_unknown_sender_rule_once_for_each_row_whose_sender_is_not_known():
    judgment_rule_use_counts: Counter[str] = Counter()

    export_trial_row(
        READ_TRIAL,
        (
            PAGE_READ_ROW_FROM_UNKNOWN_SENDER,
            FETCHED_FILE_ROW,
            SEARCH_ROW_FROM_PROVIDER_SERVER,
            PAGE_READ_ROW_FROM_UNKNOWN_SENDER,
        ),
        judgment_rule_use_counts=judgment_rule_use_counts,
    )

    assert judgment_rule_use_counts == Counter({UNKNOWN_SENDER_RULE: 2})


def test_trial_row_leaves_out_a_row_whose_sender_is_not_known_when_the_unknown_sender_rule_answers_false(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        _export_trial_row,
        UNKNOWN_SENDER_RULE,
        lambda network_request_row, *, use_counts: False,
    )

    trial_row = export_trial_row(
        READ_TRIAL,
        (PAGE_READ_ROW_FROM_UNKNOWN_SENDER,),
        judgment_rule_use_counts=Counter(),
    )

    assert (
        trial_row.any_category_request_measure_bound,
        trial_row.any_category_received_measure_bound,
    ) == (NEITHER, NEITHER)
