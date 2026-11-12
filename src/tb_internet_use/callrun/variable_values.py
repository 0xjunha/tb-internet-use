"""Find the literal values that the variables in a command's words and redirect file paths hold when it runs, from the assignments in its text.

A target is often a variable, e.g. `curl $URL` after `URL=https://a.org`, or `pip install $p` in `for p in a b`.
"""

import re
from collections.abc import Mapping, Sequence

from tb_internet_use.callrun.model import VariableValues
from tb_internet_use.shell.model import (
    FileDestination,
    ParsedShellText,
    ShellCommand,
    VariableAssignment,
)
from tb_internet_use.shell.programs import program_words

# A variable used as `$NAME` or `${NAME}`. Forms such as `${NAME:-x}` are not resolved.
_PLAIN_VARIABLE = re.compile(r"\$(?:\{(\w+)\}|(\w+))")


def command_variable_values(
    command: ShellCommand, parsed_text: ParsedShellText
) -> tuple[VariableValues, ...]:
    """Find the literal values that each `$NAME` in a command's words and redirect file paths has when it runs, e.g. LOG in `curl u > $LOG` or `tail < $LOG`.

    A name gets no values when a value before the command is computed, e.g. `A=$(date)`, or read, e.g. `read A`.
    """
    file_paths = [
        destination.path
        for destination in (command.stdout, command.stderr)
        if isinstance(destination, FileDestination)
    ]
    if command.stdin_file_path is not None:
        file_paths.append(command.stdin_file_path)
    words = (*command.words, *file_paths)
    return tuple(
        values
        for name in dict.fromkeys(
            n for word in words for n in plain_variable_names(word)
        )
        if (values := _values_of_name(name, command, parsed_text)) is not None
    )


def word_with_single_values_filled(
    word: str, variable_values: Sequence[VariableValues]
) -> str:
    """Fill in the variables of a word that have exactly one value, e.g. fetch.log for `$LOG` after `LOG=fetch.log`."""
    return filled_word(
        word, {v.name: v.values[0] for v in variable_values if len(v.values) == 1}
    )


def filled_word(word: str, value_of_name: Mapping[str, str]) -> str:
    """Fill in the variables of a word whose values are given, keeping the others as written, e.g. a.org/x for `$U/x`."""
    return _PLAIN_VARIABLE.sub(
        lambda m: value_of_name.get(m.group(1) or m.group(2), m.group(0)), word
    )


def plain_variable_names(word: str) -> tuple[str, ...]:
    """List the names a word uses as `$NAME` or `${NAME}`, in order and without repeats."""
    return tuple(
        dict.fromkeys(m.group(1) or m.group(2) for m in _PLAIN_VARIABLE.finditer(word))
    )


def _values_of_name(
    name: str, command: ShellCommand, parsed_text: ParsedShellText
) -> VariableValues | None:
    """Find the values of one name before a command, or None when they are unknown.

    In the body of the innermost for loop over the name, with no other assignment of it inside, the command takes each item in turn.
    Otherwise the command runs with one of the values, since the text does not say which assignment ran last, e.g. in if branches.
    """
    assignments = [
        a
        for a in parsed_text.assignments
        if a.name == name and a.next_command_id <= command.id
    ]
    if not assignments or any(a.value is None for a in assignments):
        return None
    if _is_set_by_read_command_before(name, command, parsed_text):
        return None
    loop_items = _items_of_loop_around(command, assignments)
    chosen = loop_items or assignments
    values = tuple(dict.fromkeys(a.value for a in chosen if a.value is not None))
    return VariableValues(name, values, takes_each_value_in_turn=bool(loop_items))


def _items_of_loop_around(
    command: ShellCommand, assignments: Sequence[VariableAssignment]
) -> list[VariableAssignment]:
    """Take the items of the innermost for loop over the name whose body holds the command, if nothing reassigns the name inside it.

    Empty when the command lies in no such loop. The assignments are in text order, so one after the items lies in the loop body.
    Two loops over one name that start at the same command cannot be told apart, e.g. in `for U in a; do for U in b; do curl $U`.
    """
    loop_starts = [
        a.next_command_id
        for a in assignments
        if a.next_command_id_after_for_loop is not None
        and a.next_command_id <= command.id < a.next_command_id_after_for_loop
    ]
    if not loop_starts:
        return []
    loop_start = max(loop_starts)
    item_positions = [
        position
        for position, a in enumerate(assignments)
        if a.next_command_id == loop_start
        and a.next_command_id_after_for_loop is not None
    ]
    if item_positions[-1] != len(assignments) - 1:
        return []
    return [assignments[position] for position in item_positions]


def _is_set_by_read_command_before(
    name: str, command: ShellCommand, parsed_text: ParsedShellText
) -> bool:
    """Check whether a `read` command before the command sets the name, e.g. `read A` or `while read A`."""
    return any(
        (words := program_words(other))[:1] == ("read",) and name in words[1:]
        for other in parsed_text.commands
        if other.id < command.id
    )
