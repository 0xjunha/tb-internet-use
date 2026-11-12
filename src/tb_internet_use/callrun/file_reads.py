"""Find the calls that read the files where a call's output went, so that output shown only by a later read can be linked to it.

Output can show up only when a call reads a file, e.g. `tail fetch.log` after `bash fetch.sh > fetch.log`,
or a read of the file where the harness saved a background command's output.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import NamedTuple

from tb_internet_use.callrun.model import (
    FileReader,
    FileText,
    PollInputText,
    RanCommand,
    RanShellText,
    RedirectedOutputReads,
    ScriptStepText,
    StdinText,
)
from tb_internet_use.callrun.paths import can_name_same_file
from tb_internet_use.callrun.variable_values import word_with_single_values_filled
from tb_internet_use.program.arguments import file_arguments, parse_arguments
from tb_internet_use.program.catalog_loader import file_reading_program_names
from tb_internet_use.shell.model import FileDestination
from tb_internet_use.shell.programs import gets_arguments_at_run_time, program_words
from tb_internet_use.toolcall.model import (
    ReadFileAction,
    ToolCall,
    WriteFileAction,
    action_steps_with_index,
    may_have_run,
)


class _RunOrderPosition(NamedTuple):
    """Position of a read or write in the trial, compared to tell which comes first."""

    # The 0-based index of the call in the trial.
    call_index: int
    # The 0-based index of the step in a tool script, or 0 for any other call.
    step_index: int
    # The id of the call's own command that the read or write runs under, or -1 for a tool step.
    command_id: int


@dataclass(frozen=True, slots=True)
class _FileRead:
    """Read of a path by a read tool or a command such as `tail fetch.log`, at its position in the trial."""

    position: _RunOrderPosition
    # The path with the variables of one value filled in, e.g. fetch.log for `$LOG` after `LOG=fetch.log`.
    path: str
    reader: FileReader


@dataclass(frozen=True, slots=True)
class _FileWrite:
    """Write of a path by a redirect, a `tee` or a write tool, at its position in the trial."""

    position: _RunOrderPosition
    # The path as the writer names it, e.g. `$LOG` in `curl u > $LOG`.
    written_path: str
    # The path with the variables of one value filled in.
    path: str
    # It replaces what the file held, e.g. `>` but not `>>` or `tee -a`.
    replaces_content: bool


class TrialFileReads:
    """Index of the file reads and writes of one trial, built once by `expand_calls` to fill the read fields of each `CallRun`."""

    def __init__(
        self,
        calls: Sequence[ToolCall],
        shell_texts_of_calls: Sequence[tuple[RanShellText, ...]],
    ) -> None:
        self._calls = calls
        self._reads: list[_FileRead] = []
        self._writes: list[_FileWrite] = []
        # The writes of each call's commands, which send its output to files.
        self._output_writes_of_call: list[list[_FileWrite]] = []
        reading_programs = file_reading_program_names()
        for call_index, (call, shell_texts) in enumerate(
            zip(calls, shell_texts_of_calls, strict=True)
        ):
            # A call that the tool did not run reads and writes no file, e.g. a rejected `cat log` shows no content and a rejected write tool or `curl u > log` leaves log as it was.
            if not may_have_run(call):
                self._output_writes_of_call.append([])
                continue
            for step_index, step in action_steps_with_index(call.action):
                position = _RunOrderPosition(call_index, step_index or 0, -1)
                if isinstance(step, ReadFileAction) and step.path:
                    self._reads.append(
                        _FileRead(position, step.path, FileReader(call.raw.key, None))
                    )
                elif isinstance(step, WriteFileAction) and step.path:
                    self._writes.append(
                        _FileWrite(
                            position, step.path, step.path, replaces_content=True
                        )
                    )
            placed_commands = _placed_commands(call_index, shell_texts)
            ran_command_of_id = {c.command.id: c for _, c in placed_commands}
            output_writes = [
                write
                for position, ran_command in placed_commands
                for write in _output_file_writes(
                    position, ran_command, ran_command_of_id
                )
            ]
            self._writes += output_writes
            self._output_writes_of_call.append(output_writes)
            for position, ran_command in placed_commands:
                words = program_words(ran_command.command)
                if words[:1] and words[0] in reading_programs:
                    self._reads += _command_reads(
                        position,
                        ran_command,
                        FileReader(call.raw.key, ran_command.command.id),
                    )

    def harness_output_file_readers(self, call_index: int) -> tuple[FileReader, ...]:
        """List the later calls that read the file where the harness saved a call's whole result."""
        output = self._calls[call_index].output
        if output is None or output.output_path is None:
            return ()
        return _unique_readers(
            read
            for read in self._reads
            if read.position.call_index > call_index
            and can_name_same_file(read.path, output.output_path)
        )

    def redirected_output_reads(
        self, call_index: int
    ) -> tuple[RedirectedOutputReads, ...]:
        """List, for each file that commands of a call send output to, the calls that read it before a later call replaces it."""
        first_write_of_path: dict[str, _FileWrite] = {}
        for write in self._output_writes_of_call[call_index]:
            first_write_of_path.setdefault(write.written_path, write)
        reads = []
        for written_path, first_write in first_write_of_path.items():
            replaced_at = min(
                (
                    later.position
                    for later in self._writes
                    if later.replaces_content
                    and later.position.call_index > call_index
                    and can_name_same_file(later.path, first_write.path)
                ),
                default=None,
            )
            readers = _unique_readers(
                read
                for read in self._reads
                if first_write.position < read.position
                and (replaced_at is None or read.position < replaced_at)
                and can_name_same_file(read.path, first_write.path)
            )
            if readers:
                reads.append(RedirectedOutputReads(written_path, readers))
        return tuple(reads)


def _placed_commands(
    call_index: int, shell_texts: Sequence[RanShellText]
) -> list[tuple[_RunOrderPosition, RanCommand]]:
    """Give each command of a call the position it runs at, which for a command of a file or heredoc is its runner's position."""
    position_of_command: dict[int, _RunOrderPosition] = {}
    placed: list[tuple[_RunOrderPosition, RanCommand]] = []
    for text in shell_texts:
        for ran_command in text.commands or ():
            command_id = ran_command.command.id
            match text.source:
                case (
                    FileText(runner_command_id=runner_id)
                    | StdinText(runner_command_id=runner_id)
                ):
                    position = position_of_command[runner_id]
                case (
                    ScriptStepText(step_index=step_index)
                    | PollInputText(step_index=step_index)
                ):
                    position = _RunOrderPosition(
                        call_index, step_index or 0, command_id
                    )
                case _:
                    position = _RunOrderPosition(call_index, 0, command_id)
            position_of_command[command_id] = position
            placed.append((position, ran_command))
    return placed


def _output_file_writes(
    position: _RunOrderPosition,
    ran_command: RanCommand,
    ran_command_of_id: Mapping[int, RanCommand],
) -> list[_FileWrite]:
    """List the files where a command's stdout or stderr ends, e.g. fetch.log for `curl u > fetch.log` or `curl u | tee fetch.log`.

    A path's variables are filled with the values of the command that writes the file, which is the last pipe reader on the way.
    """
    writes = []
    for route in (*ran_command.stdout_routes, *ran_command.stderr_routes):
        if not isinstance(route.end, FileDestination):
            continue
        writer = (
            ran_command_of_id[route.pipe_reader_ids[-1]]
            if route.pipe_reader_ids
            else ran_command
        )
        filled_path = word_with_single_values_filled(
            route.end.path, writer.variable_values
        )
        writes.append(
            _FileWrite(
                position,
                route.end.path,
                filled_path,
                replaces_content=not route.end.appends,
            )
        )
    return writes


def _command_reads(
    position: _RunOrderPosition, ran_command: RanCommand, reader: FileReader
) -> list[_FileRead]:
    """List the files that a reading command reads, i.e. the files it names, e.g. fetch.log in `tail -n 5 fetch.log`, and its stdin file, e.g. log in `grep x < log`.

    Option values and patterns name no file read, e.g. 5 and x in these commands.
    A command reads its stdin file only when it names no file or names `-`, and not when xargs or `find -exec` gives it its arguments.
    """
    command = ran_command.command
    program_name, *arguments = program_words(command)
    named_paths = file_arguments(
        program_name, parse_arguments(program_name, tuple(arguments))
    )
    paths = [path for path in named_paths if path != "-"]
    reads_stdin = not named_paths or "-" in named_paths
    if (
        command.stdin_file_path is not None
        and reads_stdin
        and not gets_arguments_at_run_time(command)
    ):
        paths.append(command.stdin_file_path)
    return [
        _FileRead(
            position,
            word_with_single_values_filled(path, ran_command.variable_values),
            reader,
        )
        for path in paths
    ]


def _unique_readers(reads: Iterable[_FileRead]) -> tuple[FileReader, ...]:
    """List the readers of some reads in order, each once."""
    return tuple(dict.fromkeys(read.reader for read in reads))
