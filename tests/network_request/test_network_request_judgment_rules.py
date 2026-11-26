"""Tests for network_request/judgment_rules.py."""

from collections import Counter

import pytest

from tb_internet_use.expanded_tool_call.model import VariableValues
from tb_internet_use.network_request.judgment_rules import (
    treat_call_name_that_ends_with_catalog_name_as_uncertain_call_of_that_name,
    treat_call_of_module_row_through_name_that_code_binds_without_import_as_call_without_row,
    treat_dotted_host_name_as_public,
    treat_single_label_or_templated_host_name_as_possibly_public,
    treat_url_of_namespace_host_as_no_target,
    treat_values_outside_their_for_loop_as_unknown_target,
    treat_web_find_as_uncertain_request,
)
from tb_internet_use.network_request.model import (
    HostNameScope,
    UnknownHostNameScope,
    UnknownHostNameScopeReason,
)

DOTTED_NAME = UnknownHostNameScope(UnknownHostNameScopeReason.DOTTED_NAME)
SINGLE_LABEL = UnknownHostNameScope(UnknownHostNameScopeReason.SINGLE_LABEL)
TEMPLATED = UnknownHostNameScope(UnknownHostNameScopeReason.TEMPLATED)
EMPTY_LABEL = UnknownHostNameScope(UnknownHostNameScopeReason.EMPTY_LABEL)


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
    for unknown_host_name_scope in (DOTTED_NAME, EMPTY_LABEL):
        with pytest.raises(ValueError):
            treat_single_label_or_templated_host_name_as_possibly_public(
                unknown_host_name_scope, use_counts=use_counts
            )
    assert use_counts == Counter(
        {"treat_single_label_or_templated_host_name_as_possibly_public": 2}
    )


def test_values_outside_their_for_loop_give_no_request_of_their_own_and_are_counted():
    use_counts: Counter[str] = Counter()
    branches = VariableValues("A", ("1", "2"), False, False)

    assert (
        treat_values_outside_their_for_loop_as_unknown_target(
            branches, use_counts=use_counts
        )
        == ()
    )
    assert use_counts == Counter(
        {"treat_values_outside_their_for_loop_as_unknown_target": 1}
    )


@pytest.mark.parametrize(
    ("url", "is_namespace"),
    [
        ("http://www.w3.org/2000/svg", True),
        ("http://schemas.openxmlformats.org/spreadsheetml/2006/main", True),
        ("http://purl.org/dc/terms/", True),
        ("https://json-schema.org/draft/2020-12/schema", True),
        # A last path part with a dot names a file that code may fetch.
        ("http://www.w3.org/2001/XMLSchema.xsd", False),
        ("https://a.org/2000/svg", False),
        # The host is only the start of another host.
        ("http://www.w3.org.evil.example/2000/svg", False),
    ],
)
def test_url_of_namespace_host_is_no_target_only_without_a_dot_in_its_last_part(
    url, is_namespace
):
    use_counts: Counter[str] = Counter()

    assert (
        treat_url_of_namespace_host_as_no_target(url, use_counts=use_counts)
        is is_namespace
    )
    assert use_counts == Counter(
        {"treat_url_of_namespace_host_as_no_target": 1} if is_namespace else {}
    )


def test_web_find_is_an_uncertain_request_and_counted():
    use_counts: Counter[str] = Counter()

    assert treat_web_find_as_uncertain_request(use_counts=use_counts)
    assert use_counts == Counter({"treat_web_find_as_uncertain_request": 1})


def test_call_name_that_ends_with_catalog_name_is_an_uncertain_call_and_counted():
    use_counts: Counter[str] = Counter()

    assert treat_call_name_that_ends_with_catalog_name_as_uncertain_call_of_that_name(
        "self.page.goto", use_counts=use_counts
    )
    assert use_counts == Counter(
        {
            "treat_call_name_that_ends_with_catalog_name_as_uncertain_call_of_that_name": 1
        }
    )


@pytest.mark.parametrize(
    ("first_name_part", "bound_names", "expected"),
    [
        # `requests = {}` then `requests.get(rid)`, or `ctx.requests.get(rid)` in `def f(ctx):`.
        ("requests", frozenset({"requests"}), True),
        ("ctx", frozenset({"ctx", "x"}), True),
        # A name that is neither imported nor bound may come from a star import, e.g. `subprocess.run(cmd)` after `from helpers import *`.
        ("subprocess", frozenset({"x"}), False),
    ],
)
def test_call_of_a_module_row_through_a_bound_name_is_a_call_without_row_and_counted(
    first_name_part, bound_names, expected
):
    use_counts: Counter[str] = Counter()

    assert (
        treat_call_of_module_row_through_name_that_code_binds_without_import_as_call_without_row(
            first_name_part, bound_names, use_counts=use_counts
        )
        is expected
    )
    assert use_counts == Counter(
        {
            "treat_call_of_module_row_through_name_that_code_binds_without_import_as_call_without_row": 1
        }
        if expected
        else {}
    )
