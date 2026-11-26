"""Read the commands of one shell text into the programs they run, the values of their variables and the routes of their output, with the role of each word.

A command's words alone do not say what it runs or where its output ends, e.g. `sudo curl u | tail -1` runs curl under sudo and shows only what tail keeps.
A variable can also get its value from a command as the text runs, e.g. U in `read U; curl $U`, which only the role of the word `U` shows.
"""

from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tb_internet_use.expanded_tool_call._expand_output_routes import (
    PipeReader,
    expand_output_routes,
    pipe_reader_of,
)
from tb_internet_use.expanded_tool_call._expand_program_invocations import (
    expand_program_invocations,
)
from tb_internet_use.expanded_tool_call._expand_variable_values import (
    expand_variable_values,
)
from tb_internet_use.expanded_tool_call.model import (
    ProgramBehavior,
    ProgramInvocation,
    ProgramWordRole,
    RanCommand,
    UnknownProgramBehavior,
    UnknownProgramInvocation,
    UnknownProgramWordRole,
)
from tb_internet_use.tool_call.model import (
    ParsedShellText,
    PipeDestination,
    ShellCommand,
    VariableAssignment,
)

if TYPE_CHECKING:
    # `ExpandedToolCallKnowledge` is passed in and named in annotations only, so that this module never loads `knowledge/` itself.
    from tb_internet_use.knowledge.expanded_tool_call_knowledge import (
        ExpandedToolCallKnowledge,
    )

# No pipe readers, for a text that no other text runs, e.g. the command string of a call.
_NO_PIPE_READERS: Mapping[int, PipeReader] = {}


def expand_ran_commands(
    parsed_shell_text: ParsedShellText,
    *,
    outer_variable_assignments: Sequence[VariableAssignment] = (),
    outer_pipe_readers_by_command_id: Mapping[int, PipeReader] = _NO_PIPE_READERS,
    knowledge: ExpandedToolCallKnowledge,
    judgment_rule_use_counts: Counter[str],
) -> RanCommandsOfShellText:
    """Read every command of a shell text into a `RanCommand`, in the order of the text, and keep the roles of its words, the rows of its programs, the assignments and the pipe readers that it reads on the way.

    `outer_variable_assignments` are the assignments of an outer text that this text sees, for a text that runs in the calling shell, e.g. the text of `eval`.
    They come before the assignments of this text, already with the names that outer commands set at run time in place, as `RanCommandsOfShellText.variable_assignments` of the outer text gives them.
    A word whose role is `VARIABLE_NAME_SET_AT_RUN_TIME`, e.g. U in `read U`, puts an assignment without a value in its place among the assignments, so a later command does not take an earlier literal value as certain.
    A command whose row gives its arguments that role but whose words could not all be read, e.g. `read -E U` without a row for `-E`, may set any variable, so it puts such an assignment for every name assigned in the text.
    `outer_pipe_readers_by_command_id` are the pipe readers of the texts that run this one, since a command of this text takes the output destination of the command that runs the text, e.g. the pipe to tail in `bash fetch.sh | tail -1`.
    This function records no write or use of a file, so a word that names a file only gets its role here.
    Every use of a rule of `judgment_rules.py` by the pieces it calls adds one to `judgment_rule_use_counts`.
    """
    shell_commands = parsed_shell_text.commands
    expanded_program_invocations_of_commands = [
        expand_program_invocations(
            shell_command,
            knowledge=knowledge,
            judgment_rule_use_counts=judgment_rule_use_counts,
        )
        for shell_command in shell_commands
    ]
    program_invocations_of_commands = tuple(
        program_invocations
        for program_invocations, _, _, _, _ in expanded_program_invocations_of_commands
    )
    word_roles_of_commands = tuple(
        word_roles
        for _, word_roles, _, _, _ in expanded_program_invocations_of_commands
    )
    program_behaviors_of_commands = tuple(
        program_behaviors
        for _, _, program_behaviors, _, _ in expanded_program_invocations_of_commands
    )
    variable_assignments = _variable_assignments_with_names_set_at_run_time_from(
        shell_commands,
        word_roles_of_commands,
        (*outer_variable_assignments, *parsed_shell_text.variable_assignments),
        command_ids_with_unread_variable_names=_command_ids_with_unread_variable_names_of(
            shell_commands,
            program_invocations_of_commands,
            program_behaviors_of_commands,
        ),
    )
    pipe_reader_command_ids = _pipe_reader_command_ids_of(shell_commands)
    pipe_readers_by_command_id = {
        **outer_pipe_readers_by_command_id,
        **{
            shell_command.id: pipe_reader_of(
                shell_command, program_invocations, word_roles, program_behaviors
            )
            for shell_command, program_invocations, word_roles, program_behaviors in zip(
                shell_commands,
                program_invocations_of_commands,
                word_roles_of_commands,
                program_behaviors_of_commands,
                strict=True,
            )
            if shell_command.id in pipe_reader_command_ids
        },
    }
    ran_commands = tuple(
        RanCommand(
            shell_command=shell_command,
            program_invocations=program_invocations,
            variable_values=expand_variable_values(
                shell_command,
                variable_assignments,
                judgment_rule_use_counts=judgment_rule_use_counts,
            ),
            stdout_routes=expand_output_routes(
                shell_command.stdout, pipe_readers_by_command_id
            ),
            stderr_routes=expand_output_routes(
                shell_command.stderr, pipe_readers_by_command_id
            ),
        )
        for shell_command, program_invocations in zip(
            shell_commands, program_invocations_of_commands, strict=True
        )
    )
    return RanCommandsOfShellText(
        ran_commands,
        word_roles_of_commands,
        program_behaviors_of_commands,
        tuple(
            program_word_indexes
            for _, _, _, program_word_indexes, _ in expanded_program_invocations_of_commands
        ),
        tuple(
            run_time_argument_roles
            for _, _, _, _, run_time_argument_roles in expanded_program_invocations_of_commands
        ),
        variable_assignments,
        pipe_readers_by_command_id,
    )


@dataclass(frozen=True, slots=True)
class RanCommandsOfShellText:
    """Commands of one shell text as `expand_ran_commands` reads them, with the facts read on the way that the piece following the texts they run needs again.

    That piece needs the row of a program, e.g. whether `eval` runs its text in the calling shell, and the assignments that a text run by `eval` sees, without asking `ExpandedToolCallKnowledge` again, which would count the row twice.
    """

    ran_commands: tuple[RanCommand, ...]
    # The role of each word, one tuple per command at the index of its `RanCommand`.
    word_roles_of_commands: tuple[
        tuple[ProgramWordRole | UnknownProgramWordRole | None, ...], ...
    ]
    # The row of each program, one tuple per command at the index of its `RanCommand`, at the index of the program in `program_invocations`.
    program_behaviors_of_commands: tuple[
        tuple[ProgramBehavior | UnknownProgramBehavior, ...], ...
    ]
    # The 0-based index in `ShellCommand.words` of the word of each program, laid out like `program_behaviors_of_commands`.
    program_word_indexes_of_commands: tuple[tuple[int, ...], ...]
    # The role that the arguments each program gets at run time take, laid out like `program_behaviors_of_commands`, None for a program that gets none.
    run_time_argument_roles_of_commands: tuple[
        tuple[ProgramWordRole | UnknownProgramWordRole | None, ...], ...
    ]
    # The outer assignments, then those of the text, with an assignment without a value for each variable that a command sets at run time, in text order.
    variable_assignments: tuple[VariableAssignment, ...]
    # The pipe readers of the outer texts and of this text by command id, which the output of a command of a text that this text runs can lead to, e.g. tail for curl in fetch.sh of `bash fetch.sh | tail -1`.
    pipe_readers_by_command_id: Mapping[int, PipeReader]


def _variable_assignments_with_names_set_at_run_time_from(
    shell_commands: Sequence[ShellCommand],
    word_roles_of_commands: Sequence[
        Sequence[ProgramWordRole | UnknownProgramWordRole | None]
    ],
    variable_assignments: Sequence[VariableAssignment],
    *,
    command_ids_with_unread_variable_names: Collection[int],
) -> tuple[VariableAssignment, ...]:
    """Put an assignment without a value for each variable that a command sets at run time among the assignments of a text, in text order.

    The variables of a command with id N are the words whose role is `VARIABLE_NAME_SET_AT_RUN_TIME`, in word order, e.g. A, then B for `read A B`.
    For a command among `command_ids_with_unread_variable_names` they are every name of `variable_assignments` and of those put so far, in the order they first appear, since its unread words may name any of them.
    Each gets `VariableAssignment(name, None, N + 1, None)`, put before the first assignment whose `next_command_id` is greater than N, so that `read U; for U in a b; do curl $U; done` still takes the items in turn.
    A word with an expansion names a variable only when the command runs, e.g. `$X` in `read $X`, so it gives no assignment.
    `expand_ran_commands` builds `command_ids_with_unread_variable_names` from the rows that `expand_program_invocations` gave for each command, and keeps what this gives, so that a text run by `eval` in that text sees the outer assignments with these in place.
    """
    variable_assignments_in_text_order = list(variable_assignments)
    for shell_command, word_roles in zip(
        shell_commands, word_roles_of_commands, strict=True
    ):
        if shell_command.id in command_ids_with_unread_variable_names:
            names_set_at_run_time = list(
                dict.fromkeys(
                    variable_assignment.name
                    for variable_assignment in variable_assignments_in_text_order
                )
            )
        else:
            expansion_word_indexes = frozenset(shell_command.expansion_word_indexes)
            names_set_at_run_time = [
                word
                for word_index, (word, word_role) in enumerate(
                    zip(shell_command.words, word_roles, strict=True)
                )
                if word_role == ProgramWordRole.VARIABLE_NAME_SET_AT_RUN_TIME
                and word_index not in expansion_word_indexes
            ]
        insertion_index = next(
            (
                variable_assignment_index
                for variable_assignment_index, variable_assignment in enumerate(
                    variable_assignments_in_text_order
                )
                if variable_assignment.next_command_id > shell_command.id
            ),
            len(variable_assignments_in_text_order),
        )
        variable_assignments_in_text_order[insertion_index:insertion_index] = [
            VariableAssignment(name, None, shell_command.id + 1, None)
            for name in names_set_at_run_time
        ]
    return tuple(variable_assignments_in_text_order)


def _command_ids_with_unread_variable_names_of(
    shell_commands: Sequence[ShellCommand],
    program_invocations_of_commands: Sequence[
        Sequence[ProgramInvocation | UnknownProgramInvocation]
    ],
    program_behaviors_of_commands: Sequence[
        Sequence[ProgramBehavior | UnknownProgramBehavior]
    ],
) -> frozenset[int]:
    """Collect the ids of the commands with a program whose row gives its arguments the role `VARIABLE_NAME_SET_AT_RUN_TIME` and whose words were not all read, e.g. `read -E U` without a row for `-E`."""
    return frozenset(
        shell_command.id
        for shell_command, program_invocations, program_behaviors in zip(
            shell_commands,
            program_invocations_of_commands,
            program_behaviors_of_commands,
            strict=True,
        )
        if any(
            isinstance(program_invocation, ProgramInvocation)
            and program_invocation.unread_words
            and isinstance(program_behavior, ProgramBehavior)
            and program_behavior.argument_role
            == ProgramWordRole.VARIABLE_NAME_SET_AT_RUN_TIME
            for program_invocation, program_behavior in zip(
                program_invocations, program_behaviors, strict=True
            )
        )
    )


def _pipe_reader_command_ids_of(
    shell_commands: Sequence[ShellCommand],
) -> frozenset[int]:
    """Collect the ids of the commands that a stdout or stderr of the text leads to through a pipe."""
    return frozenset(
        output_destination.reader_id
        for shell_command in shell_commands
        for output_destination in (shell_command.stdout, shell_command.stderr)
        if isinstance(output_destination, PipeDestination)
    )
