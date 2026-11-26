"""Extract where the content that the requests of one fetching program receive goes, from its row, its options, the routes of its stdout and the files it writes itself.

The same program can send its content to different places, e.g. `curl u` shows it in the result, `curl -o a.tgz u` saves it, `curl u > /dev/null` throws it away and `curl -I u` asks for none.
A file that the program writes as the value of an option that does not send the content there holds something else, e.g. the headers of `curl -D h.txt u`, so it is not where the content goes.
"""

from collections.abc import Sequence

from tb_internet_use.expanded_tool_call.model import (
    FileWriteChannel,
    OutputRoute,
    ProgramInvocation,
    RanCommand,
    WrittenFile,
)
from tb_internet_use.network_request.model import (
    ContentDiscarded,
    ContentPipedToCommand,
    ContentSaved,
    ContentShownInResult,
    NoContentRequested,
    ProgramContentRoute,
    ProgramOptionEffect,
    ReceivedContentDestination,
    UnknownProgramContentRoute,
    UnknownProgramOptionEffect,
    UnknownReceivedContentDestination,
)
from tb_internet_use.tool_call.model import (
    CaptureDestination,
    DiscardDestination,
    FileDestination,
    ResultDestination,
)

# The file that throws away what is written to it, as a program's own output file names it, e.g. `curl -o /dev/null u`.
_DISCARDING_FILE_PATH = "/dev/null"


def extract_received_content_destination(
    program_content_route: ProgramContentRoute | UnknownProgramContentRoute,
    program_option_effects: Sequence[ProgramOptionEffect | UnknownProgramOptionEffect],
    program_invocation: ProgramInvocation,
    ran_command: RanCommand,
    written_files: Sequence[WrittenFile],
    network_request_count: int,
) -> ReceivedContentDestination:
    """Extract where the received content of the requests of one program in a command goes, taking the first case below that fits.

    1. When an option asks for no content, e.g. `curl -I u`, or the row says `no_content`, e.g. `ping`, it is `NoContentRequested`.
    2. When the program gets more arguments when it runs, e.g. `xargs curl -O`, or an option has no row of the request catalog, e.g. `curl -K cfg u`, it is `UnknownReceivedContentDestination`, since either may send the content elsewhere as `-O` does.
    3. When an option sends the content to stdout, e.g. `curl -o - u`, or the row says `stdout`, no option sends the content to a file and the command writes no file of its own, e.g. `curl u > a.tgz`, it is the end of the stdout route.
    4. When the command writes files of its own that may hold the content, e.g. `curl -o a.tgz u`, it is `ContentSaved` with the path when there is one file and one request, or `ContentDiscarded` when that file is `/dev/null`, else `ContentSaved(None)`, also for `curl -o /dev/null u1 -o /dev/null u2`.
    5. When an option sends the content to a file, or the row says `own_file`, e.g. `pip install x`, it is `ContentSaved(None)`. The command then writes no file of its own that `expand_tool_calls` knows the path of, e.g. f of `curl --output-dir d -o f u`, which is d/f, or of `curl --output=f u`.
    6. When the row leaves the route blank, it is `UnknownReceivedContentDestination`.

    A file of its own may hold the content unless it is the value of an option whose effect is not `SENDS_CONTENT_TO_FILE`, e.g. h.txt of `curl -D h.txt u`, whose content goes to stdout, or of `curl -D h.txt u > b.txt`, whose content goes to b.txt.
    `program_option_effects` holds the answer of `NetworkRequestKnowledge` for each of `program_invocation.options`, at the same index, and `network_request_count` is the number of requests of the program in the command.
    The same order holds for a call that did not run, since `expand_tool_calls` lists the files that its words write too, so that a command gets the same destination whether it ran or not.
    """
    if (
        ProgramOptionEffect.ASKS_FOR_NO_CONTENT in program_option_effects
        or program_content_route == ProgramContentRoute.NO_CONTENT
    ):
        return NoContentRequested()
    if program_invocation.gets_more_arguments_at_run_time or any(
        isinstance(program_option_effect, UnknownProgramOptionEffect)
        for program_option_effect in program_option_effects
    ):
        return UnknownReceivedContentDestination()
    own_output_file_paths = _content_file_paths_of(
        _own_output_file_paths_of(ran_command.shell_command.id, written_files),
        program_invocation,
        program_option_effects,
    )
    sends_content_to_file = (
        ProgramOptionEffect.SENDS_CONTENT_TO_FILE in program_option_effects
    )
    if ProgramOptionEffect.SENDS_CONTENT_TO_STDOUT in program_option_effects or (
        not own_output_file_paths
        and not sends_content_to_file
        and program_content_route == ProgramContentRoute.STDOUT
    ):
        return _destination_of_stdout_routes(ran_command.stdout_routes)
    if len(own_output_file_paths) == 1 and network_request_count == 1:
        (own_output_file_path,) = own_output_file_paths
        if own_output_file_path == _DISCARDING_FILE_PATH:
            return ContentDiscarded()
        return ContentSaved(own_output_file_path)
    if own_output_file_paths:
        return ContentSaved(None)
    if sends_content_to_file or program_content_route == ProgramContentRoute.OWN_FILE:
        return ContentSaved(None)
    return UnknownReceivedContentDestination()


def _destination_of_stdout_routes(
    stdout_routes: Sequence[OutputRoute],
) -> ReceivedContentDestination:
    """Give where content sent to stdout goes, e.g. `ContentShownInResult` for `curl u`, `ContentSaved("a.tgz")` for `curl u > a.tgz` and `ContentPipedToCommand` for `curl u | tar xz`.

    With several routes, e.g. `curl u | tee log`, no single destination is the one of the content, so it is unknown.
    A capture such as `x=$(curl u)` hands the content to a command that has no id, so it is unknown too.
    """
    if len(stdout_routes) != 1:
        return UnknownReceivedContentDestination()
    (stdout_route,) = stdout_routes
    if stdout_route.pipe_reader_command_ids:
        return ContentPipedToCommand(
            stdout_route.pipe_reader_command_ids[0], stdout_route.visibility_at_end
        )
    match stdout_route.end:
        case ResultDestination():
            return ContentShownInResult()
        case FileDestination(path=path):
            return ContentSaved(path)
        case DiscardDestination():
            return ContentDiscarded()
        case CaptureDestination():
            return UnknownReceivedContentDestination()


def _content_file_paths_of(
    own_output_file_paths: Sequence[str],
    program_invocation: ProgramInvocation,
    program_option_effects: Sequence[ProgramOptionEffect | UnknownProgramOptionEffect],
) -> tuple[str, ...]:
    """Give the files of a command's own that may hold the content, i.e. all but the values of options whose effect is not `SENDS_CONTENT_TO_FILE`, e.g. a.tgz and not h.txt of `curl -o a.tgz -D h.txt u`."""
    other_file_values = {
        program_option.value
        for program_option, program_option_effect in zip(
            program_invocation.options, program_option_effects, strict=True
        )
        if program_option.value is not None
        and program_option_effect != ProgramOptionEffect.SENDS_CONTENT_TO_FILE
    }
    return tuple(
        path for path in own_output_file_paths if path not in other_file_values
    )


def _own_output_file_paths_of(
    command_id: int, written_files: Sequence[WrittenFile]
) -> tuple[str, ...]:
    """Give the paths of the files that a command of the call writes itself, e.g. `a.tgz` for `curl -o a.tgz u`, apart from those it writes by a redirect."""
    return tuple(
        written_file.path
        for written_file in written_files
        if any(
            writer.command_id == command_id
            and writer.channel == FileWriteChannel.OWN_OUTPUT_FILE
            for writer in written_file.writers
        )
    )
