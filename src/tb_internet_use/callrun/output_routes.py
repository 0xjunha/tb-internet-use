"""Follow a command's stdout or stderr through the commands that read it from a pipe to where it ends.

A request's output reaches the call's result only through its pipe readers, e.g. `curl u | tail -1` shows only what tail keeps.
"""

from collections.abc import Mapping

from tb_internet_use.callrun.model import OutputRoute
from tb_internet_use.program.arguments import parse_arguments
from tb_internet_use.shell.model import (
    FileDestination,
    OutputDestination,
    PipeDestination,
    ShellCommand,
)
from tb_internet_use.shell.programs import program_words


def output_routes(
    destination: OutputDestination, command_of_id: Mapping[int, ShellCommand]
) -> tuple[OutputRoute, ...]:
    """Follow an output destination through its pipe readers to each of its ends, the last stage's end first.

    A `tee` on the way adds one more end per file it writes, e.g. log in `curl u | tee log | tail -1`.
    """
    pipe_reader_ids: list[int] = []
    tee_routes: list[OutputRoute] = []
    while isinstance(destination, PipeDestination):
        reader = command_of_id[destination.reader_id]
        pipe_reader_ids.append(reader.id)
        tee_routes += [
            OutputRoute(tuple(pipe_reader_ids), file)
            for file in tee_file_destinations(reader)
        ]
        destination = reader.stdout
    return (OutputRoute(tuple(pipe_reader_ids), destination), *tee_routes)


def tee_file_destinations(command: ShellCommand) -> tuple[FileDestination, ...]:
    """List the files a `tee` command writes its input to, appending with -a, e.g. log in `tee -a log`."""
    words = program_words(command)
    if words[:1] != ("tee",):
        return ()
    parsed = parse_arguments("tee", words[1:])
    appends = parsed.has_option("-a", "--append")
    return tuple(
        FileDestination(path, appends)
        for path in parsed.plain_arguments
        if path != "/dev/null"
    )
