"""Tests for _export_rows.py."""

import dataclasses
from collections import Counter

import pytest

from tb_internet_use.export import export_rows
from tb_internet_use.export.model import MeasureBound
from tb_internet_use.network_request.model import (
    ContentShownInResult,
    FromWebTool,
    NetworkRequest,
    NetworkRequestCertainty,
    NetworkRequestTargetKind,
)
from tb_internet_use.network_request_result.model import (
    NetworkRequestResult,
    NetworkRequestResultCertainty,
    NetworkRequestResultLevel,
    NetworkRequestResultStopReason,
)
from tb_internet_use.tool_call.model import HarnessTool, ToolCallKey
from tb_internet_use.trial.model import (
    Trial,
    UnreadableTrajectory,
    UnreadableTrajectoryReason,
)

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
NETWORK_REQUEST_RESULT = NetworkRequestResult(
    network_request=NetworkRequest(
        tool_call_key=ToolCallKey("t1", "main", 1, 0),
        index_in_tool_call=0,
        source=FromWebTool(None, HarnessTool("claude-code", "WebFetch")),
        target="https://a.org/x",
        target_kind=NetworkRequestTargetKind.URL,
        host_names=("a.org",),
        received_content_destination=ContentShownInResult(),
        certainty=NetworkRequestCertainty.CONFIRMED,
        uncertainty_reason=None,
    ),
    request_certainty_after_evidence=NetworkRequestCertainty.CONFIRMED,
    level=NetworkRequestResultLevel.ATTEMPTED,
    stop_reason=NetworkRequestResultStopReason.NOT_VISIBLE,
    level_certainty=NetworkRequestResultCertainty.CONFIRMED,
    evidence=(),
)


def exported_rows_of(
    trial: Trial, network_request_results: tuple[NetworkRequestResult, ...]
):
    # These trials ask the door nothing, so None stands in for it.
    return export_rows(
        trial,
        network_request_results,
        knowledge=None,  # pyright: ignore[reportArgumentType]
        judgment_rule_use_counts=Counter(),
    )


def test_read_trial_without_results_has_a_trial_row_and_no_other_rows():
    trial_row, network_request_rows, trial_category_measure_rows = exported_rows_of(
        READ_TRIAL, ()
    )

    assert trial_row.trial_id == "t1"
    assert trial_row.unreadable_trajectory_reason is None
    assert trial_row.any_category_request_measure_bound == MeasureBound.NEITHER
    assert trial_row.any_category_received_measure_bound == MeasureBound.NEITHER
    assert network_request_rows == ()
    assert trial_category_measure_rows == ()


def test_unreadable_trial_with_a_result_is_refused():
    trial = dataclasses.replace(
        READ_TRIAL,
        unreadable_trajectory=UnreadableTrajectory(UnreadableTrajectoryReason.MISSING),
    )

    with pytest.raises(ValueError):
        exported_rows_of(trial, (NETWORK_REQUEST_RESULT,))


@pytest.mark.parametrize(
    ("unreadable_trajectory", "network_request_results"),
    [
        # A read trial with results, whose request rows and main measure rows `export_rows` does not export.
        (None, (NETWORK_REQUEST_RESULT,)),
        # An unreadable trial, which needs a main measure row in the upper bound for every category and sender.
        (UnreadableTrajectory(UnreadableTrajectoryReason.MISSING), ()),
    ],
)
def test_trial_that_needs_request_rows_or_main_measure_rows_raises_instead_of_getting_rows_without_them(
    unreadable_trajectory: UnreadableTrajectory | None,
    network_request_results: tuple[NetworkRequestResult, ...],
):
    trial = dataclasses.replace(READ_TRIAL, unreadable_trajectory=unreadable_trajectory)

    with pytest.raises(NotImplementedError):
        exported_rows_of(trial, network_request_results)
