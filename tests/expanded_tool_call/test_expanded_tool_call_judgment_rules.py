"""Tests for expanded_tool_call/judgment_rules.py."""

from collections import Counter

from tb_internet_use.expanded_tool_call.judgment_rules import (
    treat_word_with_expansion_as_one_argument,
)


def test_word_with_an_expansion_is_read_as_one_argument_and_counted():
    use_counts: Counter[str] = Counter()

    assert treat_word_with_expansion_as_one_argument("$OPTS", use_counts=use_counts)
    assert use_counts == Counter({"treat_word_with_expansion_as_one_argument": 1})
