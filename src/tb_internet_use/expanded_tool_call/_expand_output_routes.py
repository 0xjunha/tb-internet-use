"""Follow a command's stdout or stderr through the commands that read it from a pipe to each place where it ends, with how much of it is still there.

Output reaches the call's result or a file only through its pipe readers, e.g. `curl u | tail -1` shows only what tail keeps, and `curl u | tee log` also puts all of it in log.
How much a reader passes on is a fact of its program row, so a reader without a fact leaves the share unknown, e.g. `curl u | mytool`, and so does a reader whose program gets the piped input as arguments, e.g. `curl u | xargs cat`.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from tb_internet_use.expanded_tool_call.model import (
    OutputRoute,
    OutputVisibility,
    ProgramBehavior,
    ProgramInvocation,
    ProgramWordRole,
    UnknownProgramBehavior,
    UnknownProgramInvocation,
    UnknownProgramWordRole,
)
from tb_internet_use.tool_call.model import (
    FileDestination,
    OutputDestination,
    PipeDestination,
    ShellCommand,
)

# The roles of a word that names a file the program writes, with whether it adds to the file, i.e. `appends` of a `FileDestination`.
_APPENDS_OF_WRITTEN_FILE_ROLE = {
    ProgramWordRole.WRITTEN_FILE: False,
    ProgramWordRole.APPENDED_FILE: True,
}
# The shares from the one that hides most to the one that hides least, so that a route keeps the first one that any of its readers has.
_VISIBILITIES_FROM_LEAST_SHOWN = (
    OutputVisibility.NONE,
    OutputVisibility.UNKNOWN,
    OutputVisibility.PARTIAL,
    OutputVisibility.WHOLE,
)


def expand_output_routes(
    output_destination: OutputDestination,
    pipe_readers_by_command_id: Mapping[int, PipeReader],
) -> tuple[OutputRoute, ...]:
    """Follow one stdout or stderr of a command through its pipe readers to each of its ends, the end of the last reader first.

    `output_destination` is the stdout or stderr of the command as `parse_shell_text` gives it, and `pipe_readers_by_command_id` holds every command of the text that a pipe leads to.
    A reader that writes the piped output to files adds one route per file, ending there, e.g. log in `curl u | tee log | tail -1`.
    The share at the end of a route is the least one that its readers pass on, e.g. `NONE` for `curl u | grep a | wc -c` and `PARTIAL` for `curl u | grep a | cat`.
    """
    pipe_reader_command_ids: list[int] = []
    pipe_reader_visibilities: list[OutputVisibility] = []
    file_routes: list[OutputRoute] = []
    destination = output_destination
    while isinstance(destination, PipeDestination):
        pipe_reader = pipe_readers_by_command_id[destination.reader_id]
        pipe_reader_command_ids.append(destination.reader_id)
        pipe_reader_visibilities.append(pipe_reader.visibility_of_piped_input)
        file_routes += [
            OutputRoute(
                tuple(pipe_reader_command_ids),
                file_destination,
                _visibility_at_end_from(pipe_reader_visibilities),
            )
            for file_destination in pipe_reader.piped_input_file_destinations
        ]
        destination = pipe_reader.shell_command.stdout
    end_route = OutputRoute(
        tuple(pipe_reader_command_ids),
        destination,
        _visibility_at_end_from(pipe_reader_visibilities),
    )
    return (end_route, *file_routes)


@dataclass(frozen=True, slots=True)
class PipeReader:
    """Command of one shell text that reads another command's output through a pipe, with what its program does with that output, made by `pipe_reader_of` and read by `expand_output_routes`."""

    shell_command: ShellCommand
    # The share of the piped output that it passes on to its own stdout, from the row of its innermost program.
    visibility_of_piped_input: OutputVisibility
    # The files that it writes all of the piped output to, e.g. log in `tee log`, in the order of its words.
    piped_input_file_destinations: tuple[FileDestination, ...]


def pipe_reader_of(
    shell_command: ShellCommand,
    program_invocations: Sequence[ProgramInvocation | UnknownProgramInvocation],
    word_roles: Sequence[ProgramWordRole | UnknownProgramWordRole | None],
    program_behaviors: Sequence[ProgramBehavior | UnknownProgramBehavior],
) -> PipeReader:
    """Build the `PipeReader` of a command that reads a pipe, from the row of its innermost program, e.g. tail in `sudo tail -1`.

    `program_invocations`, `word_roles` and `program_behaviors` are what `expand_program_invocations` gave for the command, so the door is not asked again and the row of the reader is counted once.
    The program writes the piped output to a file only when its row says that it passes on all of it and a word names a file it writes, e.g. log in `tee log` or `tee -a log`.
    That is how `program_behaviors.csv` tells a program that copies its stdin to files, e.g. tee, from one that writes something else, e.g. curl in `curl -o f -d @- u`.
    """
    visibility_of_piped_input = _visibility_of_piped_input_of(
        program_invocations, program_behaviors
    )
    if visibility_of_piped_input != OutputVisibility.WHOLE:
        return PipeReader(shell_command, visibility_of_piped_input, ())
    piped_input_file_destinations = tuple(
        FileDestination(word, _APPENDS_OF_WRITTEN_FILE_ROLE[word_role])
        for word, word_role in zip(shell_command.words, word_roles, strict=True)
        if isinstance(word_role, ProgramWordRole)
        and word_role in _APPENDS_OF_WRITTEN_FILE_ROLE
    )
    return PipeReader(
        shell_command, visibility_of_piped_input, piped_input_file_destinations
    )


def _visibility_of_piped_input_of(
    program_invocations: Sequence[ProgramInvocation | UnknownProgramInvocation],
    program_behaviors: Sequence[ProgramBehavior | UnknownProgramBehavior],
) -> OutputVisibility:
    """Give the share of piped input that the innermost program of a command passes on, from its row.

    The share is unknown when the command has no program word, e.g. a lone redirect, when no row covers the innermost program, e.g. mytool, and when the innermost program gets arguments at run time.
    In the last case the program before it turns the piped input into arguments, so the innermost program does not read the pipe, e.g. cat in `ls | xargs cat` shows the files that ls names.
    """
    if not program_invocations:
        return OutputVisibility.UNKNOWN
    innermost_program_invocation = program_invocations[-1]
    innermost_program_behavior = program_behaviors[-1]
    if (
        isinstance(innermost_program_invocation, UnknownProgramInvocation)
        or isinstance(innermost_program_behavior, UnknownProgramBehavior)
        or innermost_program_invocation.gets_more_arguments_at_run_time
    ):
        return OutputVisibility.UNKNOWN
    return innermost_program_behavior.visibility_of_piped_input


def _visibility_at_end_from(
    pipe_reader_visibilities: Sequence[OutputVisibility],
) -> OutputVisibility:
    """Find the share left after a run of pipe readers, `NONE` if any shows none, else `UNKNOWN` if any is unknown, else `PARTIAL` if any passes on some, else `WHOLE`."""
    return next(
        (
            visibility
            for visibility in _VISIBILITIES_FROM_LEAST_SHOWN
            if visibility in pipe_reader_visibilities
        ),
        OutputVisibility.WHOLE,
    )
