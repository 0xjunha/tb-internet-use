"""Tests for expanded_tool_call/judgment_rules.py."""

from collections import Counter

from tb_internet_use.expanded_tool_call.judgment_rules import (
    treat_values_outside_their_for_loop_as_one_of_them,
    treat_calls_of_other_trajectory_as_not_linked,
    treat_poll_as_reading_latest_earlier_start_of_handle,
    treat_script_poll_step_naming_no_handle_as_polling_none,
    treat_word_with_expansion_as_one_argument,
)


def test_values_outside_their_for_loop_are_read_as_one_of_them_and_counted():
    use_counts: Counter[str] = Counter()

    assert treat_values_outside_their_for_loop_as_one_of_them(
        "A", use_counts=use_counts
    )
    assert use_counts == Counter(
        {"treat_values_outside_their_for_loop_as_one_of_them": 1}
    )


def test_word_with_an_expansion_is_read_as_one_argument_and_counted():
    use_counts: Counter[str] = Counter()

    assert treat_word_with_expansion_as_one_argument("$OPTS", use_counts=use_counts)
    assert use_counts == Counter({"treat_word_with_expansion_as_one_argument": 1})


def test_poll_is_linked_to_the_latest_earlier_start_of_its_handle_and_counted():
    use_counts: Counter[str] = Counter()

    assert treat_poll_as_reading_latest_earlier_start_of_handle(use_counts=use_counts)
    assert use_counts == Counter(
        {"treat_poll_as_reading_latest_earlier_start_of_handle": 1}
    )


def test_calls_of_other_trajectory_are_not_linked_and_counted():
    use_counts: Counter[str] = Counter()

    assert treat_calls_of_other_trajectory_as_not_linked(use_counts=use_counts)
    assert use_counts == Counter({"treat_calls_of_other_trajectory_as_not_linked": 1})


def test_script_poll_step_naming_no_handle_reads_no_handle_and_counted():
    use_counts: Counter[str] = Counter()

    assert treat_script_poll_step_naming_no_handle_as_polling_none(
        use_counts=use_counts
    )
    assert use_counts == Counter(
        {"treat_script_poll_step_naming_no_handle_as_polling_none": 1}
    )
