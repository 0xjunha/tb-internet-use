"""Tests for export/judgment_rules.py, one table of each rule with a made-up situation, the value it gives and the name it is counted under."""

from collections import Counter
from collections.abc import Callable

import pytest

from tb_internet_use.export.judgment_rules import (
    treat_url_query_value_and_fragment_as_credential,
)

# (rule, its situation, the value it gives)
JUDGMENT_RULE_CASES: list[tuple[Callable[..., object], tuple[object, ...], object]] = [
    (
        treat_url_query_value_and_fragment_as_credential,
        ("curl 'https://a.org/x?token=abc&page=2#k'",),
        True,
    ),
]


@pytest.mark.parametrize(("rule", "situation", "value"), JUDGMENT_RULE_CASES)
def test_each_rule_gives_its_provisional_value_and_counts_one_use_under_its_name(
    rule: Callable[..., object], situation: tuple[object, ...], value: object
):
    use_counts: Counter[str] = Counter()

    assert rule(*situation, use_counts=use_counts) == value
    assert use_counts == Counter({rule.__name__: 1})
