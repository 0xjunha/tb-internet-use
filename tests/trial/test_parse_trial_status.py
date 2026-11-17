"""Tests for parse_trial_status.py."""

import json
from typing import Any

import pytest

from tb_internet_use.trial.parse_trial_status import parse_trial_status


def _assert_raises_with_the_trial_id(status_file_contents: Any) -> None:
    with pytest.raises(ValueError) as error:
        parse_trial_status(json.dumps(status_file_contents), "t1")

    assert error.value.__notes__ == ["trial_id: t1"]


@pytest.mark.parametrize(
    "memberships",
    [
        pytest.param(
            [
                {"version": "4-0-0", "row_id": "row-1"},
                {"version": "3-0-0", "row_id": "row-2"},
            ],
            id="two leaderboard rows",
        ),
        pytest.param([], id="no leaderboard row"),
    ],
)
def test_status_without_exactly_one_leaderboard_row_raises_with_the_trial_id(
    memberships,
):
    _assert_raises_with_the_trial_id({"memberships": memberships})


@pytest.mark.parametrize(
    "status_file_contents",
    [
        pytest.param({}, id="no memberships"),
        pytest.param({"memberships": [{"row_id": "row-1"}]}, id="no version"),
        pytest.param({"memberships": [{"version": "4-0-0"}]}, id="no row_id"),
        pytest.param(
            {"memberships": [{"version": 4, "row_id": "row-1"}]},
            id="version that is no text",
        ),
        pytest.param(
            {"memberships": [{"version": "4-0-0", "row_id": 1}]},
            id="row_id that is no text",
        ),
    ],
)
def test_status_without_a_text_version_and_row_id_raises_with_the_trial_id(
    status_file_contents,
):
    _assert_raises_with_the_trial_id(status_file_contents)


def test_broken_json_raises_with_the_trial_id():
    with pytest.raises(ValueError) as error:
        parse_trial_status('{"memberships":', "t1")

    assert error.value.__notes__ == ["trial_id: t1"]
