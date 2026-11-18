"""Tests for expanded_tool_call/_expand_ran_commands.py, on texts split by `parse_shell_text` and a made-up program catalog whose rows the cases name, so that a case does not change when the real catalog gains rows."""

from collections import Counter

import pytest

from tb_internet_use.expanded_tool_call._expand_ran_commands import (
    expand_ran_commands,
)
from tb_internet_use.expanded_tool_call.judgment_rules import (
    treat_values_outside_their_for_loop_as_one_of_them,
    treat_word_with_expansion_as_one_argument,
)
from tb_internet_use.expanded_tool_call.model import (
    OutputRoute,
    OutputVisibility,
    ProgramInvocation,
    ProgramOption,
    ProgramWordRole,
    RanCommand,
    UnknownProgramWordRole,
    VariableValues,
)
from tb_internet_use.knowledge.expanded_tool_call_knowledge import (
    PROGRAM_BEHAVIORS_CSV,
    ExpandedToolCallKnowledge,
)
from tb_internet_use.tool_call.model import (
    FileDestination,
    ParsedShellText,
    ResultDestination,
    VariableAssignment,
)
from tb_internet_use.tool_call.parse_shell_text import parse_shell_text

OUTSIDE_LOOP_RULE_NAME = treat_values_outside_their_for_loop_as_one_of_them.__name__
EXPANSION_RULE_NAME = treat_word_with_expansion_as_one_argument.__name__
WHOLE_RESULT_ROUTE = OutputRoute((), ResultDestination(), OutputVisibility.WHOLE)
NAME_SET_AT_RUN_TIME = ProgramWordRole.VARIABLE_NAME_SET_AT_RUN_TIME

# Made-up rows, each named by the program and the cells that differ from the defaults of `conftest.py`. mytool has no row, read has no row for `-t` or `-E`, and tail has no row for `-Z`.
PROGRAM_BEHAVIOR_ROWS: list[dict[str, str]] = [
    {"program_name": "curl"},
    {
        "program_name": "tail",
        "argument_role": "read_file",
        "visibility_of_piped_input": "partial",
    },
    {
        "program_name": "sudo",
        "argument_role": "program",
        "options_end_at_first_argument": "yes",
        "exits_with_exit_code_of_next_program": "yes",
    },
    {"program_name": "read", "argument_role": "variable_name_set_at_run_time"},
]
# Made-up rows, each named by the program, the option and the cells that differ from the defaults of `conftest.py`.
PROGRAM_OPTION_BEHAVIOR_ROWS: list[dict[str, str]] = [
    {
        "program_name": "curl",
        "option_name": "-o",
        "takes_value": "yes",
        "value_role": "written_file",
    },
    {"program_name": "read", "option_name": "-r"},
]

# (case id, shell text, expected variable values of the first curl, expected uses of the rule on values outside their for loop)
VARIABLE_VALUE_CASES = [
    (
        "literal value",
        "U=a.org; curl $U",
        (VariableValues("U", ("a.org",), False, False),),
        0,
    ),
    (
        "read after the literal value",
        "U=a.org; read U; curl $U",
        (VariableValues("U", ("a.org",), False, True),),
        1,
    ),
    (
        "read with an option",
        "U=a.org; read -r U; curl $U",
        (VariableValues("U", ("a.org",), False, True),),
        1,
    ),
    # The unread words of read may name any variable, so every variable assigned in the text may be set, not only X.
    (
        "read with an option without a row",
        "U=a.org; V=b; read -t 5 X; curl $U $V",
        (
            VariableValues("U", ("a.org",), False, True),
            VariableValues("V", ("b",), False, True),
        ),
        2,
    ),
    # The unread words may also name a variable that the text assigns only after read, which a later turn of the loop sees.
    (
        "read with an option without a row before a later assignment in a loop",
        "while x; do curl $W; read -E U; W=b; done",
        (VariableValues("W", ("b",), False, True),),
        1,
    ),
    (
        "program whose arguments set no variable with an option without a row",
        "U=a.org; tail -Z x; curl $U",
        (VariableValues("U", ("a.org",), False, False),),
        0,
    ),
    (
        "read in a pipe reader before the loop",
        "U=a; x | while read U; do curl $U; done",
        (VariableValues("U", ("a",), False, True),),
        1,
    ),
    (
        "read before a for loop over the name",
        "read U; for U in a b; do curl $U; done",
        (VariableValues("U", ("a", "b"), True, False),),
        0,
    ),
    (
        "read after the command outside a loop",
        "U=a.org; curl $U; read U",
        (VariableValues("U", ("a.org",), False, False),),
        0,
    ),
    (
        "read later in the loop body",
        "U=a.org; while c; do curl $U; read U; done",
        (VariableValues("U", ("a.org",), False, True),),
        1,
    ),
    (
        "read of another name",
        "U=a.org; read V; curl $U",
        (VariableValues("U", ("a.org",), False, False),),
        0,
    ),
    (
        "word of read with an expansion",
        "U=a.org; read $X; curl $U",
        (VariableValues("U", ("a.org",), False, False),),
        0,
    ),
    (
        "read of a program without a row",
        "U=a.org; mytool U; curl $U",
        (VariableValues("U", ("a.org",), False, False),),
        0,
    ),
]


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


def _curl_of(ran_commands: tuple[RanCommand, ...]) -> RanCommand:
    return next(
        ran_command
        for ran_command in ran_commands
        if ran_command.shell_command.words[0] == "curl"
    )


def test_each_command_is_read_into_its_programs_routes_and_word_roles_in_text_order(
    catalogs_dir,
):
    knowledge = ExpandedToolCallKnowledge(catalogs_dir=catalogs_dir)
    parsed_shell_text = _parsed_shell_text_of(
        "sudo curl -o out u | tail 2> err; mytool x"
    )
    ran_commands_of_shell_text = expand_ran_commands(
        parsed_shell_text, knowledge=knowledge, judgment_rule_use_counts=Counter()
    )
    ran_commands = ran_commands_of_shell_text.ran_commands
    tail_route = OutputRoute((1,), ResultDestination(), OutputVisibility.PARTIAL)
    error_file_route = OutputRoute(
        (), FileDestination("err", False), OutputVisibility.WHOLE
    )
    curl = ProgramInvocation(
        "curl", (), (ProgramOption("-o", "out"),), ("u",), False, (), False
    )
    sudo = ProgramInvocation("sudo", (), (), (), False, (), True)
    assert [ran_command.shell_command for ran_command in ran_commands] == list(
        parsed_shell_text.commands
    )
    assert [
        (
            ran_command.program_invocations[0].program_name,
            ran_command.stdout_routes,
            ran_command.stderr_routes,
        )
        for ran_command in ran_commands
    ] == [
        ("sudo", (tail_route,), (WHOLE_RESULT_ROUTE,)),
        ("tail", (WHOLE_RESULT_ROUTE,), (error_file_route,)),
        ("mytool", (WHOLE_RESULT_ROUTE,), (WHOLE_RESULT_ROUTE,)),
    ]
    assert ran_commands[0].program_invocations == (sudo, curl)
    assert ran_commands_of_shell_text.word_roles_of_commands == (
        (
            None,
            None,
            None,
            ProgramWordRole.WRITTEN_FILE,
            ProgramWordRole.OTHER,
        ),
        (None,),
        (None, UnknownProgramWordRole()),
    )


@pytest.mark.parametrize(
    ("shell_text", "variable_values", "rule_uses"),
    [case[1:] for case in VARIABLE_VALUE_CASES],
    ids=[case[0] for case in VARIABLE_VALUE_CASES],
)
def test_names_that_commands_set_at_run_time_take_their_place_among_the_assignments(
    catalogs_dir, shell_text, variable_values, rule_uses
):
    knowledge = ExpandedToolCallKnowledge(catalogs_dir=catalogs_dir)
    judgment_rule_use_counts: Counter[str] = Counter()
    ran_commands = expand_ran_commands(
        _parsed_shell_text_of(shell_text),
        knowledge=knowledge,
        judgment_rule_use_counts=judgment_rule_use_counts,
    ).ran_commands
    assert _curl_of(ran_commands).variable_values == variable_values
    assert judgment_rule_use_counts[OUTSIDE_LOOP_RULE_NAME] == rule_uses


def test_pipe_that_takes_only_stderr_leads_stderr_to_its_reader(catalogs_dir):
    knowledge = ExpandedToolCallKnowledge(catalogs_dir=catalogs_dir)
    ran_commands = expand_ran_commands(
        _parsed_shell_text_of("curl u 2>&1 >/dev/null | tail"),
        knowledge=knowledge,
        judgment_rule_use_counts=Counter(),
    ).ran_commands
    assert _curl_of(ran_commands).stderr_routes == (
        OutputRoute((1,), ResultDestination(), OutputVisibility.PARTIAL),
    )


def test_outer_assignments_come_before_those_of_the_text(catalogs_dir):
    knowledge = ExpandedToolCallKnowledge(catalogs_dir=catalogs_dir)
    ran_commands = expand_ran_commands(
        _parsed_shell_text_of("U=b; curl $U", first_command_id=5),
        outer_variable_assignments=(VariableAssignment("U", "a.org", 1, None),),
        knowledge=knowledge,
        judgment_rule_use_counts=Counter(),
    ).ran_commands
    # The values keep the order of the assignments, so the outer value comes first.
    assert _curl_of(ran_commands).variable_values == (
        VariableValues("U", ("a.org", "b"), False, False),
    )


def test_names_set_at_run_time_go_before_the_first_later_assignment_in_word_order(
    catalogs_dir,
):
    knowledge = ExpandedToolCallKnowledge(catalogs_dir=catalogs_dir)
    variable_assignments = expand_ran_commands(
        _parsed_shell_text_of("X=x; read A B; read -r C $D; A=a; curl $A; Y=y"),
        knowledge=knowledge,
        judgment_rule_use_counts=Counter(),
    ).variable_assignments
    # The word `$D` names a variable only when read runs, so it gives no assignment.
    assert variable_assignments == (
        VariableAssignment("X", "x", 0, None),
        VariableAssignment("A", None, 1, None),
        VariableAssignment("B", None, 1, None),
        VariableAssignment("C", None, 2, None),
        VariableAssignment("A", "a", 2, None),
        VariableAssignment("Y", "y", 3, None),
    )


def test_command_with_unread_variable_names_gets_an_assignment_for_every_name_in_first_order(
    catalogs_dir,
):
    knowledge = ExpandedToolCallKnowledge(catalogs_dir=catalogs_dir)
    variable_assignments = expand_ran_commands(
        _parsed_shell_text_of("B=b; mytool; A=a; read -E X; curl $A; B=c"),
        knowledge=knowledge,
        judgment_rule_use_counts=Counter(),
    ).variable_assignments
    # The names are those of every assignment of the text in the order they first appear, so B comes before A.
    assert variable_assignments == (
        VariableAssignment("B", "b", 0, None),
        VariableAssignment("A", "a", 1, None),
        VariableAssignment("B", None, 2, None),
        VariableAssignment("A", None, 2, None),
        VariableAssignment("B", "c", 3, None),
    )


def test_rules_of_the_pieces_are_counted_in_the_counter_that_is_passed(catalogs_dir):
    knowledge = ExpandedToolCallKnowledge(catalogs_dir=catalogs_dir)
    judgment_rule_use_counts: Counter[str] = Counter()
    expand_ran_commands(
        _parsed_shell_text_of("U=a; read U; curl $OPTS $U"),
        knowledge=knowledge,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )
    assert judgment_rule_use_counts == Counter(
        {EXPANSION_RULE_NAME: 2, OUTSIDE_LOOP_RULE_NAME: 1}
    )


def test_row_of_each_program_is_counted_once_per_command(catalogs_dir):
    knowledge = ExpandedToolCallKnowledge(catalogs_dir=catalogs_dir)
    expand_ran_commands(
        _parsed_shell_text_of("curl u | tail -1"),
        knowledge=knowledge,
        judgment_rule_use_counts=Counter(),
    )
    # The share of tail comes from the row that `expand_program_invocations` read, so the door is not asked again.
    assert Counter(
        {
            row_key: count
            for (csv_name, row_key), count in knowledge.uses.row_use_counts.items()
            if csv_name == PROGRAM_BEHAVIORS_CSV
        }
    ) == Counter({("curl", ""): 1, ("tail", ""): 1})
