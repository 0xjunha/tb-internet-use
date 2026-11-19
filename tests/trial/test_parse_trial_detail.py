"""Tests for parse_trial_detail.py."""

import json
from typing import Any

import pytest

from tb_internet_use.trial.parse_trial_detail import parse_trial_detail

# Each path names a key of the detail file, from the top down.
REQUIRED_KEY_PATHS = [
    ("task_name",),
    ("agent_info",),
    ("agent_info", "name"),
    ("agent_info", "version"),
    ("agent_info", "model_info"),
    ("agent_info", "model_info", "name"),
    ("verifier_result",),
]
TEXT_KEY_PATHS = [
    ("task_name",),
    ("agent_info", "name"),
    ("agent_info", "version"),
    ("agent_info", "model_info", "name"),
]


def _parent_of_key(
    detail_file_contents: dict[str, Any], key_path: tuple[str, ...]
) -> dict[str, Any]:
    parent = detail_file_contents
    for key in key_path[:-1]:
        parent = parent[key]
    return parent


def _assert_raises_with_the_trial_id(detail_file_contents: dict[str, Any]) -> None:
    with pytest.raises(ValueError) as error:
        parse_trial_detail(json.dumps(detail_file_contents), "t1")

    assert error.value.__notes__ == ["trial_id: t1"]


@pytest.mark.parametrize(
    ("written_reward", "reward"),
    [pytest.param(0, 0.0, id="0"), pytest.param(1, 1.0, id="1")],
)
def test_reward_written_as_a_whole_number_becomes_a_float(
    detail_file_contents, written_reward, reward
):
    detail_file_contents["verifier_result"] = {"rewards": {"reward": written_reward}}

    parsed_reward = parse_trial_detail(json.dumps(detail_file_contents), "t1").reward

    assert parsed_reward == reward
    assert type(parsed_reward) is float


def test_reward_between_zero_and_one_stays_as_written(detail_file_contents):
    detail_file_contents["verifier_result"] = {"rewards": {"reward": 0.25}}

    assert parse_trial_detail(json.dumps(detail_file_contents), "t1").reward == 0.25


@pytest.mark.parametrize(
    "verifier_result",
    [
        pytest.param({}, id="no rewards"),
        pytest.param({"rewards": {}}, id="no reward"),
        pytest.param({"rewards": {"reward": "1.0"}}, id="reward written as text"),
        pytest.param({"rewards": {"reward": True}}, id="reward written as true"),
        pytest.param(
            {"rewards": {"reward": 10**400}}, id="reward too large for a float"
        ),
    ],
)
def test_verifier_result_without_a_reward_that_is_a_number_raises_with_the_trial_id(
    detail_file_contents, verifier_result
):
    detail_file_contents["verifier_result"] = verifier_result

    _assert_raises_with_the_trial_id(detail_file_contents)


def test_model_info_written_as_null_gives_no_model_name(detail_file_contents):
    detail_file_contents["agent_info"]["model_info"] = None

    assert parse_trial_detail(json.dumps(detail_file_contents), "t1").model_name is None


def test_model_info_that_is_neither_null_nor_an_object_raises_with_the_trial_id(
    detail_file_contents,
):
    detail_file_contents["agent_info"]["model_info"] = "model-a"

    _assert_raises_with_the_trial_id(detail_file_contents)


@pytest.mark.parametrize(
    "key_path", [pytest.param(path, id=".".join(path)) for path in REQUIRED_KEY_PATHS]
)
def test_detail_without_a_key_that_it_reads_raises_with_the_trial_id(
    detail_file_contents, key_path
):
    del _parent_of_key(detail_file_contents, key_path)[key_path[-1]]

    _assert_raises_with_the_trial_id(detail_file_contents)


@pytest.mark.parametrize(
    "key_path", [pytest.param(path, id=".".join(path)) for path in TEXT_KEY_PATHS]
)
def test_detail_with_a_value_that_is_no_text_where_it_reads_text_raises_with_the_trial_id(
    detail_file_contents, key_path
):
    _parent_of_key(detail_file_contents, key_path)[key_path[-1]] = 1

    _assert_raises_with_the_trial_id(detail_file_contents)


def test_broken_json_raises_with_the_trial_id():
    with pytest.raises(ValueError) as error:
        parse_trial_detail('{"task_name":', "t1")

    assert error.value.__notes__ == ["trial_id: t1"]
