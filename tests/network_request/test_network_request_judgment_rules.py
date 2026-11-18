"""Tests for network_request/judgment_rules.py."""

from collections import Counter

import pytest

from tb_internet_use.expanded_tool_call.model import VariableValues
from tb_internet_use.network_request.judgment_rules import (
    treat_dotted_host_name_as_public,
    treat_single_label_or_templated_host_name_as_possibly_public,
    treat_values_outside_their_for_loop_as_one_request_each,
)
from tb_internet_use.network_request.model import (
    HostNameScope,
    UnknownHostNameScope,
    UnknownHostNameScopeReason,
)

DOTTED_NAME = UnknownHostNameScope(UnknownHostNameScopeReason.DOTTED_NAME)
SINGLE_LABEL = UnknownHostNameScope(UnknownHostNameScopeReason.SINGLE_LABEL)
TEMPLATED = UnknownHostNameScope(UnknownHostNameScopeReason.TEMPLATED)


def test_dotted_host_name_is_read_as_public_and_counted_and_other_forms_are_left_alone():
    use_counts: Counter[str] = Counter()

    assert treat_dotted_host_name_as_public(DOTTED_NAME, use_counts=use_counts) == (
        HostNameScope.PUBLIC
    )
    assert treat_dotted_host_name_as_public(SINGLE_LABEL, use_counts=use_counts) == (
        SINGLE_LABEL
    )
    assert treat_dotted_host_name_as_public(TEMPLATED, use_counts=use_counts) == (
        TEMPLATED
    )
    assert use_counts == Counter({"treat_dotted_host_name_as_public": 1})


def test_single_label_or_templated_host_name_is_read_as_possibly_public_and_counted():
    use_counts: Counter[str] = Counter()

    assert treat_single_label_or_templated_host_name_as_possibly_public(
        SINGLE_LABEL, use_counts=use_counts
    )
    assert treat_single_label_or_templated_host_name_as_possibly_public(
        TEMPLATED, use_counts=use_counts
    )
    with pytest.raises(ValueError):
        treat_single_label_or_templated_host_name_as_possibly_public(
            DOTTED_NAME, use_counts=use_counts
        )
    assert use_counts == Counter(
        {"treat_single_label_or_templated_host_name_as_possibly_public": 2}
    )


def test_values_outside_their_for_loop_each_give_a_request_and_are_counted():
    use_counts: Counter[str] = Counter()
    branches = VariableValues("A", ("1", "2"), False, False)

    assert treat_values_outside_their_for_loop_as_one_request_each(
        branches, use_counts=use_counts
    ) == ("1", "2")
    assert use_counts == Counter(
        {"treat_values_outside_their_for_loop_as_one_request_each": 1}
    )
