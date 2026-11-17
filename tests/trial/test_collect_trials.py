"""Tests for _collect_trials.py."""

import dataclasses
import json
from typing import Any

import pytest

from tb_internet_use.trial import collect_trials
from tb_internet_use.trial._collect_trials import collect_one_trial
from tb_internet_use.trial.model import Trial, TrialFileTexts

TRIAL_OF_THE_FIXTURES = Trial(
    "t1",
    "4-0-0",
    "terminal-bench/fix-git",
    "row-1",
    "claude-code",
    "2.1.0",
    "model-a",
    1.0,
)
TRIAL_OF_THE_FIXTURES_WITHOUT_A_REWARD = dataclasses.replace(
    TRIAL_OF_THE_FIXTURES, reward=None
)


def _trial_file_texts_from(
    detail_file_contents: dict[str, Any],
    status_file_contents: dict[str, Any],
    trial_id: str = "t1",
) -> TrialFileTexts:
    # Bytes, as `pipeline.py` reads the files.
    return TrialFileTexts(
        trial_id,
        json.dumps(detail_file_contents).encode(),
        json.dumps(status_file_contents).encode(),
    )


def test_collects_every_field_from_the_detail_and_status_files(
    detail_file_contents, status_file_contents
):
    assert (
        collect_one_trial(
            _trial_file_texts_from(detail_file_contents, status_file_contents)
        )
        == TRIAL_OF_THE_FIXTURES
    )


def test_trial_that_ended_with_an_error_without_a_verifier_result_has_no_reward(
    detail_file_contents, status_file_contents
):
    detail_file_contents["verifier_result"] = None
    detail_file_contents["exception_info"] = {"exception_type": "AgentTimeoutError"}

    assert (
        collect_one_trial(
            _trial_file_texts_from(detail_file_contents, status_file_contents)
        )
        == TRIAL_OF_THE_FIXTURES_WITHOUT_A_REWARD
    )


def test_trial_without_a_verifier_result_or_an_error_has_no_reward(
    detail_file_contents, status_file_contents
):
    detail_file_contents["verifier_result"] = None

    assert (
        collect_one_trial(
            _trial_file_texts_from(detail_file_contents, status_file_contents)
        )
        == TRIAL_OF_THE_FIXTURES_WITHOUT_A_REWARD
    )


def test_trial_that_ended_with_an_error_keeps_the_reward_of_its_verifier(
    detail_file_contents, status_file_contents
):
    detail_file_contents["exception_info"] = {"exception_type": "VerifierTimeoutError"}

    assert (
        collect_one_trial(
            _trial_file_texts_from(detail_file_contents, status_file_contents)
        )
        == TRIAL_OF_THE_FIXTURES
    )


def test_tells_two_benchmark_versions_of_one_task_apart(
    detail_file_contents, status_file_contents
):
    status_file_contents["memberships"] = [{"version": "3-0-0", "row_id": "row-2"}]

    assert collect_one_trial(
        _trial_file_texts_from(detail_file_contents, status_file_contents)
    ) == dataclasses.replace(
        TRIAL_OF_THE_FIXTURES, benchmark_version="3-0-0", leaderboard_row_id="row-2"
    )


def test_collects_each_trial_from_its_own_files_in_the_order_of_their_texts(
    detail_file_contents, status_file_contents
):
    other_detail_file_contents = {
        "task_name": "terminal-bench/build-cython",
        "agent_info": {
            "name": "codex",
            "version": "0.5.0",
            "model_info": {"name": "model-b"},
        },
        "verifier_result": {"rewards": {"reward": 0}},
        "exception_info": None,
    }
    other_status_file_contents = {
        "memberships": [{"version": "3-0-0", "row_id": "row-2"}]
    }

    trials = collect_trials(
        [
            _trial_file_texts_from(
                other_detail_file_contents, other_status_file_contents, "t2"
            ),
            _trial_file_texts_from(detail_file_contents, status_file_contents, "t1"),
        ]
    )

    assert trials == (
        Trial(
            "t2",
            "3-0-0",
            "terminal-bench/build-cython",
            "row-2",
            "codex",
            "0.5.0",
            "model-b",
            0.0,
        ),
        TRIAL_OF_THE_FIXTURES,
    )


@pytest.mark.parametrize("broken_file", ["detail", "status"])
def test_error_of_either_file_carries_the_id_of_its_trial(
    detail_file_contents, status_file_contents, broken_file
):
    trial_file_texts = _trial_file_texts_from(
        detail_file_contents, status_file_contents, "t7"
    )
    if broken_file == "detail":
        trial_file_texts = dataclasses.replace(trial_file_texts, detail_text="{")
    else:
        trial_file_texts = dataclasses.replace(trial_file_texts, status_text="{")

    with pytest.raises(ValueError) as error:
        collect_one_trial(trial_file_texts)

    assert error.value.__notes__ == ["trial_id: t7"]
