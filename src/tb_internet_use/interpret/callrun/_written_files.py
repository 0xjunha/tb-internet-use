"""Track the content of the files that the calls of a trial write, so that a later command that runs a file can be read.

A request can sit in a file that an earlier call wrote, e.g. a `curl` line in fetch.sh that a write tool wrote before `bash fetch.sh` ran it.
"""

from dataclasses import dataclass

from tb_internet_use.interpret.callrun._output_routes import tee_file_destinations
from tb_internet_use.interpret.callrun._paths import can_name_same_file
from tb_internet_use.parse.program.arguments import file_arguments, parse_arguments
from tb_internet_use.parse.shell.model import FileDestination, ShellCommand
from tb_internet_use.parse.shell.programs import program_words
from tb_internet_use.parse.toolcall.model import (
    Action,
    EditFileAction,
    ToolCallKey,
    WriteFileAction,
)


@dataclass(frozen=True, slots=True)
class WrittenFile:
    """State of one file after the latest write to it, read when a later command runs the file."""

    # The path as the writer names it.
    path: str
    # None when the trial does not show the content, e.g. after `echo x > f.sh`, `sed -i` or a copy of an unknown file.
    content: str | None
    written_by: ToolCallKey


class WrittenFiles:
    """State of the files that the calls of a trial wrote so far, kept while the calls are read in order."""

    def __init__(self) -> None:
        # The latest write of each path string, in the order of the writes.
        self._latest_write_of_path: dict[str, WrittenFile] = {}

    def record_tool_step(self, step: Action, call_key: ToolCallKey) -> None:
        """Record what a write or edit step writes, e.g. the content of a `WriteFileAction`."""
        if isinstance(step, WriteFileAction) and step.path:
            self._record_latest_write(step.path, step.content, call_key)
        elif isinstance(step, EditFileAction) and step.path:
            self._record_latest_write(
                step.path, self._edited_content(step.path, step), call_key
            )

    def record_command(self, command: ShellCommand, call_key: ToolCallKey) -> None:
        """Record what a command writes, i.e. files it redirects to, `tee` files, `sed -i` files and the destination of `cp` or `mv`.

        `cat > f <<EOF` and `tee f <<EOF` show the content, and a copy of a file with known content keeps it. Every other write leaves the content unknown.
        That includes a cat that names a file, e.g. `cat header.sh > f <<EOF`, since cat then prints header.sh and not its heredoc.
        """
        words = program_words(command)
        program_name = words[0] if words else None
        writes_heredoc = program_name == "tee" or (
            program_name == "cat" and _cat_names_only_stdin(words)
        )
        heredoc = command.stdin_text if writes_heredoc else None
        # `2>&1` makes stderr the same destination as stdout, which is one write.
        destinations = (
            (command.stdout,)
            if command.stderr is command.stdout
            else (command.stdout, command.stderr)
        )
        for destination in destinations:
            if isinstance(destination, FileDestination):
                is_cat_output = program_name == "cat" and destination is command.stdout
                self._record_redirect_or_tee_write(
                    destination.path,
                    heredoc if is_cat_output else None,
                    destination.appends,
                    call_key,
                )
        for file in tee_file_destinations(command):
            self._record_redirect_or_tee_write(
                file.path, heredoc, file.appends, call_key
            )
        if program_name == "sed":
            parsed = parse_arguments("sed", words[1:])
            if parsed.has_option("-i", "--in-place"):
                for path in file_arguments("sed", parsed):
                    self._record_latest_write(path, None, call_key)
        elif program_name in ("cp", "mv"):
            self._record_copy(
                parse_arguments(program_name, words[1:]).plain_arguments, call_key
            )

    def latest_write(self, path: str) -> WrittenFile | None:
        """Find the latest write of the file a path names, with unknown content when the path can name several written files."""
        writes = [
            write
            for written_path, write in self._latest_write_of_path.items()
            if can_name_same_file(written_path, path)
        ]
        if not writes:
            return None
        latest = writes[-1]
        names_one_file = all(
            can_name_same_file(write.path, latest.path) for write in writes
        )
        return (
            latest
            if names_one_file
            else WrittenFile(latest.path, None, latest.written_by)
        )

    def _edited_content(self, path: str, step: EditFileAction) -> str | None:
        """Apply an edit to the known content of its file, or None when the content or the place of the edit is unknown."""
        write = self.latest_write(path)
        if write is None or write.content is None or step.old is None:
            return None
        if write.content.count(step.old) != 1:
            return None
        return write.content.replace(step.old, step.new or "")

    def _record_redirect_or_tee_write(
        self, path: str, content: str | None, appends: bool, call_key: ToolCallKey
    ) -> None:
        """Record a redirect or `tee` write, adding to the known content for `>>` and `tee -a`."""
        if appends and content is not None:
            write = self.latest_write(path)
            content = (
                write.content + content if write and write.content is not None else None
            )
        self._record_latest_write(path, content, call_key)

    def _record_copy(
        self, plain_arguments: tuple[str, ...], call_key: ToolCallKey
    ) -> None:
        """Record the destination of a `cp` or `mv` of one file, with the source's content when it is known, e.g. f.sh for `cp a.sh f.sh`.

        With several sources the destination is a directory, whose files the trial cannot tell apart, so nothing is recorded.
        """
        if len(plain_arguments) != 2:
            return
        source_path, destination_path = plain_arguments
        source = self.latest_write(source_path)
        content = source.content if source else None
        self._record_latest_write(destination_path, content, call_key)

    def _record_latest_write(
        self, path: str, content: str | None, call_key: ToolCallKey
    ) -> None:
        """Record the latest content of a path, moving it to the end of the write order."""
        self._latest_write_of_path.pop(path, None)
        self._latest_write_of_path[path] = WrittenFile(path, content, call_key)


def _cat_names_only_stdin(words: tuple[str, ...]) -> bool:
    """Check whether a cat command names no file other than `-` for stdin, e.g. `cat` or `cat -`, so that it prints only its stdin."""
    return all(
        path == "-" for path in file_arguments("cat", parse_arguments("cat", words[1:]))
    )
