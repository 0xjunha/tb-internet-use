"""Tests for expanded_tool_call/judgment_rules.py."""

from collections import Counter

from tb_internet_use.expanded_tool_call.judgment_rules import (
    treat_values_outside_their_for_loop_as_one_of_them,
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
