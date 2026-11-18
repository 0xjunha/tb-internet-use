"""Tests for expanded_tool_call/_expand_variable_values.py, on texts split by `parse_shell_text`, reading the values of the variables of the first curl command."""

from collections import Counter

import pytest

from tb_internet_use.expanded_tool_call import _expand_variable_values
from tb_internet_use.expanded_tool_call._expand_variable_values import (
    expand_variable_values,
)
from tb_internet_use.expanded_tool_call.judgment_rules import (
    treat_values_outside_their_for_loop_as_one_of_them,
)
from tb_internet_use.expanded_tool_call.model import VariableValues
from tb_internet_use.tool_call.model import (
    ParsedShellText,
    ShellCommand,
    VariableAssignment,
)
from tb_internet_use.tool_call.parse_shell_text import parse_shell_text

OUTSIDE_LOOP_RULE_NAME = treat_values_outside_their_for_loop_as_one_of_them.__name__


def _parsed_shell_text_of(
    shell_text: str, *, first_command_id: int = 0
) -> ParsedShellText:
    parsed_shell_text = parse_shell_text(
        shell_text,
        judgment_rule_use_counts=Counter(),
        first_command_id=first_command_id,
    )
    assert isinstance(parsed_shell_text, ParsedShellText)
    return parsed_shell_text


def _curl_command_of(parsed_shell_text: ParsedShellText) -> ShellCommand:
    return next(c for c in parsed_shell_text.commands if c.words[0] == "curl")


def _variable_values_and_rule_uses_of(
    shell_text: str,
) -> tuple[tuple[VariableValues, ...], int]:
    parsed_shell_text = _parsed_shell_text_of(shell_text)
    use_counts: Counter[str] = Counter()
    variable_values = expand_variable_values(
        _curl_command_of(parsed_shell_text),
        parsed_shell_text.variable_assignments,
        judgment_rule_use_counts=use_counts,
    )
    return variable_values, use_counts[OUTSIDE_LOOP_RULE_NAME]


def _assignments_with_read_in_place(
    parsed_shell_text: ParsedShellText,
) -> tuple[VariableAssignment, ...]:
    """Insert an assignment without a value for the name that each `read NAME` sets, before the first assignment that comes after the read, as the caller of `expand_variable_values` does."""
    variable_assignments = list(parsed_shell_text.variable_assignments)
    for command in parsed_shell_text.commands:
        if command.words[0] != "read":
            continue
        position = next(
            (
                index
                for index, assignment in enumerate(variable_assignments)
                if assignment.next_command_id > command.id
            ),
            len(variable_assignments),
        )
        read_assignment = VariableAssignment(
            command.words[-1], None, command.id + 1, None
        )
        variable_assignments.insert(position, read_assignment)
    return tuple(variable_assignments)


# (case id, shell text, expected variable values, expected uses of the rule)
VALUE_CASES = [
    (
        "one literal value",
        "U=a.org; curl $U",
        (VariableValues("U", ("a.org",), False, False),),
        0,
    ),
    (
        "one literal value in braces",
        "U=a.org; curl ${U}/x",
        (VariableValues("U", ("a.org",), False, False),),
        0,
    ),
    (
        "name with an underscore",
        "API_URL=a; curl $API_URL",
        (VariableValues("API_URL", ("a",), False, False),),
        0,
    ),
    (
        "name in braces followed by an underscore",
        "U=a; curl ${U}_x",
        (VariableValues("U", ("a",), False, False),),
        0,
    ),
    (
        "items of the for loop whose body holds the command, in turn",
        "for u in a b; do curl $u; done",
        (VariableValues("u", ("a", "b"), True, False),),
        0,
    ),
    (
        "one item of the for loop, in turn",
        "for u in a; do curl $u; done",
        (VariableValues("u", ("a",), True, False),),
        0,
    ),
    (
        "loop items replace a literal value before the loop",
        "U=x; for U in a b; do curl $U; done",
        (VariableValues("U", ("a", "b"), True, False),),
        0,
    ),
    (
        "loop items replace a computed value before the loop",
        "U=$(cat x); for U in a b; do curl $U; done",
        (VariableValues("U", ("a", "b"), True, False),),
        0,
    ),
    (
        "a loop over another variable does not take U in turn",
        "for U in a b; do :; done; for V in c; do curl $U; done",
        (VariableValues("U", ("a", "b"), False, False),),
        1,
    ),
    (
        "a loop over another variable inside the loop over U",
        "for U in a b; do for V in c; do curl $U; done; done",
        (VariableValues("U", ("a", "b"), True, False),),
        0,
    ),
    (
        "the innermost of two loops over U that hold the command",
        "for U in a; do echo; for U in b c; do curl $U; done; done",
        (VariableValues("U", ("b", "c"), True, False),),
        0,
    ),
    (
        "a loop over U that ended before the command inside another",
        "for u in a b; do for u in c d; do :; done; curl $u; done",
        (VariableValues("u", ("a", "b", "c", "d"), False, False),),
        1,
    ),
    (
        "values of two if branches, in text order",
        "if c; then U=b; else U=a; fi; curl $U",
        (VariableValues("U", ("b", "a"), False, False),),
        1,
    ),
    (
        "items of a loop that ended before the command",
        "for U in a b; do :; done; curl $U",
        (VariableValues("U", ("a", "b"), False, False),),
        1,
    ),
    (
        "an assignment in the loop body before the command",
        "for U in a b; do U=c; curl $U; done",
        (VariableValues("U", ("a", "b", "c"), False, False),),
        1,
    ),
    (
        "one value assigned twice",
        "if c; then U=a; else U=a; fi; curl $U",
        (VariableValues("U", ("a",), False, False),),
        0,
    ),
    (
        "a computed value after a literal one",
        'U="1 2"; U=$(cat ids.txt); curl $U',
        (VariableValues("U", ("1 2",), False, True),),
        1,
    ),
    (
        "a computed value before a literal one",
        "U=$(cat u.txt); U=a.org; curl $U",
        (VariableValues("U", ("a.org",), False, True),),
        1,
    ),
    (
        "names in the order they first appear in the words",
        "A=a; B=b; curl $B/$A $B",
        (
            VariableValues("B", ("b",), False, False),
            VariableValues("A", ("a",), False, False),
        ),
        0,
    ),
    (
        "names of the words before names of the redirect paths",
        "LOG=l; U=u; curl $U > $LOG",
        (
            VariableValues("U", ("u",), False, False),
            VariableValues("LOG", ("l",), False, False),
        ),
        0,
    ),
    (
        "later computed value in a while loop body",
        "i=0; while [ $i -lt 3 ]; do curl $i; i=$((i+1)); done",
        (VariableValues("i", ("0",), False, True),),
        1,
    ),
    (
        "later literal value in a for loop body over another variable",
        "U=x; for i in 1 2; do curl $U; U=y; done",
        (VariableValues("U", ("x", "y"), False, False),),
        1,
    ),
    (
        "later literal value before the call of a function",
        "U=a; f() { curl $U; }; U=b; f",
        (VariableValues("U", ("a", "b"), False, False),),
        1,
    ),
    (
        "later value outside any loop or function body does not count",
        "U=a; curl $U; U=b",
        (VariableValues("U", ("a",), False, False),),
        0,
    ),
    (
        "later value at the end of the for loop body over U",
        "for U in a b; do curl $U; U=c; done",
        (VariableValues("U", ("a", "b", "c"), False, False),),
        1,
    ),
    (
        "later value after the end of the for loop over U does not count",
        "for p in A B; do curl $p; done; echo; p=x",
        (VariableValues("p", ("A", "B"), True, False),),
        0,
    ),
    (
        "later value after the for loop counts for a function body defined in it",
        "for u in a b; do f() { curl $u; }; f; done; echo; u=z; f",
        (VariableValues("u", ("a", "b", "z"), False, False),),
        1,
    ),
]

# (case id, shell text)
NO_VALUE_CASES = [
    ("never assigned", "curl $U"),
    ("assigned after the command", "curl $U; U=a.org"),
    ("only computed as the text runs", "U=$(cat u.txt); curl $U"),
    ("computed loop items", "U=a; for U in $(cat list); do curl $U; done"),
    ("no variable", "curl $(cat urls.txt)"),
    ("a form that changes the value", "U=a.org; curl ${U:-b.org}"),
    ("in single quotes", "U=a.org; curl '$U' u"),
    ("a longer name that starts with an assigned one", "U=a; curl $U_x"),
]


@pytest.mark.parametrize(
    ("shell_text", "expected_variable_values", "expected_rule_uses"),
    [case[1:] for case in VALUE_CASES],
    ids=[case[0] for case in VALUE_CASES],
)
def test_values_of_variables_in_command_words(
    shell_text: str,
    expected_variable_values: tuple[VariableValues, ...],
    expected_rule_uses: int,
):
    assert _variable_values_and_rule_uses_of(shell_text) == (
        expected_variable_values,
        expected_rule_uses,
    )


@pytest.mark.parametrize(
    "shell_text",
    [case[1] for case in NO_VALUE_CASES],
    ids=[case[0] for case in NO_VALUE_CASES],
)
def test_variable_without_literal_value_gets_no_variable_values(shell_text: str):
    assert _variable_values_and_rule_uses_of(shell_text) == ((), 0)


@pytest.mark.parametrize(
    "shell_text",
    [
        "LOG=/tmp/x.log; curl u > $LOG",
        "LOG=/tmp/x.log; curl u 2> $LOG",
        "LOG=/tmp/x.log; curl u < $LOG",
    ],
    ids=["stdout", "stderr", "stdin"],
)
def test_values_of_a_variable_in_a_redirect_file_path(shell_text: str):
    assert _variable_values_and_rule_uses_of(shell_text) == (
        (VariableValues("LOG", ("/tmp/x.log",), False, False),),
        0,
    )


def test_several_values_are_taken_in_turn_when_the_rule_says_no(monkeypatch):
    monkeypatch.setattr(
        _expand_variable_values,
        OUTSIDE_LOOP_RULE_NAME,
        lambda variable_name, *, use_counts: False,
    )

    variable_values, _ = _variable_values_and_rule_uses_of(
        "if c; then U=a; else U=b; fi; curl $U"
    )

    assert variable_values == (VariableValues("U", ("a", "b"), True, False),)


def test_text_run_in_calling_shell_sees_the_outer_assignments_its_caller_passes():
    # `U=a.org; eval 'curl $U; U=c.org'; U=b.org`. The caller passes the outer assignments up to `eval`, then those of the inner text, whose commands get ids after the outer ones.
    outer_shell_text = _parsed_shell_text_of(
        "U=a.org; eval 'curl $U; U=c.org'; U=b.org"
    )
    (eval_command,) = outer_shell_text.commands
    inner_shell_text = _parsed_shell_text_of(
        "curl $U; U=c.org", first_command_id=eval_command.id + 1
    )
    visible_outer_assignments = tuple(
        assignment
        for assignment in outer_shell_text.variable_assignments
        if assignment.next_command_id <= eval_command.id
    )

    assert expand_variable_values(
        _curl_command_of(inner_shell_text),
        visible_outer_assignments + inner_shell_text.variable_assignments,
        judgment_rule_use_counts=Counter(),
    ) == (VariableValues("U", ("a.org",), False, False),)


@pytest.mark.parametrize(
    ("shell_text", "expected_variable_values", "expected_rule_uses"),
    [
        (
            "U=a.org; read U; curl $U",
            (VariableValues("U", ("a.org",), False, True),),
            1,
        ),
        (
            "U=a; x | while read U; do curl $U; done",
            (VariableValues("U", ("a",), False, True),),
            1,
        ),
        # The read comes before the loop in text order, so the loop items still give the values in turn.
        (
            "read U; for U in a b; do curl $U; done",
            (VariableValues("U", ("a", "b"), True, False),),
            0,
        ),
    ],
    ids=[
        "read before the command",
        "read in a while condition",
        "read before a for loop",
    ],
)
def test_variable_set_by_a_command_counts_as_a_value_set_at_run_time(
    shell_text: str,
    expected_variable_values: tuple[VariableValues, ...],
    expected_rule_uses: int,
):
    # The caller inserts an assignment without a value for `read U` at its place in text order, since only a program fact says that read sets U.
    parsed_shell_text = _parsed_shell_text_of(shell_text)
    use_counts: Counter[str] = Counter()

    variable_values = expand_variable_values(
        _curl_command_of(parsed_shell_text),
        _assignments_with_read_in_place(parsed_shell_text),
        judgment_rule_use_counts=use_counts,
    )

    assert (variable_values, use_counts[OUTSIDE_LOOP_RULE_NAME]) == (
        expected_variable_values,
        expected_rule_uses,
    )
