"""Tests for callrun/variable_values.py."""

import pytest

from tb_internet_use.callrun.model import VariableValues
from tb_internet_use.callrun.variable_values import (
    command_variable_values,
    plain_variable_names,
    word_with_single_values_filled,
)
from tb_internet_use.shell.parser import parse_shell


@pytest.mark.parametrize(
    ("text", "values", "takes_each_value_in_turn"),
    [
        ("U=a.org; curl $U", ("a.org",), False),
        ("U=a.org; curl ${U}", ("a.org",), False),
        ("curl $U; U=a.org", None, None),  # assigned after the command
        ("U=$(cat f); curl $U", None, None),  # computed
        ("U=a.org; U=$(cat f); curl $U", None, None),
        ("read U; curl $U", None, None),
        ("U=a.org; read U; curl $U", None, None),
        ("for U in a b; do curl $U; done", ("a", "b"), True),
        ("for U in a; do curl $U; done", ("a",), True),
        ("for U in a b; do :; done; curl $U", ("a", "b"), False),  # after the loop
        ("if c; then U=a; else U=b; fi; curl $U", ("a", "b"), False),
        (
            "for U in a b; do U=c; curl $U; done",
            ("a", "b", "c"),
            False,
        ),  # reassigned in the body
        ("for U in a b; do :; done; for V in c; do curl $U; done", ("a", "b"), False),
        ("U=x; for U in a b; do curl $U; done", ("a", "b"), True),
        ("U=a.org; curl ${U:-b.org}", None, None),  # not a plain variable
    ],
)
def test_values_of_a_variable(
    text: str, values: tuple[str, ...] | None, takes_each_value_in_turn: bool | None
):
    parsed = parse_shell(text)
    (curl,) = [c for c in parsed.commands if c.words[0] == "curl"]
    found = command_variable_values(curl, parsed)
    expected = (
        ()
        if values is None
        else (VariableValues("U", values, bool(takes_each_value_in_turn)),)
    )
    assert found == expected


def test_plain_variable_names_are_in_order_without_repeats():
    assert plain_variable_names("$A/${B}/$A-$1") == ("A", "B", "1")


def test_word_with_single_values_filled_fills_only_variables_with_one_value():
    variable_values = (
        VariableValues("A", ("x",), False),
        VariableValues("B", ("y", "z"), False),
    )
    assert (
        word_with_single_values_filled("$A/${A}/$B/$C", variable_values) == "x/x/$B/$C"
    )


@pytest.mark.parametrize(
    "text", ["LOG=/tmp/x.log; curl u > $LOG", "LOG=/tmp/x.log; curl u < $LOG"]
)
def test_values_of_a_variable_in_a_redirect_file_path(text: str):
    parsed = parse_shell(text)
    (curl,) = [c for c in parsed.commands if c.words[0] == "curl"]
    assert command_variable_values(curl, parsed) == (
        VariableValues("LOG", ("/tmp/x.log",), False),
    )
