"""Find the literal values that the assignments of a text give to the variables in the words and redirect file paths of one of its commands.

A file or a text that a command runs is often named by a variable, e.g. `bash $F` after `F=fetch.sh`, or `bash -c "$CMD"`, and a loop can run a command once per item, e.g. `for p in A B; do pip install $p; done`.
Only what the text itself assigns is a value. A variable that the text never assigns, or assigns only what it computes as it runs, e.g. `U=$(cat url.txt)`, gets no `VariableValues`.
"""

import re
from collections import Counter
from collections.abc import Sequence

from tb_internet_use.expanded_tool_call.judgment_rules import (
    treat_values_outside_their_for_loop_as_one_of_them,
)
from tb_internet_use.expanded_tool_call.model import VariableValues
from tb_internet_use.tool_call.model import (
    FileDestination,
    ShellCommand,
    VariableAssignment,
)

# A variable used as `$NAME` or `${NAME}`. A form such as `${NAME:-x}` or `${NAME%/}` changes the value, so it is not a use of the name here.
_PLAIN_VARIABLE = re.compile(r"\$(?:\{(\w+)\}|(\w+))")


def expand_variable_values(
    shell_command: ShellCommand,
    variable_assignments: Sequence[VariableAssignment],
    *,
    judgment_rule_use_counts: Counter[str],
) -> tuple[VariableValues, ...]:
    """Find the literal values that each variable in a command's words and redirect file paths may have when it runs, in the order the names first appear.

    `variable_assignments` are the assignments that the shell running the command sees, in text order, e.g. those of the text with the outer ones before them for the text of `eval`.
    The caller puts a variable that a command sets as it runs, e.g. U in `read U`, among them as an assignment without a value, at its place in text order.
    Those whose `next_command_id` is at most the id of the command come before it.
    One that comes after it counts too when the command is in a loop body or a function body, since it may run before a later run of the command, e.g. `i=$((i+1))` in `while c; do curl $i; i=$((i+1)); done`.
    A word counts only when it is among `shell_command.expansion_word_indexes`, so `$U` in single quotes is not a variable, e.g. in `echo '$U'`.
    Every use of `treat_values_outside_their_for_loop_as_one_of_them` adds one to `judgment_rule_use_counts`.
    """
    variable_values: list[VariableValues] = []
    for variable_name in _variable_names_of(shell_command):
        assignments_of_name = [
            assignment
            for assignment in variable_assignments
            if assignment.name == variable_name
        ]
        assignments_before = [
            assignment
            for assignment in assignments_of_name
            if assignment.next_command_id <= shell_command.id
        ]
        loop_item_assignments = _loop_item_assignments_for(
            shell_command, assignments_before
        )
        later_assignments = _later_assignments_for(
            shell_command, assignments_of_name, loop_item_assignments
        )
        deciding_assignments = [
            *(loop_item_assignments or assignments_before),
            *later_assignments,
        ]
        values = tuple(
            dict.fromkeys(
                assignment.value
                for assignment in deciding_assignments
                if assignment.value is not None
            )
        )
        if not values:
            continue
        has_value_set_at_run_time = any(
            assignment.value is None for assignment in deciding_assignments
        )
        if loop_item_assignments and not later_assignments:
            takes_each_value_in_turn = True
        elif len(values) + has_value_set_at_run_time > 1:
            takes_each_value_in_turn = (
                not treat_values_outside_their_for_loop_as_one_of_them(
                    variable_name, use_counts=judgment_rule_use_counts
                )
            )
        else:
            takes_each_value_in_turn = False
        variable_values.append(
            VariableValues(
                variable_name,
                values,
                takes_each_value_in_turn,
                has_value_set_at_run_time,
            )
        )
    return tuple(variable_values)


def _variable_names_of(shell_command: ShellCommand) -> tuple[str, ...]:
    """List the names that the expansion words and the redirect file paths of a command use as `$NAME` or `${NAME}`, in order and without repeats.

    The redirect file paths carry no mark of their quotes, so each is read as an expansion word.
    """
    expansion_words = [
        shell_command.words[i] for i in shell_command.expansion_word_indexes
    ]
    redirect_file_paths = [
        destination.path
        for destination in (shell_command.stdout, shell_command.stderr)
        if isinstance(destination, FileDestination)
    ]
    if shell_command.stdin_file_path is not None:
        redirect_file_paths.append(shell_command.stdin_file_path)
    return tuple(
        dict.fromkeys(
            match.group(1) or match.group(2)
            for word in (*expansion_words, *redirect_file_paths)
            for match in _PLAIN_VARIABLE.finditer(word)
        )
    )


def _loop_item_assignments_for(
    shell_command: ShellCommand, assignments_before: Sequence[VariableAssignment]
) -> list[VariableAssignment]:
    """Take the item assignments of the innermost for loop over the name whose body holds the command, if nothing assigns the name again before the command inside it.

    Empty when the command lies in no such loop, e.g. after the loop in `for U in a b; do :; done; curl $U`.
    The items of a loop that ended before the command are not among them, e.g. c and d in `for U in a b; do for U in c d; do :; done; curl $U; done`, where they come after a and b and so make the result empty.
    The assignments are in text order, so one after the items lies in the loop body, e.g. `U=c` in `for U in a b; do U=c; curl $U; done`.
    Two loops over one name that start at the same command and end at the same command cannot be told apart, e.g. in `for U in a; do for U in b; do curl $U; done; done`.
    """
    holding_loop_item_assignments = [
        assignment
        for assignment in assignments_before
        if assignment.next_command_id_after_for_loop is not None
        and shell_command.id < assignment.next_command_id_after_for_loop
    ]
    if not holding_loop_item_assignments:
        return []
    first_command_id_of_innermost_loop = max(
        assignment.next_command_id for assignment in holding_loop_item_assignments
    )
    next_command_id_after_innermost_loop = min(
        assignment.next_command_id_after_for_loop
        for assignment in holding_loop_item_assignments
        if assignment.next_command_id == first_command_id_of_innermost_loop
        and assignment.next_command_id_after_for_loop is not None
    )
    item_positions = [
        position
        for position, assignment in enumerate(assignments_before)
        if assignment.next_command_id == first_command_id_of_innermost_loop
        and assignment.next_command_id_after_for_loop
        == next_command_id_after_innermost_loop
    ]
    if item_positions[-1] != len(assignments_before) - 1:
        return []
    return [assignments_before[position] for position in item_positions]


def _later_assignments_for(
    shell_command: ShellCommand,
    assignments_of_name: Sequence[VariableAssignment],
    loop_item_assignments: Sequence[VariableAssignment],
) -> list[VariableAssignment]:
    """Take the assignments after the command in the text that may run before a later run of it, which is when the command is in a loop body or a function body.

    The types do not say where a while loop or a function body ends, so every later assignment counts, e.g. `U=b` in `U=a; f() { curl $U; }; U=b; f`.
    For a command that takes the items of a for loop in turn, only those up to the end of that loop count, since the loop assigns an item before each run, e.g. not `p=x` in `for p in A B; do pip install $p; done; echo; p=x`.
    A command in a function body is the exception, since a call after the loop runs it again, e.g. `u=z` counts in `for u in a b; do f() { curl $u; }; f; done; echo; u=z; f`.
    One inside that loop counts, since the command may sit in an inner loop of its body, e.g. `U=x` in `for U in a b; do while c; do curl $U; U=x; done; done`.
    An assignment that ends the loop body and one right after the loop have the same `next_command_id`, so both count, e.g. `U=c` in `for U in a b; do curl $U; U=c; done`.
    """
    if not (shell_command.in_loop_body or shell_command.in_function_body):
        return []
    later_assignments = [
        assignment
        for assignment in assignments_of_name
        if assignment.next_command_id > shell_command.id
    ]
    if not loop_item_assignments or shell_command.in_function_body:
        return later_assignments
    first_loop_item_assignment = loop_item_assignments[0]
    next_command_id_after_for_loop = (
        first_loop_item_assignment.next_command_id_after_for_loop
    )
    assert next_command_id_after_for_loop is not None
    return [
        assignment
        for assignment in later_assignments
        if assignment.next_command_id <= next_command_id_after_for_loop
    ]
